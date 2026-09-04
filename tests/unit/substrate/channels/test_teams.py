"""lab.substrate.channels.teams — the Microsoft Teams approval channel, OFFLINE: the webhook URL and the
HTTP POST are constructor-injected (a recorded fake), the loop's channel_events/ack are patched and the
inbound decisions run against a FakeRedis; no env, no network, no live Redis.
Run: pytest tests/unit/substrate/channels/test_teams.py (or as a script)."""
import io
import json
import urllib.request
from contextlib import redirect_stdout

import pytest

from fixtures.fakes import FakeRedis, patched_client
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
# `decide` is a CHANNEL BINDING over approvals.human_decision — the same implementation the
# `approvals_decide` MCP tool (a Copilot Studio connector) calls. These tests assert the binding and
# the guarantees it inherits; tests/unit/substrate/mcp/workflow/test_approval_tools.py asserts that
# both callers record IDENTICAL audit entries.
def _open_request(r, subject="claims"):
    return approvals.request("adoit-import", subject, {"summary": {}}, "architect", client=r)


def test_decide_records_through_approvals_with_the_callers_actor():
    with patched_client(FakeRedis()) as r:
        rid = _open_request(r)
        out = _enabled().decide(rid, "approve", "  maria@contoso.com  ", " looks right ")
        assert out == {"request_id": rid, "decision": "approve", "actor": "maria@contoso.com",
                       "channel": "teams", "comment": "looks right", "decided_at": out["decided_at"]}
        st = approvals.status(rid, client=r)
        assert st["status"] == "approve" and st["decided_by"] == "maria@contoso.com"
        assert st["decided_via"] == "teams"                       # the channel, for the audit log


def test_decide_requires_a_real_actor():
    with patched_client(FakeRedis()) as r:
        rid = _open_request(r)
        for bad in (None, "", "   "):
            with pytest.raises(ValueError, match="actor is required"):
                _enabled().decide(rid, "approve", bad)
        assert approvals.status(rid, client=r)["status"] == "pending"   # never an anonymous default
        assert approvals.DEC not in r.x                                 # and nothing in the audit log


def test_decide_propagates_unknown_id_invalid_decision_and_a_settled_request():
    with patched_client(FakeRedis()) as r:
        rid = _open_request(r)
        ch = _enabled()
        with pytest.raises(KeyError, match="unknown request"):
            ch.decide("apr-nope", "approve", "maria")
        with pytest.raises(ValueError, match="decision must be one of"):
            ch.decide(rid, "frobnicate", "maria")
        ch.decide(rid, "update", "maria", "rename X")             # changes requested -> still open
        assert approvals.status(rid, client=r)["status"] == "update"
        ch.decide(rid, "decline", "omar", "wrong domain")
        with pytest.raises(ValueError, match="already decline"):  # a final decision is final
            ch.decide(rid, "approve", "maria")


def test_decide_works_even_when_outbound_is_not_configured():
    """The inbound path needs no webhook: a connector can record a decision on a disabled channel."""
    with patched_client(FakeRedis()) as r:
        rid = _open_request(r)
        T.TeamsChannel("").decide(rid, "decline", "maria", "wrong domain")
        assert approvals.status(rid, client=r)["decided_via"] == "teams"


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
