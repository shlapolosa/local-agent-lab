"""lab.substrate.channels.steward — the VOCABULARY channel, OFFLINE.

The steward's queue, separated from the owners' by APPROVAL KIND (see
tests/unit/platform/test_contracts_approval_audience.py for the partition that decides which is
which). It is the Teams adapter aimed at a second Workflows webhook: the same Adaptive Card
envelope, a different consumer group, and a feed carrying only `STEWARD_KINDS`. So it is a
SUBCLASS, not a second adapter — three class attributes (`name`, `setting`, `audience`) are the
whole difference, and anything learned about the card or the loop is learned once.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/channels/test_steward.py
"""
import io
import json
from contextlib import redirect_stdout

import pytest

from lab.platform import config
from lab.platform.contracts import ApprovalAudience, ApprovalKind
from lab.substrate import approvals
from lab.substrate.channels import steward as S
from lab.substrate.channels import teams as T

TERM = {"request_id": "apr-9", "kind": ApprovalKind.CONCEPT_ADMISSION.value,
        "subject": "'Agent' means two things", "requester": "wf-fabric", "trace_id": "",
        "payload": json.dumps({"question": {"prompt": "Admit this term?", "items": [
            {"label": "Agent", "samples": ["admit", "merge", "decline"]}]}})}


def _enabled():
    ch = S.StewardChannel("https://hook.test/steward", post=lambda p: ch.sent.append(p),
                          review_url="http://review.test", jaeger_url="http://jaeger.test")
    ch.sent = []
    return ch


def _stopper(monkeypatch):
    import signal as signal_mod
    handlers = {}
    monkeypatch.setattr(signal_mod, "signal", lambda sig, fn: handlers.setdefault(sig, fn))
    return lambda: handlers[signal_mod.SIGTERM]()


def test_it_is_the_teams_adapter_with_its_own_queue_and_its_own_webhook():
    """Reuse, deliberately: the card, the loop, the unacked-on-failure rule and the inbound
    `decide` binding are the Teams channel's and must not be reimplemented. What differs is the
    three things that make it a SEPARATE queue."""
    assert issubclass(S.StewardChannel, T.TeamsChannel)
    assert S.StewardChannel.name == "steward" != T.TeamsChannel.name
    assert S.StewardChannel.audience is ApprovalAudience.STEWARD
    assert T.TeamsChannel.audience is ApprovalAudience.OWNER
    assert S.StewardChannel.setting == "TEAMS_STEWARD_WEBHOOK_URL"


def test_steward_is_a_registered_approval_channel():
    assert S.StewardChannel.name in approvals.CHANNELS       # its own consumer group


def test_settings_default_to_its_own_config_value_not_the_owner_channels():
    ch = S.StewardChannel()
    assert ch.webhook == config.TEAMS_STEWARD_WEBHOOK_URL
    # The whole point of a second channel is a second destination: inheriting the owners' webhook
    # would post vocabulary cards right back into the queue this exists to drain.
    assert ch.webhook != T.config.TEAMS_WEBHOOK_URL or not T.config.TEAMS_WEBHOOK_URL


def test_disabled_without_its_webhook_and_says_which_setting_by_name():
    ch = S.StewardChannel("")
    assert not ch.enabled
    out = io.StringIO()
    with redirect_stdout(out):
        ch.notify(TERM)
        assert ch.run() is None                 # exits immediately, exactly as the others do
    text = out.getvalue()
    assert "[steward not configured]" in text and "apr-9" in text and "NOT configured" in text
    assert "TEAMS_STEWARD_WEBHOOK_URL" in text


def test_the_card_renders_the_vocabulary_question_without_dispatching_on_its_kind():
    ch = _enabled()
    card = ch.card(TERM)["attachments"][0]["content"]
    body = json.dumps(card["body"])
    assert "Admit this term?" in body and "Agent" in body
    assert card["actions"][0]["url"].endswith("?approval=apr-9")


def test_the_loop_reads_only_the_stewards_audience_and_acks_under_its_own_name(monkeypatch):
    """The filter is asked for by the channel and applied in `channel_events` — one reader, one
    rule. A channel that read the whole queue and filtered after would ack nothing it skipped."""
    seen, acked = [], []
    stop = _stopper(monkeypatch)
    monkeypatch.setattr(approvals, "channel_events",
                        lambda name, block_ms=0, **kw: (stop(), seen.append((name, kw)),
                                                        [("e1", TERM)])[2])
    monkeypatch.setattr(approvals, "ack", lambda name, eid, **kw: acked.append((name, eid)))
    ch = _enabled()
    ch.run()
    assert seen and seen[0][0] == "steward"
    assert seen[0][1]["audience"] is ApprovalAudience.STEWARD
    assert acked == [("steward", "e1")] and len(ch.sent) == 1


