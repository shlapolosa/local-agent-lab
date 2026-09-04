"""The consumer must satisfy the process's DECLARED outputs.

`workflow-mcp`'s `<process>_result` returns exactly `ProcessSpec.outputs`. The long-lived consumer
used to omit the EA repository's import artifacts (only the one-shot host wrote them), so the files a
human must import were unreachable through the governed surface: the contract promised what the
producer never delivered. Offline: FakeRedis, the workflow is faked.
"""
import pytest

from fixtures.fakes import FakeRedis
from lab.platform import workflows
from lab.platform.contracts import PROCESSES, WorkflowStatus


def test_consumer_writes_every_declared_output(monkeypatch):
    from lab.workloads.visio_to_archimate import consumer
    spec = PROCESSES["visio_to_archimate"]
    r = FakeRedis()
    rid = workflows.request("visio_to_archimate", {"diagram": "art://a/b.vsdx"}, "tester", client=r)

    out = {"request_id": "apr-1", "review_app": "http://review", "xml_ref": "art://x/m.xml",
           "import_artifacts": [{"ref": "art://x/m.xlsx", "label": "Download objects"}],
           "svg_refs": ["art://x/v.svg"], "trace_id": "t" * 32,
           "summary": {"elements": 3, "relations": 2, "views": 1}}
    monkeypatch.setattr(consumer, "run_once", lambda *a, **k: _coro(out))

    class Root:                     # the composition root the consumer is handed
        def redis(self): return r
    consumer.handle(Root(), "1-1", _req(rid).to_fields())

    got = workflows.status(rid, client=r)
    assert got["status"] == WorkflowStatus.DONE.value
    missing = [o for o in spec.outputs if o not in got]
    assert not missing, f"declared outputs the consumer never wrote: {missing}"


def _coro(value):
    async def _c(*a, **k):
        return value
    return _c()


def _req(rid):
    from lab.platform.contracts import WorkflowRequest
    return WorkflowRequest(request_id=rid, process="visio_to_archimate",
                           inputs={"diagram": "art://a/b.vsdx"}, requester="tester",
                           created_at="2026-09-04T00:00:00+00:00", created_ts="1.0")


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
