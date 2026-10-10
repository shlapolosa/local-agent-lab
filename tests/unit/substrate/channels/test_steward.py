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
