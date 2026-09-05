"""Microsoft Teams approval channel — the fourth consumer group on approvals:requests
(enabled when TEAMS_WEBHOOK_URL is set in .env; unset = disabled, plumbing only).

Same contract as the review app and Telegram: consume approvals:requests via consumer group
"teams", notify a human, and record the decision on approvals:decisions. Teams is where this
lab's reviewers already are (Copilot Studio agents live in the same client), so it is the
cheapest useful channel — no new plumbing, just an adapter.

OUTBOUND (wired today, zero extra infrastructure)
  An **Adaptive Card** POSTed to an incoming webhook (a Teams channel "Workflow"/Power Automate
  webhook, or a legacy O365 connector — both accept the same `{"type":"message","attachments":[…]}`
  envelope). The card carries what a reviewer needs to DECIDE: kind, subject, request id,
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
import time
import urllib.request

from lab.platform import config
from lab.substrate import approvals

MAX_SAMPLE = 160        # a sample is evidence for recognition, not a transcript excerpt
CARD_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"
CARD_VERSION = "1.4"                    # Teams renders up to 1.5; 1.4 is the safe floor everywhere
SUMMARY_FACTS = (("Elements", "elements"), ("Relationships", "relations"), ("Views", "views"),
                 ("Violations", "violations"), ("Warnings", "warnings"))


class TeamsChannel:
    name = "teams"

    def __init__(self, webhook: str | None = None, *, post=None,
                 review_url: str = config.REVIEW_APP_URL, jaeger_url: str = config.JAEGER_UI_URL):
        """Settings come from lab.platform.config unless injected; `post(payload)` replaces the
        webhook call (tests) — default is the urllib adapter `_post`."""
        self.webhook = config.TEAMS_WEBHOOK_URL if webhook is None else webhook
        self.enabled = bool(self.webhook)
        self.review_url = review_url
        self.jaeger_url = (jaeger_url or "").rstrip("/")
        if post is not None:
            self._post = post

    # --- outbound: request -> human ---
    def card(self, f):
        """The Teams message envelope wrapping one Adaptive Card. Pure — no I/O, so it is the thing
        the tests assert on.

        Payload-driven, never kind-driven. An approval that carries a `question` is rendered as one;
        an approval that carries a `summary` is rendered as one. Nothing here dispatches on the
        approval KIND, which is what lets a new kind of question reach every channel without any of
        them being edited — the same property the review app and the approval tools keep.
        """
        payload = json.loads(f.get("payload") or "{}") or {}
        question = payload.get("question") or {}
        body = [{"type": "TextBlock", "text": f'Approval needed: {f["kind"]}',
                 "weight": "Bolder", "size": "Large", "wrap": True},
                {"type": "TextBlock", "text": f.get("subject", ""), "spacing": "None",
                 "isSubtle": True, "wrap": True}]
        body += self._question_blocks(question) if question else self._summary_blocks(f, payload)

        # The deep link carries the request id: a reviewer with three approvals open should not have
        # to go and find theirs.
        # The label says what the reviewer is actually being asked to do — answering a question and
        # releasing a staged write are different acts and should not read the same.
        actions = [{"type": "Action.OpenUrl",
                    "title": "Answer in the review app" if question else "Review & decide",
                    "url": f'{self.review_url.rstrip("/")}?approval={f["request_id"]}'}]
        trace = approvals.trace_url(f.get("trace_id"), self.jaeger_url)   # one link construction
        if trace:
            actions.append({"type": "Action.OpenUrl", "title": "Open trace", "url": trace})
        return {"type": "message", "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
            "content": {"$schema": CARD_SCHEMA, "type": "AdaptiveCard", "version": CARD_VERSION,
                        "body": body, "actions": actions}}]}

    def _question_blocks(self, question) -> list:
        """One row per thing a human must identify.

        What a person actually needs to tell two voices apart is how long each spoke, how often, and
        a line they said — so all three are on the card. No `Action.Submit`: an incoming webhook is
        SEND-ONLY, Teams renders a submit button and has nowhere to post it, and a button that
        silently does nothing is worse than none. The card says where to answer instead.
        """
        blocks = [{"type": "TextBlock", "text": question.get("prompt", ""), "wrap": True}]
        for item in question.get("items") or []:
            said = " · ".join(str(s)[:MAX_SAMPLE] for s in (item.get("samples") or [])[:2])
            blocks.append({"type": "Container", "separator": True, "items": [
                {"type": "FactSet", "facts": [
                    {"title": item.get("label", "?"),
                     "value": f'{round(float(item.get("seconds") or 0))}s · '
                              f'{item.get("turns", 0)} turns'}]},
                *([{"type": "TextBlock", "text": said, "wrap": True, "isSubtle": True,
                    "spacing": "None"}] if said else []),
            ]})
        blocks.append({"type": "TextBlock", "isSubtle": True, "wrap": True,
                       "text": "Answer in the review app, or through a flow that posts this card and "
                               "waits for a response — a webhook card cannot send an answer back."})
        return blocks

    def _summary_blocks(self, f, payload) -> list:
        """The staged-model summary: counts, the target domain, and violations called out in red."""
        s = payload.get("summary") or {}
        facts = [{"title": "Request", "value": f["request_id"]},
                 {"title": "Requester", "value": f.get("requester", "?")}]
        if s.get("domain"):
            facts.append({"title": "Domain", "value": str(s["domain"])})
        facts += [{"title": t, "value": str(s.get(k, "?"))} for t, k in SUMMARY_FACTS]
        out = [{"type": "FactSet", "facts": facts}]
        if s.get("violations"):
            out.append({"type": "TextBlock", "color": "Attention", "weight": "Bolder", "wrap": True,
                        "text": f'{s["violations"]} validation violation(s) — review before approving.'})
        out.append({"type": "TextBlock", "isSubtle": True, "wrap": True,
                    "text": "Diagrams are not shown here — open the review app for the views and to decide."})
        return out

    def notify(self, f):
        payload = self.card(f)
        if not self.enabled:
            print("[teams not configured] would post:\n" + json.dumps(payload, indent=1)); return
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
        req = urllib.request.Request(self.webhook, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode()

    def run(self):
        print(f"teams channel: {'enabled' if self.enabled else 'NOT configured (set TEAMS_WEBHOOK_URL) — plumbing only'}")
        if not self.enabled:
            return
        while True:
            for eid, f in approvals.channel_events(self.name, block_ms=5000):
                try:
                    self.notify(f)
                except Exception as e:      # a webhook hiccup must not kill the channel; the entry is
                    print(f'[teams] send failed for {f.get("request_id")}: {e}')   # left UNACKED, so it
                    continue                # stays in this group's pending list and is not lost
                approvals.ack(self.name, eid)
            time.sleep(1)


if __name__ == "__main__":
    TeamsChannel().run()
