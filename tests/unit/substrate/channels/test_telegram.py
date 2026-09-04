"""lab.substrate.channels.telegram — the Telegram approval channel, OFFLINE: token/chat and the Bot API
are constructor-injected (a recorded fake), approvals.decide/channel_events/ack are patched; no env.
Run: pytest tests/unit/substrate/channels/test_telegram.py (or as a script)."""
import io
import json
import urllib.request
from contextlib import redirect_stdout

import pytest

from lab.substrate import approvals
from lab.substrate.channels import telegram as T

REQ = {"request_id": "apr-1", "kind": "adoit-import", "subject": "claims", "requester": "architect",
       "payload": json.dumps({"summary": {"elements": 3, "relations": 2, "views": 1, "violations": 0, "warnings": 1}})}


def _enabled():
    def fake_api(method, **params):
        ch.sent.append((method, params))
        return ch.updates if method == "getUpdates" else {"ok": True}
    ch = T.TelegramChannel("tok", "42", api=fake_api, review_url="http://review.test")
    ch.sent, ch.updates = [], {"result": []}
    return ch


def test_disabled_without_token_and_chat():
    ch = T.TelegramChannel("", "")
    assert not ch.enabled and ch.offset == 0
    out = io.StringIO()
    with redirect_stdout(out):
        ch.notify(REQ)                 # prints the message instead of sending it
        assert ch.poll_commands() is None
        assert ch.run() is None        # exits immediately
    text = out.getvalue()
    assert "[telegram not configured]" in text and "apr-1" in text and "3 elements" in text
    assert "NOT configured" in text


def test_settings_default_to_config():
    ch = T.TelegramChannel()
    assert ch.token == T.config.TELEGRAM_BOT_TOKEN and ch.chat == T.config.TELEGRAM_CHAT_ID
    assert ch.review_url == T.config.REVIEW_APP_URL and ch._call.__func__ is T.TelegramChannel._call


def test_notify_sends_summary_with_review_link_and_commands():
    ch = _enabled()
    ch.notify(REQ)
    (method, params), = ch.sent
    assert method == "sendMessage" and params["chat_id"] == "42"
    txt = params["text"]
    assert "Approval needed: adoit-import — claims" in txt and "id apr-1 from architect" in txt
    assert "3 elements, 2 relationships, 1 views, 0 violations, 1 warnings" in txt
    assert "Diagrams: http://review.test" in txt and "/approve apr-1" in txt and "/decline apr-1" in txt


def test_poll_commands_records_decisions_and_reports_errors(monkeypatch):
    ch = _enabled()
    decided = []

    def fake_decide(rid, decision, actor, channel, comment):
        if rid == "missing":
            raise KeyError(rid)
        decided.append((rid, decision, actor, channel, comment))
    monkeypatch.setattr(approvals, "decide", fake_decide)
    ch.updates = {"result": [
        {"update_id": 7, "message": {"text": "hello", "from": {"username": "bob"}}},                 # not a command
        {"update_id": 8, "message": {"text": "/approve apr-1", "from": {"username": "bob"}}},
        {"update_id": 9, "message": {"text": "/decline@labbot apr-2 too big", "from": {"id": 99}}},  # @bot suffix, id actor
        {"update_id": 10, "message": {"text": "/update", "from": {"username": "bob"}}},              # no id -> ignored
        {"update_id": 11, "message": {"text": "/frobnicate apr-3", "from": {"username": "bob"}}},     # unknown -> ignored
        {"update_id": 12, "message": {"text": "/approve missing", "from": {"username": "bob"}}},      # decide raises
    ]}
    ch.poll_commands()
    assert ch.offset == 13                                     # every update acknowledged
    assert decided == [("apr-1", "approve", "bob", "telegram", ""),
                       ("apr-2", "decline", "99", "telegram", "too big")]
    replies = [p["text"] for m, p in ch.sent if m == "sendMessage"]
    assert replies == ["Recorded approve for apr-1", "Recorded decline for apr-2", "Error: 'missing'"]
    assert ch.sent[0] == ("getUpdates", {"offset": 0, "timeout": 0})


def test_call_posts_urlencoded_form_to_the_bot_api(monkeypatch):
    """The one test of the real urllib adapter."""
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(url, data=None, timeout=None):
        seen.update(url=url, data=data, timeout=timeout)
        return Resp(b'{"ok": true, "result": []}')
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    out = T.TelegramChannel("tok", "42")._call("getUpdates", offset=3, timeout=0)
    assert out == {"ok": True, "result": []}
    assert seen["url"] == "https://api.telegram.org/bottok/getUpdates"
    assert seen["data"] == b"offset=3&timeout=0" and seen["timeout"] == 30


def test_run_loop_notifies_acks_polls_and_sleeps(monkeypatch):
    ch = _enabled()
    acked, polled = [], []
    monkeypatch.setattr(approvals, "channel_events", lambda name, block_ms: [("e1", REQ)])
    monkeypatch.setattr(approvals, "ack", lambda name, eid: acked.append((name, eid)))
    monkeypatch.setattr(ch, "poll_commands", lambda: polled.append(1))

    class Stop(Exception):
        pass
    monkeypatch.setattr(T.time, "sleep", lambda s: (_ for _ in ()).throw(Stop()))
    with pytest.raises(Stop):
        ch.run()
    assert acked == [("telegram", "e1")] and polled == [1]
    assert ch.sent and ch.sent[0][0] == "sendMessage"


def test_main_entry_runs_the_channel(monkeypatch):
    monkeypatch.setattr(T.config, "TELEGRAM_BOT_TOKEN", None)
    monkeypatch.setattr(T.config, "TELEGRAM_CHAT_ID", None)
    import runpy
    out = io.StringIO()
    with redirect_stdout(out):
        runpy.run_module("lab.substrate.channels.telegram", run_name="__main__")
    assert "NOT configured" in out.getvalue()


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q", "-p", "no:warnings"]))
