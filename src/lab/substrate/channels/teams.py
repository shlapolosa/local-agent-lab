"""Microsoft Teams approval channel — the fourth consumer group on approvals:requests
(enabled when TEAMS_WEBHOOK_URL is set in .env; unset = disabled, plumbing only).

Same contract as the review app and Telegram: consume approvals:requests via consumer group
"teams", notify a human, and record the decision on approvals:decisions. Teams is where this
lab's reviewers already are (Copilot Studio agents live in the same client), so it is the
cheapest useful channel — no new plumbing, just an adapter.

OUTBOUND (wired today, zero extra infrastructure)
  An **Adaptive Card** POSTed to a Teams channel **Workflows** webhook — Teams → the channel → … →
  Workflows → "Post to a channel when a webhook request is received", whose URL is on
  api.powerautomate.com / api.powerplatform.com / flow.microsoft.com. That is `TEAMS_WEBHOOK_URL`.

  NOT a legacy O365 connector: those are GONE. Microsoft blocked new connectors in Aug 2024 and
  DISABLED the surviving ones on 18-22 May 2026, so a webhook.office.com URL no longer delivers and
  cannot be created. Workflows is the only path now. Nothing in this module changes for it — a
  Workflows webhook accepts the same `{"type":"message","attachments":[…]}` envelope the connector
  took, which is why this adapter needed no rewrite; only the URL's origin moved. The card carries what a reviewer needs to DECIDE: kind, subject, request id,
  requester, target domain, and the model summary (elements / relationships / views / violations /
  warnings), with violations called out in Attention red. Diagrams are NOT rendered in the card
  (same reasoning as Telegram: a card is not a canvas) — an `Action.OpenUrl` button links to the
  review app for the views, and a second one to the run's Jaeger trace.

INBOUND — two paths, both real, only one needs a bot:
  (a) WIRED: `Action.OpenUrl` -> the review app, where the human decides. An incoming webhook is
      send-only: Teams renders `Action.Submit` on a webhook card but has nothing to post it back
      to, so OpenUrl is the only action that works without a bot. This path is always available.
  (b) `decide(request_id, decision, actor, comment)` — the entry point a **Copilot Studio
      connector, a Teams outgoing webhook, or a bot** calls once it has captured the decision and
      the SIGNED-IN USER. The actor is the caller's, never an anonymous default: an empty actor is
      a ValueError, because "who approved this EA write" is the whole point of the audit log.
      OVER THE WIRE that entry point is the governed MCP tool `approvals_decide` on workflow-mcp
      (`lab.substrate.mcp.workflow.approval_tools`), reached through the gateway like every other
      capability — granted per team, metered, traced. Both it and this method call
      `approvals.human_decision`, so the Python path and the tool are ONE implementation and cannot
      diverge. What is still needed to close the loop in Teams is only the Microsoft side: a Copilot
      Studio agent with an MCP/custom connector to the gateway, carrying the signed-in user as
      `actor`. Note it needs no webhook — the inbound path works on a disabled channel.

Run: .venv/bin/python -m lab.substrate.channels.teams   (loop; exits immediately if not configured)
"""
import json

from lab.platform import config, streams
from lab.platform.contracts import ApprovalAudience
from lab.platform.webhook import post_json
from lab.substrate import approval_card, approvals



