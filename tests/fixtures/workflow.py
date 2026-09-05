"""Shared doubles/harness hoisted from the former `test_workflow_run` module (restructure): imported by every test that
needs them (`from fixtures.workflow import …`) instead of test-to-test imports.
"""
import asyncio
import base64
import contextlib
import json
import os
import tempfile
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from agent_framework import Content, Message
from opentelemetry import trace

from lab.workloads import gateway
from lab.workloads.visio_to_archimate import workflow as W
from lab.workloads import ids

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCHEMA = json.load(open(os.path.join(ROOT, "src", "lab", "workloads", "visio_to_archimate", "schemas", "ba_output.schema.json")))
TRACEPARENT = {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"}

# ------------------------------------------------------------------ fixtures (contract-valid documents)
BA_OK = {
    "systemName": "Clinic Portal",
    "summary": "Clinicians use a web portal to read patient records.",
    # provenance is required by the deterministic gate; "Clinician" uses the STRING shorthand on
    # purpose, so the gate's normalisation to the object form is exercised on every run.
    "actors": [{"name": "Clinician", "role": "Reads records", "layer": "Business", "aspect": "active",
                "candidateType": "BusinessActor", "provenance": "structure"}],
    "components": [{"name": "Portal", "role": "Web front end", "layer": "Application", "aspect": "active",
                    "candidateType": "ApplicationComponent",
                    "provenance": {"source": "diagram", "representation": "structure"}}],
    "data": [{"name": "Patient Record", "role": "The clinical record", "layer": "Application",
              "aspect": "passive", "candidateType": "DataObject",
              "provenance": {"source": "document", "representation": "document"}}],
    "behaviors": [],
    "relationships": [{"from": "Portal", "to": "Clinician", "type": "Serving", "intent": "portal serves clinician"},
                      {"from": "Portal", "to": "Patient Record", "type": "Access", "intent": "portal reads record"}],
    "openQuestions": [],
}

# What the deterministic gate hands on: the same document with every provenance in the object form
# (the "Clinician" shorthand expanded to its only possible source). This — not BA_OK — is what the
# Architect prompt and the persisted `ba_output` artifact contain.
BA_NORMALISED = json.loads(json.dumps(BA_OK))
BA_NORMALISED["actors"][0]["provenance"] = {"source": "diagram", "representation": "structure"}

SPEC_OK = {
    "name": "Clinic Portal", "id": "clinic-portal",
    "elements": [{"id": "clinician", "type": "BusinessActor", "name": "Clinician"},
                 {"id": "portal", "type": "ApplicationComponent", "name": "Portal"},
                 {"id": "patient-record", "type": "DataObject", "name": "Patient Record"}],
    "relations": [{"type": "Serving", "src": "portal", "tgt": "clinician"},
                  # ArchiMate-illegal on purpose (Component -> DataObject may only Access/Associate):
                  # the deterministic relrepair step must legalise it and report the change
                  {"type": "Aggregation", "src": "portal", "tgt": "patient-record"}],
}


# ------------------------------------------------------------------ fakes
class FakeResult:
    """A fastmcp CallToolResult stand-in: `.data` (parsed) and `.content` (blocks)."""
    def __init__(self, data=None, content=None):
        self.data, self.content = data, list(content or [])


def image_block(data: bytes = b"\x89PNG-bytes", mime: str = "image/png"):
    return SimpleNamespace(type="image", data=base64.b64encode(data).decode(), mimeType=mime)


def text_block(text: str):
    return SimpleNamespace(type="text", text=text)


class Router:
    """One in-memory gateway MCP. `tools` maps a tool-name SUFFIX to a canned result — a value, a
    FakeResult, a callable(args), or an Exception to raise. Tool names are prefixed like the gateway
    does (`<server>-<tool>`); every call is recorded as (suffix, args)."""
    def __init__(self, tools: dict, hidden=(), full=False):
        self.tools, self.calls, self.hidden, self.full = dict(tools), [], set(hidden), full

    def names(self):
        """What the gateway LISTS. With `full=True` (the run harness) that is every CONTRACT tool, not
        just the ones a test stubs.

        A real gateway exposes a server's whole tool set to a granted team; listing only the stubbed
        subset made the fake unrealistic, which is why no test caught a workload calling a tool the
        gateway no longer had. `call()` still fails loudly on an unstubbed tool, so a test cannot
        accidentally depend on one."""
        if not self.full:                        # a focused unit test: exactly the tools it named
            return [f"srv-{s}" for s in self.tools]
        from lab.platform.contracts import SERVERS
        every = {t for c in SERVERS.values() for t in c.names()} - self.hidden
        return [f"srv-{s}" for s in dict.fromkeys([*self.tools, *sorted(every)])]

    def call(self, name, args):
        suffix = name.split("-", 1)[1]
        self.calls.append((suffix, args))
        h = self.tools[suffix]
        if isinstance(h, Exception):
            raise h
        out = h(args) if callable(h) else h
        return out if isinstance(out, FakeResult) else FakeResult(data=out)

    def called(self, suffix):
        return [a for s, a in self.calls if s == suffix]

    def client_class(self):
        router = self

        class FakeClient:                    # replaces workflow.Client (constructed with a transport)
            def __init__(self, transport):
                self.transport = transport

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def list_tools(self):
                return [SimpleNamespace(name=n) for n in router.names()]

            async def call_tool(self, name, args):
                return router.call(name, args)
        return FakeClient


def default_tools(**over) -> dict:
    """The happy-path gateway: every tool the six executors call. Override per test (None removes)."""
    t = {
        "semantic_store_spec": lambda a: {"spec_ref": f"art://store/{a['name']}"},
        "ea_search": [],
        "semantic_validate_model": {"illegal": [], "warnings": ["w1"]},
        # svg_refs is a DICT {view label: ref} — exactly what adoit-mcp's render report returns and what
        # the review app iterates with .items(); a list here would hide an AttributeError in the UI
        "archimate_render": {"xml_ref": "art://x/visio-import.archimate.xml",
                             "svg_refs": {"landscape": "art://x/a.svg", "detail": "art://x/b.svg"},
                             "views": {"v1": {}, "v2": {}}},
        # the EA-repository port: it echoes back the views it was handed (the staged MODEL) and adds
        # the OPAQUE artifacts THIS repository needs a human to import — see adoit-mcp
        "ea_stage_import": lambda a: {
            "request_id": "req-1", "status": "pending", "review_app": "http://review/req-1",
            "artifacts": {"xml_ref": a.get("xml_ref"), "svg_refs": a.get("svg_refs") or {}},
            "import_artifacts": [{"ref": "art://x/visio-import.xlsx", "label": "Download objects (5 objects)",
                                 "note": "matched by name", "media_type": ""}],
            "instructions": "import both files via the repository's UI"},
        "storage_get": FakeResult(content=[image_block(), text_block("diagram.png")]),
        "storage_extract_figures": FakeResult(content=[]),
    }
    t.update(over)
    return {k: v for k, v in t.items() if v is not None}


class FakeResponse:
    """An AgentResponse stand-in: `.text` + `.messages` (function_call/function_result contents ride here)."""
    def __init__(self, text, messages=None):
        self.text = text
        self.messages = messages if messages is not None else [Message("assistant", [Content.from_text(text)])]


class FakeAgent:
    def __init__(self, owner, name, instructions, credential, traceparent, tools):
        self.owner, self.name, self.instructions = owner, name, instructions
        self.credential, self.traceparent, self.tools = credential, traceparent, list(tools or [])

    @property
    def tools_by_name(self) -> dict:
        return {t.__name__: t for t in self.tools if callable(t) and hasattr(t, "__name__")}

    async def run(self, msg):
        turns = self.owner.scripts.get(self.name) or []
        assert turns, f"no scripted turn left for agent {self.name!r} (got: {text_of(msg)[:120]!r})"
        turn = turns.pop(0)
        self.owner.runs.append((self.name, msg))
        if callable(turn):
            turn = turn(self.tools_by_name, msg)
        if isinstance(turn, FakeResponse):
            return turn
        return FakeResponse(turn if isinstance(turn, str) else json.dumps(turn))


class Agents:
    """Scripted stand-in for agents.make_agent: per agent NAME an ordered list of turns — a str /
    dict (the reply text), a FakeResponse, or a callable(tools_by_name, msg) -> one of those."""
    def __init__(self, **scripts):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.made, self.runs = [], []

    def make_agent(self, name, instructions, credential, traceparent=None, tools=None):
        agent = FakeAgent(self, name, instructions, credential, traceparent, tools)
        self.made.append(agent)
        return agent

    def agent(self, name):
        return next(a for a in self.made if a.name == name)

    def runs_of(self, name):
        return [m for n, m in self.runs if n == name]


class FakeMcpTool:
    """agents.ba_tools / agents.architect_tools stand-in: the async-context MCP tool, inert."""
    def __init__(self, name, headers):
        self.name, self.headers, self.opened = name, dict(headers), 0

    async def __aenter__(self):
        self.opened += 1
        return self

    async def __aexit__(self, *exc):
        return False


class RunLog:
    """lab.platform.runlog recorder — no Redis. Node transitions + update() fields, in order."""
    def __init__(self):
        self.nodes, self.updates = [], []

    @contextlib.contextmanager
    def span_node(self, run_id, name, **attrs):
        self.nodes.append((run_id, name, "start"))
        try:
            yield
        except BaseException as e:
            self.nodes.append((run_id, name, f"fail:{type(e).__name__}"))
            raise
        self.nodes.append((run_id, name, "done"))

    def update(self, run_id, **fields):
        self.updates.append((run_id, fields))


def text_of(msg) -> str:
    """The text of a str prompt or a Message (its text contents joined)."""
    if isinstance(msg, str):
        return msg
    return "\n".join(c.text for c in msg.contents if getattr(c, "type", "") == "text")


def data_contents(msg) -> list:
    return [c for c in msg.contents if getattr(c, "type", "") == "data"]


def tool_call_response(text: str, calls: list[tuple[str, object]]) -> FakeResponse:
    """A response whose messages carry function_call + function_result pairs (what an agent that
    called its MCP tools returns; results may be dicts OR JSON strings — AF #3313)."""
    contents = []
    for i, (name, result) in enumerate(calls):
        contents.append(Content.from_function_call(call_id=f"c{i}", name=name, arguments={}))
        contents.append(Content.from_function_result(call_id=f"c{i}", result=result))
    return FakeResponse(text, [Message("assistant", contents), Message("assistant", [Content.from_text(text)])])


class RecordingTracer:
    """A tracer that keeps each span's attributes — the run's OWN audit trail, which several
    behaviours (a degraded render, a failed EA search) report ONLY through. A no-op tracer would
    make those assertions impossible; this stays otherwise identical to the real one's interface."""
    def __init__(self):
        self.spans: dict[str, dict] = {}

    @contextlib.contextmanager
    def start_as_current_span(self, name, context=None):
        attrs = self.spans.setdefault(name.replace("-agent", "").replace("-", "_"), {})

        class Span:
            def set_attribute(self, k, v):
                attrs[k] = v

            def set_attributes(self, d):
                attrs.update(d)
        yield Span()


def make_cfg(run_id="run-test", schema=SCHEMA, tracer=None):
    return W.make_cfg(ba_cred="ba-key", ar_cred="ar-key", traceparent=TRACEPARENT, schema=schema,
                      tracer=tracer or trace.get_tracer("test-workflow"), root_ctx=None,
                      mcp_url="http://gw.test/mcp/", run_id=run_id)


@contextlib.contextmanager
def harness(agents: Agents, tools: dict | None = None, *, env: dict | None = None, run_id="run-test"):
    """Patch every seam for one run; yields .router .agents .runlog .cfg."""
    # `None` for a tool means the gateway does NOT expose it (a missing grant, or a version skew) —
    # the fake must stop listing it, not just stop answering it.
    hidden = {k for k, v in (tools or {}).items() if v is None}
    router = Router(default_tools(**(tools or {})), hidden=hidden, full=True)
    rl, tracer = RunLog(), RecordingTracer()
    with ExitStack() as st:
        # TWO seams, and both are needed. `lab.workloads.gateway` is the shared gateway-MCP
        # transport every workload uses (preflight + tool calls); `W.Client` is the one session the
        # visio workflow opens itself, for a multi-term EA search. Patch only one and a test reaches
        # the network — which is how it fails, loudly, rather than silently passing.
        st.enter_context(patch.object(W, "Client", router.client_class()))
        st.enter_context(patch.object(gateway, "Client", router.client_class()))
        st.enter_context(patch.object(W.A, "make_agent", agents.make_agent))
        st.enter_context(patch.object(W.A, "ba_tools", lambda headers: FakeMcpTool("storage", headers)))
        st.enter_context(patch.object(W.A, "architect_tools", lambda headers: FakeMcpTool("ea-tools", headers)))
        st.enter_context(patch.object(W.runlog, "span_node", rl.span_node))
        st.enter_context(patch.object(W.runlog, "update", rl.update))
        st.enter_context(patch.dict(os.environ, {"BA_MODE": "json", "ARCHITECT_MODE": "json", **(env or {})}))
        os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)      # no-op tracer
        yield SimpleNamespace(router=router, agents=agents, runlog=rl, spans=tracer.spans,
                              cfg=make_cfg(run_id=run_id, tracer=tracer))


def run(h, inputs):
    return asyncio.run(W.run_workflow(h.cfg, inputs))


def raises(h, inputs, exc_type, fragment: str):
    try:
        run(h, inputs)
    except exc_type as e:
        assert fragment in str(e), str(e)
        return e
    raise AssertionError(f"expected {exc_type.__name__} containing {fragment!r}")


EXECUTOR_IDS = ["ba", "resolve_existing", "architect_design", "store", "architect_finalize", "stage_import"]
