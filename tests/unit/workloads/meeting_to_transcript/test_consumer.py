"""`meeting_to_transcript.consumer` — what THIS process contributes to the shared serve loop.

Everything generic (the poll, crash hygiene, acking, stopping on a signal) lives in
`lab.workloads.consumer` and is tested there. What belongs here is the wiring and the three small
things only this process knows: its identity, how it unpacks its own inputs, and what its log line
says it is working on.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/workloads/meeting_to_transcript/test_consumer.py
"""
import asyncio
import runpy
from types import SimpleNamespace

from lab.platform.contracts import PROCESSES
from lab.workloads import consumer as base
from lab.workloads.meeting_to_transcript import consumer


def test_it_is_registered_and_gets_its_own_consumer_group():
    """One shared request stream, one group per process — so each sees every event and discards the
    others. The group comes from the registry, never from a literal here."""
    assert consumer.PROCESS in PROCESSES
    assert PROCESSES[consumer.PROCESS].group == "wf-meeting-transcript"


def test_it_unpacks_its_own_inputs_by_name():
    """It must NOT reach for another workload's convenience fields — the generic request carries
    `inputs` and nothing process-shaped, which is what keeps two processes from coupling."""
    seen = {}

    async def fake_run_once(root, recording, owner, on_trace=None):
        seen.update(recording=recording, owner=owner, traced=on_trace)
        return {"request_id": "apr-1"}

    req = SimpleNamespace(inputs={"recording": "collab://recording/m1/r1",
                                  "owner": "maria@contoso.com"})
    saved = consumer.run_once
    consumer.run_once = fake_run_once
    try:
        out = asyncio.run(consumer._run(object(), req, on_trace="cb"))
    finally:
        consumer.run_once = saved
    assert seen == {"recording": "collab://recording/m1/r1", "owner": "maria@contoso.com",
                    "traced": "cb"}
    assert out == {"request_id": "apr-1"}


def test_the_log_line_names_the_recording_and_never_a_person():
    """Console lines end up in logs and traces. The handle is ids only, which is exactly what makes
    it safe to print — the organiser's identity is not."""
    req = SimpleNamespace(inputs={"recording": "collab://recording/m1/r1",
                                  "owner": "maria@contoso.com"})
    label = consumer._describe(req)
    assert label == "collab://recording/m1/r1" and "maria" not in label


def test_the_entry_point_wires_this_process_into_the_shared_loop():
    """`python -m ...consumer` reaches the shared loop carrying this process's identity."""
    seen = {}
    saved = base.serve
    base.serve = lambda **kw: seen.update(kw)
    try:
        runpy.run_module("lab.workloads.meeting_to_transcript.consumer", run_name="__main__",
                         alter_sys=True)
    finally:
        base.serve = saved
    assert seen["process"] == "meeting_to_transcript"
    assert seen["service"] == "process-meeting-to-transcript"
    assert callable(seen["run"]) and callable(seen["describe"])


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
