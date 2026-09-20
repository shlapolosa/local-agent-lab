"""A node says what it DOES, and the label travels from the declaration to the page.

`step_5`, `derive`, `validate_and_persist` are addresses. The screen must not be where a human
name for them is invented — the workload that declares the node is the only place that knows what
it is for, so the label is stamped with the node and the page renders whatever arrived.
"""
from lab.platform import runlog
from lab.workloads import gateway
from lab.workloads.usecase import derivation
from lab.workloads.usecase.steps import step_for


def test_a_node_span_carries_whatever_the_declaration_said(monkeypatch):
    seen = []
    monkeypatch.setattr(runlog, "node", lambda rid, name, status, **kw: seen.append((name, status, kw)))
    with gateway.node_span({"run_id": "r1"}, "derive", title="run the screening steps"):
        pass
    assert seen[0][2]["title"] == "run the screening steps"
    assert seen[0][1] == "start" and seen[-1][1] == "done"


def test_a_run_not_on_a_board_still_takes_a_title_without_complaining():
    with gateway.node_span({}, "derive", title="run the screening steps"):
        pass                                   # a null context: no board, no error, no branch


def test_the_step_shape_is_stamped_with_the_step_s_own_title(monkeypatch):
    seen = {}
    monkeypatch.setattr(runlog, "node", lambda rid, name, status, **kw: seen.update(kw))
    derivation.stamp_shape({"run_id": "r1"}, step_for("5"), {"matched": []})
    assert seen["title"] == "match capabilities" and seen["key"] == "coverage_map"


# ------------------------------------------------------- every declared executor has a label

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
WORKFLOWS = ("use_case_screening", "use_case_design")


def _executor_ids(module: str) -> set[str]:
    """The ids as DECLARED — read from `@executor(id=...)` rather than from a list someone keeps in
    step with it, which is the list that goes stale."""
    tree = ast.parse((ROOT / "src" / "lab" / "workloads" / module / "workflow.py").read_text())
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "executor":
            out |= {k.value.value for k in n.keywords if k.arg == "id"}
    return out


@pytest.mark.parametrize("module", WORKFLOWS)
def test_every_declared_executor_has_a_title(module):
    from importlib import import_module
    nodes = import_module(f"lab.workloads.{module}.workflow").NODES
    missing = sorted(_executor_ids(module) - set(nodes))
    assert not missing, f"{module}: executors with no title: {missing}"
    assert all(t and len(t.split()) <= 6 for t in nodes.values())