class TeamsChannel:
    # The three things that make a Teams channel a DISTINCT queue, so a second one (the steward's
    # vocabulary queue, `lab.substrate.channels.steward`) is a subclass overriding these and nothing
    # else: same card, same loop, same unacked-on-failure rule, same inbound `decide` binding.
    name = "teams"
    setting = "TEAMS_WEBHOOK_URL"                 # the config key its webhook comes from
    audience = ApprovalAudience.OWNER             # whose approvals it is told about (contracts)

    def __init__(self, webhook: str | None = None, *, post=None,
                 review_url: str = config.REVIEW_APP_URL, jaeger_url: str = config.JAEGER_UI_URL):
        """Settings come from lab.platform.config unless injected; `post(payload)` replaces the
        webhook call (tests) — default is the urllib adapter `_post`."""
        self.webhook = getattr(config, self.setting) if webhook is None else webhook
        self.enabled = bool(self.webhook)
        self.review_url = review_url
        self.jaeger_url = (jaeger_url or "").rstrip("/")
        if post is not None:
            self._post = post

    # --- outbound: request -> human ---
    def card(self, f):
        """The Teams message envelope wrapping one Adaptive Card. The card itself is
        `lab.substrate.approval_card` — shared with `GET /api/approvals/{id}/card`, so a low-code
        flow and this channel show a person the same thing."""
        content = approval_card.card(f, review_url=self.review_url, jaeger_url=self.jaeger_url,
                                     answers=self.answers_on_card)
        return {"type": "message", "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
            "content": content}]}

    #: Whether THIS channel's webhook is a flow that WAITS for a response. A card only carries inputs when
    #: something can receive them: Teams renders `Action.Submit` on any card, and a button that silently
    #: does nothing is worse than none — which is why the honest default is False and why it is a setting
    #: rather than a guess. Turn it on with the waiting flow, not before.
    answers_on_card: bool = False

    #: Who an ASK is addressed to. Empty = the room. A proactive message from the agent can reach only a
    #: PERSONAL chat (Microsoft's constraint, verified 11 Oct 2026), which turns out to be the right
    #: shape: an ask names one human, a channel broadcasts. The channel keeps the RECORD — what is open,
    #: who decided — and the DM carries the ASK. Interruption versus visibility, again.
    recipients: tuple[str, ...] = ()

    def notify(self, f):
        payload = self.card(f)
        if not self.enabled:
            print(f"[{self.name} not configured] would post:\n" + json.dumps(payload, indent=1)); return
        # Named people get the ask each in their own chat; with nobody named it goes to the room, which
        # is still VISIBLE. A gate whose question reaches nobody is the one outcome it may never produce.
        for who in self.recipients or ():
            self._post({**payload, "recipient": who})
        if not self.recipients:
            self._post(payload)

    # --- inbound: human -> decision (see the module docstring: path (b)) ---
    def decide(self, request_id, decision, actor, comment=""):
        """Record a decision taken in Teams. `actor` is the SIGNED-IN USER supplied by the caller
        (Copilot Studio / bot / outgoing webhook) — there is no anonymous default.

        This is a thin CHANNEL BINDING, not a second implementation: the rules (identified actor,
        legal decision, request still open) live once in `approvals.human_decision`, which the
        `approvals_decide` MCP tool calls with the same arguments — a Teams bot and a Copilot Studio
        connector therefore decide on identical terms. Raises ValueError for a missing actor, an
        unknown decision or an already-decided request; KeyError for an unknown request id."""
        return approvals.human_decision(request_id, decision, actor, self.name, comment)

    def _post(self, payload):
        """The substrate's one outbound JSON POST — shared with the meeting notifier, so the two
        sanctioned direct-egress paths cannot drift apart in timeout or encoding."""
        return post_json(self.webhook, payload)

    def deliver(self, eid, fields):
        """One request in front of a human. A failed send is deliberately left UNACKED: it stays in
        this group's pending list, `channel_events` reclaims it, and an outage delays a card rather
        than dropping the approval — the durability Streams were chosen over pub/sub to get."""
        try:
            self.notify(fields)
        except Exception as e:              # noqa: BLE001 — a webhook hiccup is not this card's end
            print(f'[{self.name}] send failed for {fields.get("request_id")}: {e}', flush=True)
            return
        # SAY SO ON SUCCESS TOO. Printing only on failure makes "sent every card" and "never saw an
        # event" produce byte-identical logs — which is exactly where an hour went when three
        # approvals were raised and no card arrived: the service was healthy, the webhook answered
        # 202, and nothing anywhere could say whether this channel had run at all. An instrument
        # that cannot report success is not an instrument. Ids only, never the subject: a subject is
        # free text a person typed.
        print(f'[{self.name}] card sent for {fields.get("request_id")}', flush=True)
        approvals.ack(self.name, eid)

    def probe(self):
        """Post ONE minimal card that touches no approval — proves the webhook flow is alive. Measured need
        (13 Sep 2026): a person saw no fabric card and nothing could say whether none was raised, none was
        sent, or the flow was dead. Ids and a timestamp only."""
        payload = {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive",
                   "content": {"type": "AdaptiveCard", "version": "1.4", "body": [
                       {"type": "TextBlock", "text": "fabric channel probe", "weight": "Bolder"},
                       {"type": "TextBlock", "text": f"{self.name} channel reachable at {_utc_now()} — no action needed", "wrap": True}]}}]}
        if not self.enabled:
            print(f"[{self.name} not configured] would post a probe card"); return
        self._post(payload)
        print(f"[{self.name}] probe sent", flush=True)

    def run(self):
        print(f"{self.name} channel: "
              f"{'enabled' if self.enabled else f'NOT configured (set {self.setting}) — plumbing only'}")
        if not self.enabled:
            return
        lag = approvals.channel_lag(self.name)
        backlog = f"backlog lag={lag['lag']} pending={lag['pending']}" if lag else "backlog unknown"
        # The SHARED loop, and this is the change that matters: a channel used to run an unguarded
        # `while True` with no signal handler, so a Redis blip ended the only thing telling anyone an
        # approval was waiting, and a container stop killed it mid-delivery. The two newer consumers
        # were fixed for exactly that and the fix never came back here, because there was nothing
        # shared to fix.
        # `audience` is what separates two Teams channels reading the ONE durable stream: the
        # filter is asked for here and applied in `channel_events`, so the events this channel will
        # never show are acked there rather than silently left in its pending list.
        streams.serve(name=f"{self.name} channel", ready=f"{self.name} channel serving  {backlog}",
                      read=lambda: approvals.channel_events(self.name, block_ms=streams.BLOCK_MS,
                                                            audience=self.audience),
                      handle=self.deliver)


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    import sys
    TeamsChannel().probe() if "--probe" in sys.argv[1:] else TeamsChannel().run()
