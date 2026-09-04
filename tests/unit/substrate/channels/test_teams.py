"""lab.substrate.channels.teams — the Microsoft Teams approval channel, OFFLINE: the webhook URL and the
HTTP POST are constructor-injected (a recorded fake), approvals.decide/channel_events/ack are patched;
no env, no network, no Redis.
Run: pytest tests/unit/substrate/channels/test_teams.py (or as a script)."""
import io
import json
import urllib.request
from contextlib import redirect_stdout

import pytest

from lab.substrate import approvals
from lab.substrate.channels import teams as T

REQ = {"request_id": "apr-1", "kind": "adoit-import", "subject": "claims", "requester": "architect",
       "trace_id": "abc123def456", "payload": json.dumps(
           {"xml_ref": "art://x/claims.archimate.xml",
            "summary": {"elements": 3, "relations": 2, "views": 1, "violations": 0, "warnings": 1,
                        "domain": "Claims", "new_elements": 3}})}


def _enabled(**kw):
    def fake_post(payload):
        ch.sent.append(payload)
        return "1"
    ch = T.TeamsChannel("https://hook.test/x", post=fake_post,
                        review_url="http://review.test", jaeger_url="http://jaeger.test", **kw)
    ch.sent = []
    return ch


def _card(payload):
    """The Adaptive Card inside the Teams message envelope."""
    return payload["attachments"][0]["content"]


def _facts(card):
    fs, = [b for b in card["body"] if b["type"] == "FactSet"]
    return {f["title"]: f["value"] for f in fs["facts"]}


# ------------------------------------------------------------------ configuration / disabled
def test_settings_default_to_config():
    ch = T.TeamsChannel()
    assert ch.webhook == T.config.TEAMS_WEBHOOK_URL
    assert ch.review_url == T.config.REVIEW_APP_URL and ch.jaeger_url == T.config.JAEGER_UI_URL
    assert ch._post.__func__ is T.TeamsChannel._post          # the real urllib adapter, not injected


def test_disabled_without_webhook_prints_instead_of_sending():
    ch = T.TeamsChannel("")
    assert not ch.enabled
    out = io.StringIO()
    with redirect_stdout(out):
        ch.notify(REQ)                    # prints the card instead of posting it
        assert ch.run() is None           # exits immediately
    text = out.getvalue()
    assert "[teams not configured]" in text and "apr-1" in text and "NOT configured" in text
    assert "TEAMS_WEBHOOK_URL" in text


# ------------------------------------------------------------------ outbound: the Adaptive Card
def test_card_carries_everything_a_reviewer_needs_to_decide():
    ch = _enabled()
    ch.notify(REQ)
    payload, = ch.sent
    assert payload["type"] == "message"
    att, = payload["attachments"]
    assert att["contentType"] == "application/vnd.microsoft.card.adaptive" and att["contentUrl"] is None
    card = _card(payload)
    assert card["type"] == "AdaptiveCard" and card["version"] == "1.4"
    assert card["$schema"].endswith("adaptive-card.json")

    texts = " ".join(b.get("text", "") for b in card["body"] if b["type"] == "TextBlock")
    assert "adoit-import" in texts and "claims" in texts
    assert "Diagrams" in texts                                     # says where the visuals are

    assert _facts(card) == {"Request": "apr-1", "Requester": "architect", "Domain": "Claims",
                            "Elements": "3", "Relationships": "2", "Views": "1",
                            "Violations": "0", "Warnings": "1"}

    actions = {a["title"]: a for a in card["actions"]}
    assert all(a["type"] == "Action.OpenUrl" for a in actions.values())
    assert actions["Review & decide"]["url"] == "http://review.test"
    assert actions["Open trace"]["url"] == "http://jaeger.test/trace/abc123def456"


def test_card_degrades_gracefully_without_summary_or_trace():
    ch = _enabled()
    ch.notify({"request_id": "apr-2", "kind": "adoit-import", "subject": "x", "requester": "bot",
               "payload": json.dumps({})})
    card = _card(ch.sent[0])
    facts = _facts(card)
    assert facts["Elements"] == "?" and facts["Violations"] == "?" and "Domain" not in facts
    assert [a["title"] for a in card["actions"]] == ["Review & decide"]      # no trace -> no trace button


def test_violations_are_flagged_attention():
    ch = _enabled()
    bad = dict(REQ, payload=json.dumps({"summary": {"elements": 1, "relations": 0, "views": 1,
                                                    "violations": 4, "warnings": 0}}))
    ch.notify(bad)
    card = _card(ch.sent[0])
    warn, = [b for b in card["body"] if b["type"] == "TextBlock" and b.get("color") == "Attention"]
    assert "4" in warn["text"] and "violation" in warn["text"].lower()


