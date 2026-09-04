"""src/lab/workloads/workflowviz.py — Mermaid for a built Agent Framework workflow, never a host failure.
OFFLINE: a two-executor WorkflowBuilder graph, plus the guarded failure paths with WorkflowViz stubbed."""
import sys
import types


import agent_framework
from agent_framework import WorkflowBuilder, WorkflowContext, executor

from fixtures.fakes import run_script
from lab.workloads import workflowviz


def _two_node_workflow():
    @executor(id="read_diagram")
    async def read_diagram(text: str, ctx: WorkflowContext[str]) -> None:
        await ctx.send_message(text.upper())

    @executor(id="render")
    async def render(text: str, ctx: WorkflowContext[None, str]) -> None:
        await ctx.yield_output(text)
    return WorkflowBuilder(start_executor=read_diagram).add_edge(read_diagram, render).build()


def test_mermaid_for_a_built_workflow():
    out = workflowviz.mermaid(_two_node_workflow())
    assert out.startswith("flowchart TD") and "read_diagram" in out and "render" in out and "-->" in out, out
    full = workflowviz.mermaid(_two_node_workflow(), include_internal_executors=True)
    assert isinstance(full, str) and "read_diagram" in full


def test_none_and_non_workflow_return_none():
    assert workflowviz.mermaid(None) is None
    assert workflowviz.mermaid(object()) is None
    assert workflowviz.mermaid("not a workflow") is None


def _with_stub(to_mermaid):
    class Stub:
        def __init__(self, wf): self.wf = wf
    Stub.to_mermaid = to_mermaid
    real = agent_framework.WorkflowViz
    agent_framework.WorkflowViz = Stub
    try:
        return workflowviz.mermaid(object())
    finally:
        agent_framework.WorkflowViz = real


def test_older_signature_fallback_and_bad_outputs():
    assert _with_stub(lambda self: "flowchart TD\n a --> b") == "flowchart TD\n a --> b", "no-kwarg signature -> retried"

    def always_type_error(self, **kw):
        raise TypeError("nope")
    assert _with_stub(always_type_error) is None
    assert _with_stub(lambda self, include_internal_executors=False: "   ") is None, "blank -> None"
    assert _with_stub(lambda self, include_internal_executors=False: b"bytes") is None, "not a str -> None"

    def boom(self, include_internal_executors=False):
        raise RuntimeError("graph broken")
    assert _with_stub(boom) is None


def test_missing_viz_api_is_logged_not_raised():
    real = sys.modules["agent_framework"]
    sys.modules["agent_framework"] = types.ModuleType("agent_framework")       # no WorkflowViz at all
    try:
        assert workflowviz.mermaid(object()) is None
    finally:
        sys.modules["agent_framework"] = real


def test_cli():
    code, out, _ = run_script("src/lab/workloads/workflowviz.py", [])
    assert code == 0 and out.strip() == "None"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
