"""The meeting app's process: the Teams SDK adapted to `bot`, a Graph notification route, and the two
listeners — one FastAPI app, one event loop.

Everything that DECIDES lives in `bot`, `notifications` and `channel`; this module only translates.
Two facts about the SDK (microsoft-teams-apps 2.1.0, measured 5 Oct 2026) shape it:

* `AutomaticRefresh`: Teams sends `value.trigger: "automatic"` when a card refreshes, the SDK types
  that field `Literal["manual"]`, and so EVERY refresh failed validation (500) before any handler ran —
  the organiser's view could never load. The field carries nothing we route on (the verb does), so it
  is dropped before the SDK parses the body. Auth is the Authorization header, which this never touches.
* In a group or meeting chat the bot receives only messages that @mention it; the commands assume so.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, Request, Response

from lab.platform import config
from lab.substrate.meetingapp import bot, channel, notifications, registry, subscriptions

__all__ = ["AutomaticRefresh", "web", "main"]

LISTEN_EVERY_S = 3
RENEW_EVERY_S = 15 * 60


class AutomaticRefresh:
    """ASGI middleware: drop `value.trigger == "automatic"` from bot activities (see module doc)."""

    def __init__(self, app, path: str = "/api/messages"):
        self.app, self.path = app, path

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != self.path:
            return await self.app(scope, receive, send)
        body, more = b"", True
        while more:
            msg = await receive()
            body += msg.get("body", b"")
            more = msg.get("more_body", False)
        try:
            act = json.loads(body)
            if isinstance(act, dict) and isinstance(act.get("value"), dict) and act["value"].get("trigger") == "automatic":
                del act["value"]["trigger"]
                body = json.dumps(act).encode()
        except ValueError:
            pass
        sent = False

        async def replay():
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await self.app(scope, replay, send)


def web(*, client_state: str, handle=notifications.handle) -> FastAPI:
    """The non-bot routes. Graph's validation handshake is echoed; a notification is handled off the
    event loop and answered 202 at once — Graph retries a slow endpoint and then drops it."""
    app = FastAPI()
    app.add_middleware(AutomaticRefresh)

    @app.post("/graph/notifications")
    async def graph_notifications(request: Request) -> Response:
        token = request.query_params.get("validationToken")
        if token:
            return Response(token, media_type="text/plain")
        try:
            body = await request.json()
        except ValueError:
            return Response(status_code=400)
        asyncio.get_running_loop().run_in_executor(None, lambda: handle(body, client_state=client_state))
        return Response(status_code=202)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True}

    return app


def _dump(model) -> dict:
    return model.model_dump(by_alias=True, exclude_none=True) if model is not None else {}


def teams(web_app: FastAPI):  # pragma: no cover — SDK wiring; the decisions are tested in `bot`
    import uvicorn
    from microsoft_teams.api import AdaptiveCardActionCardResponse, MessageActivityInput
    from microsoft_teams.apps import App
    from microsoft_teams.apps.http.fastapi_adapter import FastAPIAdapter
    from microsoft_teams.cards import AdaptiveCard

    adapter = FastAPIAdapter(app=web_app, server_factory=lambda fa: uvicorn.Server(
        uvicorn.Config(app=fa, host=config.BIND_HOST, port=config.MEETING_APP_PORT, log_level="info")))
    app = App(client_id=config.MEETING_APP_ID, client_secret=config.MEETING_APP_SECRET,
              tenant_id=config.ENTRA_TENANT_ID, http_server_adapter=adapter)

    def card(spec: dict) -> AdaptiveCard:
        return AdaptiveCard.model_validate(spec)

    def registered(ctx):
        m = registry.by_chat(ctx.activity.conversation.id)
        return m if m is not None and not m.paused else None

    @app.on_conversation_update
    async def installed(ctx):
        act = _dump(ctx.activity)
        added = {m.get("id") for m in act.get("membersAdded") or []}
        meeting = (act.get("channelData") or {}).get("meeting") or {}
        if ctx.activity.recipient.id not in added or not meeting.get("id"):
            return
        info = _dump(await ctx.api.meetings.get_by_id(meeting["id"]))
        welcome = await asyncio.to_thread(bot.on_install, act, info)
        if welcome:
            await ctx.send(card(welcome))

    @app.on_meeting_start
    async def started(ctx):
        if registered(ctx):
            await ctx.send("Meeting Notes is on. Press **Record** (with transcription) for the minutes.")

    @app.on_meeting_end
    async def ended(ctx):
        if registered(ctx):
            await ctx.send("Meeting ended. If it was recorded, the speaker question follows here shortly.")

    @app.on_message
    async def command(ctx):
        said = await asyncio.to_thread(bot.on_command, _dump(ctx.activity))
        if said:
            await ctx.send(said)

    @app.on_card_action_execute
    async def execute(ctx):
        act = _dump(ctx.activity)
        verb = ((act.get("value") or {}).get("action") or {}).get("verb")
        actor = ""
        if verb == "submit":
            member = await ctx.api.conversations.get_member_by_id(ctx.activity.conversation.id, ctx.activity.from_.id)
            actor = member.user_principal_name or member.email or ctx.activity.from_.aad_object_id or ""
        shown = await asyncio.to_thread(lambda: bot.on_card(act, actor=actor))
        approval_id = (((act.get("value") or {}).get("action") or {}).get("data") or {}).get("approval_id", "")
        posted = registry.card_of(approval_id) if verb == "submit" and "refresh" not in shown else None
        if posted:
            # close the card for EVERYONE, not only the organiser who answered it
            await ctx.api.conversations.update_activity(posted[0], posted[1],
                                                        MessageActivityInput().add_card(card(shown)))
        return AdaptiveCardActionCardResponse(value=card(shown))

    async def post(meeting, spec: dict) -> str:
        sent = await app.send(meeting.chat_id, card(spec), service_url=meeting.service_url)
        return sent.id

    return app, post


async def _listen(post) -> None:  # pragma: no cover — a timer around two tested passes
    channel.ensure()
    while True:
        for one in (channel.approvals_pass, channel.minutes_pass):
            try:
                await one(post)
            except Exception as e:              # noqa: BLE001 — a Redis blip costs a tick, never the loop
                print(f"[meeting-app] {one.__name__}: {type(e).__name__}: {e}", flush=True)
        await asyncio.sleep(LISTEN_EVERY_S)


async def _renew() -> None:  # pragma: no cover — a timer around tested `subscriptions.ensure`
    from lab.substrate.mcp.graph import graph_auth
    from lab.substrate.mcp.graph.graph_rest import GraphClient
    client = GraphClient(graph_auth.token_source("app", tenant_id=config.ENTRA_TENANT_ID,
                                                 client_id=config.MEETING_APP_ID,
                                                 client_secret=config.MEETING_APP_SECRET),
                         base_url=config.GRAPH_BASE_URL)
    while True:
        try:
            said = await asyncio.to_thread(subscriptions.ensure, client, catalog_id=config.MEETING_APP_CATALOG_ID,
                                           base_url=config.MEETING_APP_PUBLIC_URL,
                                           client_state=config.MEETING_APP_NOTIFY_STATE)
            print(f"[meeting-app] recordings subscription {said}", flush=True)
        except Exception as e:                  # noqa: BLE001
            print(f"[meeting-app] subscription not kept ({type(e).__name__}: {e})", flush=True)
        await asyncio.sleep(RENEW_EVERY_S)


def main() -> None:  # pragma: no cover — composition root of the process
    missing = [k for k in ("MEETING_APP_ID", "MEETING_APP_SECRET", "MEETING_APP_PUBLIC_URL",
                           "MEETING_APP_CATALOG_ID", "MEETING_APP_NOTIFY_STATE") if not getattr(config, k)]
    if missing:
        raise SystemExit(f"meeting-app is not configured: set {', '.join(missing)}")
    web_app = web(client_state=config.MEETING_APP_NOTIFY_STATE)
    app, post = teams(web_app)

    async def run():
        await app.initialize()
        await asyncio.gather(app.start(config.MEETING_APP_PORT), _listen(post), _renew())
    # "channel: enabled" is the readiness line lab.sh waits for, as for every approval channel
    print(f"meeting-app channel: enabled (build {config.BUILD_SHA or '?'}, :{config.MEETING_APP_PORT})", flush=True)
    asyncio.run(run())


if __name__ == "__main__":  # pragma: no cover
    main()
