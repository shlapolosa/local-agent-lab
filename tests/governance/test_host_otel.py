"""TDD: the workflow hosts use the ONE shared OTel setup (src/lab/platform/otel.py) THROUGH the container —
no private provider copy (review B-H1: five copies of _setup_otel), no host-level tracer wrapper: the tracer
is `container.build(SERVICE).tracer()`, so the service name is a container setting, and the DevUI host gets
its own name from its own container instead of mutating the one-shot host's. Offline: tracing off (no
OTLP endpoint) -> no-op tracer."""
import os

os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)

from lab.platform import container, otel  # noqa: E402
from lab.workloads.visio_to_archimate import host  # noqa: E402


def test_host_has_no_private_otel_setup_and_no_tracer_wrapper():
    src = open(host.__file__, encoding="utf-8").read()
    assert "_setup_otel" not in src and "TracerProvider" not in src
    assert not hasattr(host, "tracer"), "the tracer comes from the container (root.tracer()), not a host wrapper"
    assert host._shutdown is otel.shutdown            # one flush path, shared with the scripts


def test_the_container_names_the_tracer_after_the_process_service():
    root = container.build(host.SERVICE)
    assert root.config.service_name() == host.SERVICE == "process-visio-to-archimate"
    t = root.tracer()
    assert t.instrumentation_info.name == host.SERVICE if hasattr(t, "instrumentation_info") \
        else type(t).__name__ == "ProxyTracer"
    assert root.tracer() is t                           # a Singleton: one tracer per container/process


def test_each_host_composes_its_own_service_name_without_mutating_another():
    src = open(os.path.join(os.path.dirname(host.__file__), "devui_entry.py"), encoding="utf-8").read()
    assert 'SERVICE = "process-visio-to-archimate-devui"' in src and "container.build(SERVICE)" in src
    assert "H.SERVICE =" not in src                     # never overrides the one-shot host's service name


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
