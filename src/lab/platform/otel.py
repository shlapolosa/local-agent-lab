"""OpenTelemetry bootstrap shared by every lab process — one implementation of "tracer provider +
OTLP/HTTP exporter, or a no-op when tracing is not configured".

    from lab.platform.otel import tracer
    tracer = tracer("adoit-mcp", instrument_urllib=True)   # ADOIT REST calls become child spans
    with tracer.start_as_current_span("archimate_render"): ...

Semantics (unchanged from the per-service copies this replaces):
  * OTEL_EXPORTER_OTLP_ENDPOINT unset  -> no provider is installed; the returned tracer is the SDK's
    no-op proxy, so spans cost nothing and nothing is exported.
  * set                                -> a TracerProvider with service.name=<service> and a
    BatchSpanProcessor(OTLPSpanExporter(<endpoint>/v1/traces)) is installed ONCE per process.
Idempotent: OTel allows only one global provider, so the FIRST call in a process fixes
`service.name`; later calls (even with another service name) just return a tracer — that is what
`export_capabilities.py` importing the same service name relies on, and what stops a second call
from tripping OTel's "overriding the current TracerProvider is not allowed" warning.
"""
from __future__ import annotations

import os
import threading

_STATE = {"provider": None, "urllib": False}
_LOCK = threading.Lock()


def endpoint() -> str | None:
    """The OTLP/HTTP collector base URL, or None when tracing is off."""
    return os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or None


def tracer(service: str, *, instrument_urllib: bool = False):
    """Install the provider for `service` if tracing is configured (first call wins) and return a
    tracer named `service`. `instrument_urllib=True` additionally makes urllib calls child spans."""
    from opentelemetry import trace

    ep = endpoint()
    if ep:
        with _LOCK:
            if _STATE["provider"] is None:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                from opentelemetry.sdk.resources import Resource
                from opentelemetry.sdk.trace import TracerProvider
                from opentelemetry.sdk.trace.export import BatchSpanProcessor
                provider = TracerProvider(resource=Resource.create({"service.name": service}))
                provider.add_span_processor(BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=ep.rstrip("/") + "/v1/traces")))
                trace.set_tracer_provider(provider)
                _STATE["provider"] = provider
            if instrument_urllib and not _STATE["urllib"]:
                from opentelemetry.instrumentation.urllib import URLLibInstrumentor
                URLLibInstrumentor().instrument()
                _STATE["urllib"] = True
    return trace.get_tracer(service)


def shutdown() -> None:
    """Flush and stop the provider this module installed (scripts call it before exiting so the
    batch processor exports its last spans). A no-op when tracing is off."""
    with _LOCK:
        provider, _STATE["provider"] = _STATE["provider"], None
    if provider is not None:
        provider.shutdown()


__all__ = ["tracer", "shutdown", "endpoint"]
