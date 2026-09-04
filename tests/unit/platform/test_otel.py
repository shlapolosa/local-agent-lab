"""src/lab/platform/otel.py — the one tracer bootstrap. OFFLINE: OTEL_EXPORTER_OTLP_ENDPOINT points at a dummy
URL and OTLPSpanExporter is swapped for an in-memory exporter BEFORE the provider is installed, so
no span ever leaves the process. Order matters (OTel allows ONE global provider per process): the
no-op case runs first, then the install-once case."""
import os


os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)                    # start from "tracing off"

from opentelemetry import trace  # noqa: E402
from opentelemetry.exporter.otlp.proto.http import trace_exporter as _te  # noqa: E402
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult  # noqa: E402

from lab.platform import otel  # noqa: E402


class MemoryExporter(SpanExporter):
    instances = []

    def __init__(self, endpoint=None, **kw):
        self.endpoint, self.spans, self.shut = endpoint, [], False
        MemoryExporter.instances.append(self)

    def export(self, spans):
        self.spans.extend(spans); return SpanExportResult.SUCCESS

    def shutdown(self):
        self.shut = True


def test_no_endpoint_means_no_provider():
    assert otel.endpoint() is None
    t = otel.tracer("svc-off")
    with t.start_as_current_span("noop") as span:
        assert not span.is_recording()
    assert otel._STATE["provider"] is None
    otel.shutdown()                                                     # no-op when nothing installed
    assert otel._STATE["provider"] is None


def test_endpoint_installs_provider_once_and_shutdown_flushes():
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://127.0.0.1:1/"
    real = _te.OTLPSpanExporter
    _te.OTLPSpanExporter = MemoryExporter
    try:
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
        otel.shutdown()                                                 # second call: nothing to do
    finally:
        _te.OTLPSpanExporter = real
        os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
        try:
            from opentelemetry.instrumentation.urllib import URLLibInstrumentor
            URLLibInstrumentor().uninstrument()
        except Exception:                                               # noqa: BLE001 — best-effort cleanup
            pass


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