def test_post_sends_json_to_the_webhook(monkeypatch):
    """The one test of the real urllib adapter."""
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        seen.update(url=req.full_url, data=req.data, headers=req.headers, timeout=timeout)
        return Resp(b"1")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    out = T.TeamsChannel("https://hook.test/x")._post({"type": "message"})
    assert out == "1"
    assert seen["url"] == "https://hook.test/x" and seen["timeout"] == 30
    assert json.loads(seen["data"]) == {"type": "message"}
    assert seen["headers"]["Content-type"] == "application/json"


# ------------------------------------------------------------------ inbound: decisions
def test_decide_records_through_approvals_with_the_callers_actor(monkeypatch):
    recorded = []
    monkeypatch.setattr(approvals, "decide",
                        lambda *a: recorded.append(a) or {"decision": a[1], "actor": a[2]})
    ch = _enabled()
    out = ch.decide("apr-1", "approve", "maria@contoso.com", "looks right")
    assert recorded == [("apr-1", "approve", "maria@contoso.com", "teams", "looks right")]
    assert out["decision"] == "approve"
    ch.decide("apr-1", "update", "  maria@contoso.com  ")           # actor trimmed, comment optional
    assert recorded[1] == ("apr-1", "update", "maria@contoso.com", "teams", "")


def test_decide_requires_a_real_actor(monkeypatch):
    called = []
    monkeypatch.setattr(approvals, "decide", lambda *a: called.append(a))
    ch = _enabled()
    for bad in (None, "", "   "):
        with pytest.raises(ValueError, match="actor"):
            ch.decide("apr-1", "approve", bad)
    assert called == []                                              # never an anonymous default


def test_decide_propagates_unknown_id_and_invalid_decision(monkeypatch):
    def fake_decide(rid, decision, actor, channel, comment):
        if decision not in approvals.DECISIONS:
            raise ValueError("decision must be one of ...")
        raise KeyError(f"unknown request {rid}")
    monkeypatch.setattr(approvals, "decide", fake_decide)
    ch = _enabled()
    with pytest.raises(KeyError):
        ch.decide("apr-nope", "approve", "maria")
    with pytest.raises(ValueError):
        ch.decide("apr-1", "frobnicate", "maria")


def test_decide_works_even_when_outbound_is_not_configured(monkeypatch):
    """The inbound path needs no webhook: a connector can record a decision on a disabled channel."""
    recorded = []
    monkeypatch.setattr(approvals, "decide", lambda *a: recorded.append(a))
    T.TeamsChannel("").decide("apr-1", "decline", "maria", "wrong domain")
    assert recorded == [("apr-1", "decline", "maria", "teams", "wrong domain")]


# ------------------------------------------------------------------ the loop
def test_run_notifies_and_acks_each_request(monkeypatch):
    ch = _enabled()
    acked = []
    monkeypatch.setattr(approvals, "channel_events", lambda name, block_ms: [("e1", REQ)])
    monkeypatch.setattr(approvals, "ack", lambda name, eid: acked.append((name, eid)))

    class Stop(Exception):
        pass
    monkeypatch.setattr(T.time, "sleep", lambda s: (_ for _ in ()).throw(Stop()))
    with pytest.raises(Stop):
        ch.run()
    assert acked == [("teams", "e1")] and len(ch.sent) == 1


def test_send_failure_does_not_kill_the_loop_and_leaves_the_entry_unacked(monkeypatch):
    def boom(payload):
        raise OSError("webhook 503")
    ch = T.TeamsChannel("https://hook.test/x", post=boom)
    acked = []
    monkeypatch.setattr(approvals, "channel_events", lambda name, block_ms: [("e1", REQ)])
    monkeypatch.setattr(approvals, "ack", lambda name, eid: acked.append(eid))

    class Stop(Exception):
        pass
    monkeypatch.setattr(T.time, "sleep", lambda s: (_ for _ in ()).throw(Stop()))
    out = io.StringIO()
    with redirect_stdout(out), pytest.raises(Stop):
        ch.run()
    assert acked == []                                    # unacked -> stays in the group's pending list
    assert "webhook 503" in out.getvalue() and "apr-1" in out.getvalue()


def test_teams_is_a_registered_approval_channel():
    assert T.TeamsChannel.name in approvals.CHANNELS       # own consumer group: sees every request


def test_main_entry_runs_the_channel(monkeypatch):
    monkeypatch.setattr(T.config, "TEAMS_WEBHOOK_URL", None)
    import runpy
    out = io.StringIO()
    with redirect_stdout(out):
        runpy.run_module("lab.substrate.channels.teams", run_name="__main__")
    assert "NOT configured" in out.getvalue()


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q", "-p", "no:warnings"]))
