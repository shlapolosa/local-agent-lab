"""Every `state` key a workload reads is one something actually writes.

This exists because of a defect class that produced five separate bugs in one batch and would have
produced more. A workload's `state` is an untyped dict threaded through executors, so
`state.get("role_rates")` is indistinguishable from `state.get("rolerates")` — and both are
indistinguishable from a key somebody INTENDED to wire and never did. The failure is always silent
and always in the same direction: the derivation runs, reads `{}`, and returns a confident answer
pinned to a constant. Three governed derivations were being fed empty tables this way, and the
hardcoded values two commits had just removed came straight back through the unwired path.

So: a key read from `state` must be a declared input of the process, or written by an executor in
the same module. Anything else is a typo or an intention, and both are worth failing a build over.

AST-based, offline, and it generalises — it reads every workload workflow module in the tree, so a
new process is covered the day it lands rather than the day somebody remembers.
"""
import ast
from pathlib import Path

import pytest

from lab.platform.contracts import PROCESSES

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / "src" / "lab" / "workloads").glob("*/workflow.py"))

#: Keys a workflow legitimately reads that no executor writes and no contract declares, with the
#: reason. Each entry is a claim somebody has checked — NOT a place to park a defect.
ALLOWED = {
    # `governed_run` writes this onto the inputs before the graph starts.
    "trace_id",
}


def _process_for(path: Path) -> object | None:
    """The ProcessSpec a workflow module belongs to, by directory name."""
    return PROCESSES.get(path.parent.name)


def _host_supplies(path: Path) -> set[str]:
    """Keys the HOST puts into the workflow's starting state.

    The third writer, and a legitimate one: a host may compose a value from the process's declared
    inputs before the graph starts (`meeting` is built from `recording`, `transcript` and
    `chat_id`). That composition belongs in the composition root, so it is not an InputField and
    not written by any executor — but it is not unwired either."""
    host = path.parent / "host.py"
    if not host.exists():
        return set()
    keys: set[str] = set()
    for node in ast.walk(ast.parse(host.read_text())):
        if isinstance(node, ast.keyword) and node.arg == "inputs" and isinstance(node.value,
                                                                                ast.Dict):
            keys.update(k.value for k in node.value.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str))
        # `inputs = {...}` then `inputs=inputs` — the same composition, spelled over two lines.
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                and any(isinstance(t, ast.Name) and t.id == "inputs" for t in node.targets)):
            keys.update(k.value for k in node.value.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str))
    return keys


def _reads_and_writes(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Keys read from `state`, and keys any `state | {...}` literal writes."""
    reads: set[str] = set()
    writes: set[str] = set()
    for node in ast.walk(tree):
        # state.get("x") / state.get("x", default)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "state" and node.args
                and isinstance(node.args[0], ast.Constant)):
            reads.add(node.args[0].value)
        # state["x"] — a read on Load, a WRITE on Store. Both spellings are in the tree
        # (`state["spec"], state["spec_ref"] = spec, ref` is how the visio workflow builds its
        # state), so the context is what separates them.
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                and node.value.id == "state" and isinstance(node.slice, ast.Constant)):
            (writes if isinstance(node.ctx, ast.Store) else reads).add(node.slice.value)
        # `state | {...}` and `{**state, ...}` — the two ways an executor adds to the state.
        # Deliberately NOT every dict literal: a tool-argument dict `{"conditions": state.get(
        # "conditions")}` carries the same key it reads, so counting it as a write would make the
        # test pass on exactly the defect it exists to catch. Measured — it did.
        merged = None
        # `ctx.send_message({...})` — the FIRST executor in a chain builds the next one's state
        # from scratch rather than merging, so its literal is a write too.
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "send_message" and node.args
                and isinstance(node.args[0], ast.Dict)):
            merged = node.args[0]
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr)
                and isinstance(node.left, ast.Name) and node.left.id == "state"
                and isinstance(node.right, ast.Dict)):
            merged = node.right
        if isinstance(node, ast.Dict) and any(k is None and isinstance(v, ast.Name)
                                              and v.id == "state"
                                              for k, v in zip(node.keys, node.values)):
            merged = node
        if merged is not None:
            writes.update(k.value for k in merged.keys
                          if isinstance(k, ast.Constant) and isinstance(k.value, str))
    return reads, writes


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.parent.name)
def test_every_state_key_read_is_one_something_writes(path):
    spec = _process_for(path)
    if spec is None:
        pytest.skip(f"{path.parent.name} declares no ProcessSpec")
    reads, writes = _reads_and_writes(ast.parse(path.read_text()))
    declared = ({f.name for f in spec.inputs} | set(spec.outputs) | ALLOWED
                | _host_supplies(path))
    orphans = sorted(reads - writes - declared)
    assert not orphans, (
        f"{path.parent.name} reads {orphans} from its state, and nothing in the module writes them "
        f"and no input declares them. A governed derivation fed an unwired key returns a confident "
        f"answer pinned to a constant, and nothing downstream can tell.")
