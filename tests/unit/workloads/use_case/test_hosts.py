"""The four use-case hosts and their consumers.

A host is a composition root: it reads configuration, builds the credential and hands the graph
everything it needs as arguments. What is worth testing is therefore not the derivation — the graph
is faked here — but the things a host alone decides: its OTel service name, what reaches a span,
what lands on the Runs board, and that a consumer unpacks THIS process's inputs by the names its
contract declares.
"""
import asyncio
import contextlib
import importlib
import os
from types import SimpleNamespace

import pytest

from fixtures.fakes import FakeRedis
from fixtures.host import make_root
from lab.platform.contracts import PROCESSES

HOSTS = ("use_case_screening", "use_case_design", "use_case_investment", "use_case_provisioning")


@pytest.fixture(autouse=True)
def _static_credentials():
    """Every host resolves a credential through `identity.agent_headers`. Static keys with no
    client id keep it off MSAL — a unit test must never reach a tenant."""
    for prefix in ("USECASE_AGENT", "USECASE_DELIVERY"):
        os.environ.pop(f"{prefix}_CLIENT_ID", None)
        os.environ.pop(f"{prefix}_CLIENT_SECRET", None)
        os.environ[f"{prefix}_KEY"] = f"sk-{prefix.lower()}"


def host_of(name):
    return importlib.import_module(f"lab.workloads.{name}.host")


def consumer_of(name):
    return importlib.import_module(f"lab.workloads.{name}.consumer")


# ---------------------------------------------------------------- what a host owns

@pytest.mark.parametrize("name", HOSTS)
def test_every_host_declares_its_own_otel_service_name(name):
    """One distinct service name per business process, so each stage is traced and audited
    independently — and so NFR-02's budget can be measured on the screening one alone."""
    names = {host_of(n).SERVICE for n in HOSTS}
    assert len(names) == len(HOSTS)
    assert host_of(name).SERVICE.startswith("process-usecase-")


@pytest.mark.parametrize("name", HOSTS)
def test_the_process_name_comes_from_the_registry_and_is_not_retyped(name):
    host = host_of(name)
    assert host.PROCESS in PROCESSES
    assert PROCESSES[host.PROCESS].name == host.PROCESS


def test_the_two_grant_profiles_use_two_different_identities():
    """Screening and design share one identity because their grants are the same; investment and
    provisioning hold the other, because theirs carry the write path. One workload never holds
    another's credential."""
    assessment = {host_of(n).AGENT_PREFIX for n in ("use_case_screening", "use_case_design")}
    delivery = {host_of(n).AGENT_PREFIX for n in ("use_case_investment", "use_case_provisioning")}
    assert len(assessment) == len(delivery) == 1
    assert assessment != delivery


@pytest.mark.parametrize("name", HOSTS)
def test_a_credential_is_resolved_without_reaching_a_tenant(name):
    assert host_of(name)._cred().startswith("sk-usecase")


# ---------------------------------------------------------------- the run, faked

def _fake_run(name, out, recorder):
    """Patch the module's `run_workflow` so the host runs without a gateway."""
    host = host_of(name)

    async def run_workflow(cfg, inputs):
        recorder.append((cfg, inputs))
        return out
    return host, run_workflow


@pytest.mark.parametrize("name,args,out", [
    ("use_case_screening", ("art://in/u.md", "ba@x.ae"),
     {"approval_id": "apr-1", "screening_ref": "art://s/scr.json"}),
    ("use_case_design", ("art://s/sub.json", "art://s/scr.json"),
     {"approval_id": "apr-2", "verdict": "proceed", "business_case_ref": "art://d/bc.json"}),
    ("use_case_investment", ("art://d/design.json",),
     {"approval_id": "apr-3", "investment_ref": "art://i/inv.json"}),
    ("use_case_provisioning", ("art://i/inv.json",),
     {"provisioned": True, "work_items_ref": "art://p/wi.json"}),
])
def test_a_run_produces_a_trace_and_the_row_a_reviewer_follows(name, args, out, monkeypatch):
    host, run_workflow = _fake_run(name, out, calls := [])
    monkeypatch.setattr(host, "run_workflow", run_workflow)
    root = make_root(host.SERVICE, redis=FakeRedis())
    result = asyncio.run(host.run_once(root, *args))

    assert result["trace_id"], "every run publishes a trace id"
    row = host.run_fields(result)
    assert row, "a finished run puts something on the board"
    assert all(v is None or isinstance(v, (str, bool)) for v in row.values())


@pytest.mark.parametrize("name,args", [
    ("use_case_screening", ("art://in/u.md", "ba@x.ae")),
    ("use_case_design", ("art://s/sub.json", "art://s/scr.json")),
])
def test_the_trace_id_is_published_as_soon_as_it_exists(name, args, monkeypatch):
    """A run watched live needs its trace before it finishes, not after."""
    host, run_workflow = _fake_run(name, {}, [])
    monkeypatch.setattr(host, "run_workflow", run_workflow)
    seen: list[str] = []
    asyncio.run(host.run_once(make_root(host.SERVICE, redis=FakeRedis()), *args,
                              on_trace=seen.append))
    assert seen and len(seen[0]) == 32


