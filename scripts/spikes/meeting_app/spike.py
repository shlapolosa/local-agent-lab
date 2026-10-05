"""SPIKE (exempt from TDD): one local service that answers S2 and S3 of the meeting-app plan and
records what S1 needs.

  S3  Does the Python Teams SDK host our bot? Logs install / meeting start / meeting end and
      card invokes; `card` in the meeting chat posts an Action.Execute card whose REFRESH is
      scoped to the sender — the organiser-only view — so a second person can confirm they see
      the neutral one.
  S2  /graph/notifications echoes Graph's validation token and logs every change notification.
  S1  every activity's meeting/organiser ids are logged so s1_rsc_fetch.py can call Graph with
      ONLY the app's RSC grant.

Everything lands in var/spike/meeting_app.jsonl. Run behind a tunnel:
    set -a && source .env && set +a && .venv/bin/python scripts/spikes/meeting_app/spike.py
"""
import json
import logging
logging.basicConfig(level=logging.INFO)
import os
import time
from pathlib import Path

from fastapi import FastAPI, Request, Response
from microsoft_teams.api import AdaptiveCardActionCardResponse, AdaptiveCardInvokeActivity
from microsoft_teams.apps import ActivityContext, App
from microsoft_teams.apps.http.fastapi_adapter import FastAPIAdapter
from microsoft_teams.cards import AdaptiveCard

LOG = Path("var/spike/meeting_app.jsonl")
LOG.parent.mkdir(parents=True, exist_ok=True)


def log(kind: str, data) -> None:
    with LOG.open("a") as f:
        f.write(json.dumps({"t": time.strftime("%H:%M:%S"), "kind": kind, "data": data}, default=str) + "\n")
    print(kind, json.dumps(data, default=str)[:400], flush=True)


web = FastAPI()


class AutomaticRefresh:
    """microsoft-teams-apps 2.1.0 types `value.trigger` as Literal["manual"], but Teams sends
    "automatic" for a card REFRESH — so every refresh fails validation before any handler runs
    (measured). The trigger carries nothing we route on (the verb does), so drop it. Auth is the
    Authorization header, not the body, so rewriting the body cannot weaken it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/api/messages":
            return await self.app(scope, receive, send)
        body, more = b"", True
        while more:
            msg = await receive()
            body += msg.get("body", b"")
            more = msg.get("more_body", False)
        try:
            act = json.loads(body)
            if isinstance(act.get("value"), dict) and act["value"].get("trigger") == "automatic":
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


web.add_middleware(AutomaticRefresh)


@web.post("/graph/notifications")
async def notifications(request: Request) -> Response:
    token = request.query_params.get("validationToken")
    if token:
        log("graph.validation", {"path": "notifications"})
        return Response(token, media_type="text/plain")
    log("graph.notification", await request.json())
    return Response(status_code=202)


@web.post("/graph/lifecycle")
async def lifecycle(request: Request) -> Response:
    token = request.query_params.get("validationToken")
    if token:
        return Response(token, media_type="text/plain")
    log("graph.lifecycle", await request.json())
    return Response(status_code=202)


app = App(client_id=os.environ["MEETING_APP_ID"], client_secret=os.environ["MEETING_APP_SECRET"],
          tenant_id=os.environ["ENTRA_TENANT_ID"], http_server_adapter=FastAPIAdapter(app=web))


def dump(ctx) -> dict:
    return ctx.activity.model_dump(by_alias=True, exclude_none=True)


@app.on_conversation_update
async def on_update(ctx):
    log("bot.conversation_update", dump(ctx))
    meeting = (dump(ctx).get("channelData") or {}).get("meeting") or {}
    if meeting.get("id"):
        info = await ctx.api.meetings.get_by_id(meeting["id"])
        log("bot.meeting_info", info.model_dump(by_alias=True, exclude_none=True))
    await ctx.send("Spike installed. Type `card` to test the organiser-only view.")


@app.on_meeting_start
async def on_start(ctx):
    log("bot.meeting_start", dump(ctx))
    await ctx.send("Meeting started (spike).")


@app.on_meeting_end
async def on_end(ctx):
    log("bot.meeting_end", dump(ctx))
    await ctx.send("Meeting ended (spike).")


def card(view: str, owner: str, mri: str) -> AdaptiveCard:
    """`owner` is the Entra object id (the authorisation check); `mri` is the Teams user id (29:…),
    which is what `refresh.userIds` matches — an Entra id there matches nobody (measured)."""
    body = {"neutral": "Awaiting the organiser to name the speakers.",
            "owner": "ORGANISER VIEW — samples, names and consent would be here.",
            "done": "Answer recorded (spike)."}[view]
    spec = {"type": "AdaptiveCard", "version": "1.5", "body": [{"type": "TextBlock", "text": body, "wrap": True}]}
    if view != "done":
        spec["refresh"] = {"action": {"type": "Action.Execute", "verb": "refresh", "data": {"owner": owner, "mri": mri}},
                           "userIds": [mri]}
    if view == "owner":
        spec["actions"] = [{"type": "Action.Execute", "verb": "submit", "title": "Submit",
                            "data": {"owner": owner, "mri": mri}}]
    return AdaptiveCard.model_validate(spec)


@app.on_message
async def on_message(ctx):
    log("bot.message", dump(ctx))
    if (ctx.activity.text or "").strip().lower().endswith("card"):
        owner, mri = ctx.activity.from_.aad_object_id, ctx.activity.from_.id
        log("bot.card_sent", {"owner": owner})
        await ctx.send(card("neutral", owner, mri))


@app.on_card_action_execute
async def on_execute(ctx: ActivityContext[AdaptiveCardInvokeActivity]):
    act = dump(ctx)
    log("bot.card_execute", act)
    value = act.get("value") or {}
    verb = (value.get("action") or {}).get("verb")
    data = (value.get("action") or {}).get("data") or {}
    owner, mri = data.get("owner"), data.get("mri")
    clicker = ctx.activity.from_.aad_object_id
    view = "neutral" if clicker != owner else ("owner" if verb == "refresh" else "done")
    return AdaptiveCardActionCardResponse(value=card(view, owner, mri))


if __name__ == "__main__":
    import asyncio
    asyncio.run(app.start(int(os.environ.get("SPIKE_PORT", "3978"))))
