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
      Wiring (b) end-to-end needs a bot/agent registration (Copilot Studio topic + a custom
      connector or Power Automate flow calling this process); until then (a) carries the decision.
      Note `decide()` needs no webhook — the inbound path works on a disabled channel.

Run: .venv/bin/python -m lab.substrate.channels.teams   (loop; exits immediately if not configured)
"""
import json
import time
import urllib.request

from lab.platform import config
from lab.substrate import approvals

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
        """The Teams message envelope wrapping one Adaptive Card. Pure — no I/O, so it is the
        thing the tests assert on."""
        s = (json.loads(f.get("payload") or "{}") or {}).get("summary", {})
        facts = [{"title": "Request", "value": f["request_id"]},
                 {"title": "Requester", "value": f.get("requester", "?")}]
        if s.get("domain"):
            facts.append({"title": "Domain", "value": str(s["domain"])})
        facts += [{"title": t, "value": str(s.get(k, "?"))} for t, k in SUMMARY_FACTS]

        body = [{"type": "TextBlock", "text": f'Approval needed: {f["kind"]}',
                 "weight": "Bolder", "size": "Large", "wrap": True},
                {"type": "TextBlock", "text": f.get("subject", ""), "spacing": "None",
                 "isSubtle": True, "wrap": True},
                {"type": "FactSet", "facts": facts}]
        if s.get("violations"):
            body.append({"type": "TextBlock", "color": "Attention", "weight": "Bolder", "wrap": True,
                         "text": f'{s["violations"]} validation violation(s) — review before approving.'})
        body.append({"type": "TextBlock", "isSubtle": True, "wrap": True,
                     "text": "Diagrams are not shown here — open the review app for the views and to decide."})

        actions = [{"type": "Action.OpenUrl", "title": "Review & decide", "url": self.review_url}]
        if f.get("trace_id"):
            actions.append({"type": "Action.OpenUrl", "title": "Open trace",
                            "url": f'{self.jaeger_url}/trace/{f["trace_id"]}'})
        return {"type": "message", "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
            "content": {"$schema": CARD_SCHEMA, "type": "AdaptiveCard", "version": CARD_VERSION,
                        "body": body, "actions": actions}}]}

    def notify(self, f):
        payload = self.card(f)
        if not self.enabled:
            print("[teams not configured] would post:\n" + json.dumps(payload, indent=1)); return
        self._post(payload)

    # --- inbound: human -> decision (see the module docstring: path (b)) ---
    def decide(self, request_id, decision, actor, comment=""):
        """Record a decision taken in Teams. `actor` is the SIGNED-IN USER supplied by the caller
        (Copilot Studio / bot / outgoing webhook) — there is no anonymous default. Raises ValueError
        for a missing actor or an unknown decision, KeyError for an unknown request id."""
        actor = (actor or "").strip()
        if not actor:
            raise ValueError("actor is required — a Teams decision must carry the signed-in user")
        return approvals.decide(request_id, decision, actor, self.name, comment)

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
