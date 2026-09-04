"""Telegram approval channel — PLUMBING ONLY (enhancement; enabled when
TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set in .env).

Same contract as the review app: consume approvals:requests via consumer group
"telegram", notify a human, and record decisions on approvals:decisions. Telegram can't show
the diagrams (screen limits), so the notification carries the summary + a link to the review
app for the visuals; the decision itself can still be taken here.

Commands understood in the chat:  /approve <id> [comment] | /decline <id> <comment> | /update <id> <comment>
Run: .venv/bin/python -m lab.substrate.channels.telegram   (long-poll loop; exits immediately if not configured)
"""
import json
import time
import urllib.parse
import urllib.request

from lab.platform import config
from lab.substrate import approvals

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramChannel:
    name = "telegram"

    def __init__(self, token: str | None = None, chat: str | None = None, *, api=None,
                 review_url: str = config.REVIEW_APP_URL):
        """Settings come from lab.platform.config unless injected; `api(method, **params)` replaces the
        Bot API call (tests) — default is the urllib adapter `_call`."""
        self.token = config.TELEGRAM_BOT_TOKEN if token is None else token
        self.chat = config.TELEGRAM_CHAT_ID if chat is None else chat
        self.enabled = bool(self.token and self.chat)
        self.offset = 0
        self.review_url = review_url
        if api is not None:
            self._call = api

    # --- outbound: request -> human ---
    def notify(self, f):
        p = json.loads(f["payload"]); s = p.get("summary", {})
        text = (f'Approval needed: {f["kind"]} — {f["subject"]}\n'
                f'id {f["request_id"]} from {f["requester"]}\n'
                f'{s.get("elements","?")} elements, {s.get("relations","?")} relationships, '
                f'{s.get("views","?")} views, {s.get("violations","?")} violations, {s.get("warnings","?")} warnings\n'
                f'Diagrams: {self.review_url}\n'
                f'Reply: /approve {f["request_id"]}  |  /decline {f["request_id"]} <reason>  |  /update {f["request_id"]} <changes>')
        if not self.enabled:
            print("[telegram not configured] would send:\n" + text); return
        self._call("sendMessage", chat_id=self.chat, text=text)

    # --- inbound: human -> decision ---
    def poll_commands(self):
        if not self.enabled:
            return
        for u in self._call("getUpdates", offset=self.offset, timeout=0).get("result", []):
            self.offset = u["update_id"] + 1
            msg = u.get("message", {}); txt = msg.get("text", "")
            if not txt.startswith("/"):
                continue
            parts = txt.split(maxsplit=2)
            cmd = parts[0].lstrip("/").split("@")[0]
            if cmd in approvals.DECISIONS and len(parts) >= 2:
                actor = msg.get("from", {}).get("username") or str(msg.get("from", {}).get("id"))
                try:
                    approvals.decide(parts[1], cmd, actor, self.name, parts[2] if len(parts) > 2 else "")
                    self._call("sendMessage", chat_id=self.chat, text=f"Recorded {cmd} for {parts[1]}")
                except (KeyError, ValueError) as e:
                    self._call("sendMessage", chat_id=self.chat, text=f"Error: {e}")

    def _call(self, method, **params):
        data = urllib.parse.urlencode(params).encode()
        with urllib.request.urlopen(API.format(token=self.token, method=method), data=data, timeout=30) as r:
            return json.load(r)

    def run(self):
        print(f"telegram channel: {'enabled' if self.enabled else 'NOT configured — plumbing only'}")
        if not self.enabled:
            return
        while True:
            for eid, f in approvals.channel_events(self.name, block_ms=5000):
                self.notify(f); approvals.ack(self.name, eid)
            self.poll_commands()
            time.sleep(1)


if __name__ == "__main__":
    TelegramChannel().run()