def test_a_decision_is_recorded_against_this_channel(monkeypatch):
    """The audit log must say WHERE a steward answered — `mcp:`/channel provenance is the point."""
    recorded = {}
    monkeypatch.setattr(approvals, "human_decision",
                        lambda rid, d, actor, channel, comment="": recorded.update(
                            rid=rid, d=d, actor=actor, channel=channel))
    _enabled().decide("apr-9", "approve", "steward@doh")
    assert recorded == {"rid": "apr-9", "d": "approve", "actor": "steward@doh", "channel": "steward"}


def test_main_entry_runs_the_channel(monkeypatch):
    monkeypatch.setattr(config, "TEAMS_STEWARD_WEBHOOK_URL", None)
    import runpy
    out = io.StringIO()
    with redirect_stdout(out):
        runpy.run_module("lab.substrate.channels.steward", run_name="__main__")
    assert "NOT configured" in out.getvalue()


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q", "-p", "no:warnings"]))


# ------------------------------------------------ T2.5: answering ON the card, when something is waiting
def _question():
    return {"prompt": "Triage these terms.", "fields": ["value"], "items": [
        {"label": "urn:fabric:candidate:0", "samples": ["'Clinical Reviewer' — asked for by 2 documents"]},
        {"label": "urn:fabric:candidate:1", "samples": ["'Agentic retrieval' — asked for by 2 documents"]}]}


def _card(ch, **over):
    f = {"request_id": "apr-1", "kind": "concept-admission", "subject": "2 terms", "question": _question()}
    return ch.card({**f, **over})["attachments"][0]["content"]


def test_a_card_carries_NO_inputs_unless_something_is_waiting_for_them(monkeypatch):
    """Teams renders `Action.Submit` on any card and has nowhere to post it unless a flow is waiting. A
    button that silently does nothing is worse than no button, so the default is off and the card says
    where to answer instead."""
    ch = S.StewardChannel("https://hook.test/steward")
    ch.answers_on_card = False
    content = _card(ch)
    assert not [b for b in content["body"] if str(b.get("type", "")).startswith("Input.")]
    assert all(a["type"] == "Action.OpenUrl" for a in content["actions"])
    assert "review app" in json.dumps(content)


def test_when_a_flow_IS_waiting_every_term_gets_a_control_keyed_as_the_gate_keys_it():
    """One control per label, keyed EXACTLY as `check_answer` keys the answer — so what the flow posts is
    what the gate already accepts, with nothing to map and nothing to drift."""
    ch = S.StewardChannel("https://hook.test/steward")
    ch.answers_on_card = True
    content = _card(ch)
    choices = [b for b in content["body"] if b.get("type") == "Input.ChoiceSet"]
    assert [c["id"] for c in choices] == ["urn:fabric:candidate:0", "urn:fabric:candidate:1"]
    # three answers, because "it already means something we have" is the commonest one
    assert [o["value"] for o in choices[0]["choices"]] == ["admit", "existing", "decline"]
    assert all(c["value"] == "decline" for c in choices), "the safe answer is the default"
    texts = [b for b in content["body"] if b.get("type") == "Input.Text"]
    assert [t["id"] for t in texts] == ["urn:fabric:candidate:0::id", "urn:fabric:candidate:1::id"]
    submit = [a for a in content["actions"] if a["type"] == "Action.Submit"]
    assert len(submit) == 1 and submit[0]["data"]["labels"] == [c["id"] for c in choices]
    # the approval id rides the answer, so the flow can address the gate without correlating anything
    assert submit[0]["data"]["request_id"] == "apr-1"
    assert content["actions"][-1]["type"] == "Action.OpenUrl", "the review app stays reachable"


def test_a_question_with_no_items_gets_no_submit_button():
    ch = S.StewardChannel("https://hook.test/steward")
    ch.answers_on_card = True
    content = _card(ch, question={"prompt": "nothing to answer", "items": []})
    assert not [a for a in content["actions"] if a["type"] == "Action.Submit"]
