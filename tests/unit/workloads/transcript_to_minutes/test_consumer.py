"""`transcript_to_minutes.consumer` — what THIS process contributes to the shared serve loop.

Everything generic (the poll, crash hygiene, acking, stopping on a signal) lives in
`lab.workloads.consumer` and is tested there. What belongs here is the wiring and the small things
only this process knows: its identity, how it unpacks its own inputs, and what its log line says.

The unpacking is worth a test of its own rather than trusting the signature, because this consumer
is the LAST carrier of everything a human's approval released. A field dropped here is dropped
silently — the run still writes its minutes and simply never does the thing the field was for.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/workloads/transcript_to_minutes/test_consumer.py
"""
import asyncio
import runpy
from types import SimpleNamespace

from lab.platform.contracts import PROCESSES, TRANSCRIPT_TO_MINUTES
from lab.workloads import consumer as base
from lab.workloads.transcript_to_minutes import consumer

INPUTS = {"transcript": "art://t/x.segments.json",
          "speaker_map": {"SPEAKER_00": {"identity": "maria@contoso.com"}},
          "owner": "maria@contoso.com",
          "recording": "collab://item/b!d/01FILE",
          "chat_id": "19:meeting_ZmFrZQ@thread.v2",
          # the LANE: which provider's pipeline this minutes run belongs to
          "provider": "elevenlabs"}


def test_it_is_registered_and_gets_its_own_consumer_group():
    assert consumer.PROCESS in PROCESSES
    assert PROCESSES[consumer.PROCESS].group == "wf-meeting-minutes"


def test_every_input_the_contract_declares_reaches_the_run():
    """The invariant, not a list: whatever `TRANSCRIPT_TO_MINUTES` declares, this consumer forwards.
    `chat_id` reached the contract and stopped here once — the run wrote its minutes, delivered its
    files and then had nowhere to announce them, which looks exactly like working."""
    seen = {}

    async def fake_run_once(root, transcript, speaker_map, owner="", recording="", chat_id="",
                            provider="", on_trace=None):
        seen.update(transcript=transcript, speaker_map=speaker_map, owner=owner,
                    recording=recording, chat_id=chat_id, provider=provider)
        return {"minutes_ref": "art://m/x.json"}

    saved, consumer.run_once = consumer.run_once, fake_run_once
    try:
        out = asyncio.run(consumer._run(object(), SimpleNamespace(inputs=INPUTS), on_trace=None))
    finally:
        consumer.run_once = saved
    assert seen == INPUTS
    assert set(seen) == {f.name for f in TRANSCRIPT_TO_MINUTES.inputs}, \
        "a new input on the contract that never reaches the run is a silently dead field"
    assert out == {"minutes_ref": "art://m/x.json"}


def test_the_log_line_names_the_transcript_and_never_a_person():
    """Console lines end up in logs and traces. A reference is an id; the organiser is not."""
    label = consumer._describe(SimpleNamespace(inputs=INPUTS))
    assert label == INPUTS["transcript"] and "maria" not in label


def test_the_entry_point_wires_this_process_into_the_shared_loop():
    seen = {}
    saved, base.serve = base.serve, lambda **kw: seen.update(kw)
    try:
        runpy.run_module("lab.workloads.transcript_to_minutes.consumer", run_name="__main__",
                         alter_sys=True)
    finally:
        base.serve = saved
    assert seen["process"] == "transcript_to_minutes"
    assert callable(seen["run"]) and callable(seen["describe"])


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
