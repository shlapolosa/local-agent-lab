"""src/lab/platform/otel.py — the one tracer bootstrap. OFFLINE: OTEL_EXPORTER_OTLP_ENDPOINT points at a dummy
URL and OTLPSpanExporter is swapped for an in-memory exporter BEFORE the provider is installed, so
no span ever leaves the process. The process globals OTel and this module keep (one TracerProvider
per process; install-once state) are snapshotted and restored per test by tests/conftest.py's
`_isolated_otel`, so the two cases below are independent and run in any order."""
import sys

import pytest
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http import trace_exporter as _te
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from lab.platform import otel


class MemoryExporter(SpanExporter):
    instances = []

    def __init__(self, endpoint=None, **kw):
        self.endpoint, self.spans, self.shut = endpoint, [], False
        MemoryExporter.instances.append(self)

    def export(self, spans):
        self.spans.extend(spans); return SpanExportResult.SUCCESS

    def shutdown(self):
        self.shut = True


@pytest.fixture(autouse=True)
def _tracing_off(monkeypatch):
    """Start every test from "tracing off" (the exporter list too — it is class state)."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    MemoryExporter.instances = []
    yield
    try:
        from opentelemetry.instrumentation.urllib import URLLibInstrumentor
        URLLibInstrumentor().uninstrument()
    except Exception:                                               # noqa: BLE001 — best-effort cleanup
        pass


def test_no_endpoint_means_no_provider():
    assert otel.endpoint() is None
    t = otel.tracer("svc-off")
    with t.start_as_current_span("noop") as span:
        assert not span.is_recording()
    assert otel._STATE["provider"] is None
    otel.shutdown()                                                     # no-op when nothing installed
    assert otel._STATE["provider"] is None


def test_endpoint_installs_provider_once_and_shutdown_flushes(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:1/")
    monkeypatch.setattr(_te, "OTLPSpanExporter", MemoryExporter)
    assert otel.endpoint() == "http://127.0.0.1:1/"
    t = otel.tracer("svc-a", instrument_urllib=True)
    provider = otel._STATE["provider"]
    assert provider is not None and trace.get_tracer_provider() is provider
    assert provider.resource.attributes["service.name"] == "svc-a"
    assert otel._STATE["urllib"] is True
    assert len(MemoryExporter.instances) == 1 and MemoryExporter.instances[0].endpoint == "http://127.0.0.1:1/v1/traces"
    # idempotent: a second service name in the same process neither reinstalls nor re-instruments
    t2 = otel.tracer("svc-b", instrument_urllib=True)
    assert otel._STATE["provider"] is provider and len(MemoryExporter.instances) == 1
    with t.start_as_current_span("work") as span:
        assert span.is_recording()
    with t2.start_as_current_span("more"):
        pass
    otel.shutdown()
    exp = MemoryExporter.instances[0]
    assert exp.shut and {s.name for s in exp.spans} == {"work", "more"}, "shutdown flushed the batch"
    assert otel._STATE["provider"] is None
    otel.shutdown()                                                     # second call: nothing to do


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