class RecordingTracer:
    """Records what a host actually puts on its span, and still yields a usable span context —
    `governed_run` reads the trace id off it, so a tracer that only recorded would never run."""

    def __init__(self):
        self.attrs: dict = {}

    @contextlib.contextmanager
    def start_as_current_span(self, name, context=None):
        outer = self

        class Span:
            def set_attribute(self, k, v): outer.attrs[k] = v
            def set_attributes(self, d): outer.attrs.update(d)
            def get_span_context(self):
                return SimpleNamespace(trace_id=0x0123456789abcdef0123456789abcdef, span_id=1)
        yield Span()


def test_the_span_carries_shapes_not_the_person_who_submitted(monkeypatch):
    """A span reaches a collector this lab does not authenticate, so the submitter is recorded as
    a boolean — THAT one was supplied, never who."""
    host, run_workflow = _fake_run("use_case_screening", {}, [])
    monkeypatch.setattr(host, "run_workflow", run_workflow)
    tracer = RecordingTracer()
    root = make_root(host.SERVICE, redis=FakeRedis())
    root.tracer.override(tracer)

    asyncio.run(host.run_once(root, "art://in/u.md", "someone@example.ae",
                              attachments=["a", "b"], intake={"effort": {}}))

    assert tracer.attrs, "the host records nothing, so this would pass vacuously"
    assert tracer.attrs["usecase.submitter.given"] is True
    assert tracer.attrs["usecase.attachments"] == 2
    for key, value in tracer.attrs.items():
        assert isinstance(value, (int, float, bool, str)), (key, value)
        assert "someone@example.ae" not in str(value), f"{key} leaked the submitter"


def test_the_label_on_the_board_names_the_document_not_the_person():
    """A board row is rendered beside other people's runs."""
    host = host_of("use_case_screening")
    assert host._label("art://in/u.md", "") == "screening art://in/u.md"
    assert "@" not in host._label("art://in/u.md", "")


# ---------------------------------------------------------------- the consumers

@pytest.mark.parametrize("name", HOSTS)
def test_a_consumer_serves_its_own_process_and_nothing_else(name, monkeypatch):
    consumer = consumer_of(name)
    seen: dict = {}
    monkeypatch.setattr(consumer.base, "serve", lambda **kw: seen.update(kw))
    consumer.main()
    assert seen["process"] == host_of(name).PROCESS
    assert seen["service"] == host_of(name).SERVICE


@pytest.mark.parametrize("name,inputs,expected", [
    ("use_case_screening", {"submission": "art://a/u.md"}, "art://a/u.md"),
    ("use_case_screening", {"submission_handle": "collab://d/x"}, "collab://d/x"),
    ("use_case_design", {"submission_ref": "art://a/s.json"}, "art://a/s.json"),
    ("use_case_investment", {"design_ref": "art://d/d.json"}, "art://d/d.json"),
    ("use_case_provisioning", {"investment_ref": "art://i/i.json"}, "art://i/i.json"),
])
def test_the_console_line_names_a_reference_never_a_person(name, inputs, expected):
    """Logs are read by other people, so a describe line carries an id and not a submitter."""
    described = consumer_of(name)._describe(SimpleNamespace(inputs=inputs))
    assert described == expected


@pytest.mark.parametrize("name", HOSTS)
def test_a_consumer_describes_a_request_with_nothing_useful_rather_than_raising(name):
    assert consumer_of(name)._describe(SimpleNamespace(inputs={}))


@pytest.mark.parametrize("name,inputs", [
    ("use_case_screening", {"submission": "art://a/u.md", "submitter": "ba@x.ae"}),
    ("use_case_design", {"submission_ref": "art://a/s.json", "screening_ref": "art://a/c.json",
                         "criticality": {"criticality_class": {"value": "routine"}}}),
    ("use_case_investment", {"design_ref": "art://d/d.json",
                             "conformance": {"decision": {"value": "approve"}}}),
    ("use_case_provisioning", {"investment_ref": "art://i/i.json",
                               "authorisation": {"decision": {"value": "approve"}}}),
])
def test_a_consumer_unpacks_the_inputs_its_contract_declares(name, inputs, monkeypatch):
    """The names here are the spec's. A consumer reading a field the contract does not declare
    would fail only on a real request, hours after the mistake. And the SHAPES are the contract's
    too: a fixture the process would refuse proves nothing about the consumer (the cloud found the
    design row in exactly that state on 10 Sep 2026), so every row passes its own validator first."""
    from lab.platform.contracts import PROCESSES
    inputs = PROCESSES[name].validate(inputs)
    host = host_of(name)
    seen: list = []

    async def run_once(root, *a, **kw):
        seen.append((a, kw))
        return {"trace_id": "t"}

    monkeypatch.setattr(consumer_of(name), "run_once", run_once)
    spec = PROCESSES[host.PROCESS]
    assert set(inputs) <= {f.name for f in spec.inputs}, "the test itself uses declared names only"
    asyncio.run(consumer_of(name)._run(object(), SimpleNamespace(inputs=inputs), lambda t: None))
    assert seen, "the consumer called the host"


# ---------------------------------------------------------------- the CLI entry points

@pytest.mark.parametrize("name", HOSTS)
def test_running_a_host_with_no_arguments_explains_itself(name, capsys):
    assert host_of(name).main([]) == 2
    assert capsys.readouterr().out.strip(), "it prints its own usage"
