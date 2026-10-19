"""Governance: the ARGUMENTS a workload passes to a governed tool are arguments that tool accepts.

`test_contracts_match_servers` pins the tool NAMES in both directions. Names were never the whole
contract, and the argument half cost a live regression on 12 Oct 2026: `artifact_intake` began passing
`proposed_for` to `semantic_vocab_propose`, which the domain method accepted and the TOOL did not.
FastMCP refuses an unexpected keyword, a ToolError is not transient so nothing retries it, and the call
sits in an executor with no handler — so every intake run meeting an unknown term failed. It reached the
cloud, because nothing offline objected:

  * `preflight` resolves REQUIRED_TOOLS by name and passes;
  * the parity test compares name sets and passes;
  * the workload's own unit test passes, because `tests/fixtures/workflow.Router` calls a stub and
    validates no arguments. That double's `names()` was hardened after the 320-second version-skew
    failure for exactly this reason — "test doubles must model a REAL gateway" — and the argument half
    is the same lesson, unlearned.

This closes it from the other side, statically: every `gateway.call(cfg, <Catalogue>.<verb>, {...})`
whose argument dict is a LITERAL is checked against the server's own parameter schema. A call built
from a variable is skipped and counted — an AST cannot know its keys, and a check that pretended to
would be worse than one that says what it covered.

Offline: the servers are imported with the environment pinned, exactly as the parity test does.
"""
import ast
import asyncio
import importlib
import os
import pathlib
import tempfile

import pytest
from fastmcp import FastMCP

from lab.platform import config, contracts

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKLOADS = ROOT / "src/lab/workloads"
SUBSTRATE = ROOT / "src/lab/substrate"

#: alias -> server module, the same table the parity test keeps (one place would be better; this test
#: exists to be additive, so it reads the parity test's table rather than growing a third).
from tests.governance.test_contracts_match_servers import SERVER_MODULES  # noqa: E402


@pytest.fixture(scope="module")
def accepted() -> dict[str, tuple[set[str], set[str]]]:
    """tool name -> (every accepted parameter, the required ones), from the SERVERS themselves."""
    tmp = tempfile.mkdtemp(prefix="arg-parity-")
    os.makedirs(os.path.join(tmp, "no-ref-models"))
    saved_env = {k: os.environ.get(k) for k in ("OTEL_EXPORTER_OTLP_ENDPOINT", "MCP_SHARED_SECRET")}
    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    os.environ["MCP_SHARED_SECRET"] = "shh"
    saved = {k: getattr(config, k) for k in ("ARTIFACTS_URL", "UPLOADS_URL", "REFERENCE_MODELS_DIR")}
    config.ARTIFACTS_URL = config.UPLOADS_URL = f"file://{tmp}/store"
    config.REFERENCE_MODELS_DIR = os.path.join(tmp, "no-ref-models")
    out: dict[str, tuple[set[str], set[str]]] = {}
    try:
        for module in SERVER_MODULES.values():
            m = importlib.import_module(module)
            mcp = next((getattr(v, "mcp") for v in vars(m).values()
                        if isinstance(getattr(v, "mcp", None), FastMCP)),
                       next((v for v in vars(m).values() if isinstance(v, FastMCP)), None))
            tools = mcp.list_tools()
            if asyncio.iscoroutine(tools):
                tools = asyncio.run(tools)
            for t in (tools.values() if isinstance(tools, dict) else tools):
                p = t.parameters or {}
                out[t.name] = (set(p.get("properties") or {}), set(p.get("required") or []))
    finally:
        for k, v in saved.items():
            setattr(config, k, v)
        for k, v in saved_env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    return out


def _tool_of(node: ast.AST) -> str | None:
    """`SemanticTools.vocab_propose` -> "semantic_vocab_propose", resolved through the catalogue itself
    so a renamed verb cannot drift past this test."""
    if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
        return None
    cat = getattr(contracts, node.value.id, None)
    name = getattr(cat, node.attr, None) if cat is not None else None
    return name if isinstance(name, str) else None


def _literal_keys(node: ast.AST) -> set[str] | None:
    """The dict's keys when every one is a literal string, else None (a variable, or **spread)."""
    if not isinstance(node, ast.Dict):
        return None
    keys = set()
    for k in node.keys:
        if not isinstance(k, ast.Constant) or not isinstance(k.value, str):
            return None                      # `**base` has a None key; a computed key is unknowable
        keys.add(k.value)
    return keys


def _tuple_sites() -> list[tuple[str, int, str, set[str]]]:
    """The SUBSTRATE's call shape: `call([(Tool.x, {...}), …])` — a list of (tool, args) tuples.

    The workloads pass three positional arguments; the fabric's appliers and sweeps pass tuple lists
    through `fabric_gateway.call`, so the collector above never looked at them. That is how
    `vocab_place` came to be called with `cid` when its parameter is `concept_id` — an argument fastmcp
    refuses outright, i.e. a write path that cannot work, with 2411 tests green and a design review
    needed to find it. The two shapes are two collectors; the assertion over them is one."""
    sites = []
    for path in sorted(SUBSTRATE.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Tuple) or len(node.elts) != 2:
                continue
            tool, keys = _tool_of(node.elts[0]), _literal_keys(node.elts[1])
            if tool and keys is not None:
                sites.append((str(path.relative_to(ROOT)), node.lineno, tool, keys))
    return sites


def _call_sites() -> list[tuple[str, int, str, set[str]]]:
    """(file, line, tool, literal arg keys) for every statically readable gateway call in a workload."""
    sites = []
    for path in sorted(WORKLOADS.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and len(node.args) >= 3):
                continue
            f = node.func
            called = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if called != "call":
                continue
            tool = _tool_of(node.args[1])
            keys = _literal_keys(node.args[2])
            if tool and keys is not None:
                sites.append((str(path.relative_to(ROOT)), node.lineno, tool, keys))
    return sites


def test_every_literal_argument_the_SUBSTRATE_passes_is_one_its_tool_accepts(accepted):
    """The same invariant over the substrate's `(tool, args)` tuples — the fabric's appliers and sweeps."""
    sites = _tuple_sites()
    assert len(sites) >= 15, f"only {len(sites)} substrate call sites parsed — the AST shapes have moved"
    wrong = []
    for file, line, tool, keys in sites:
        if tool not in accepted:
            continue                         # a tool on no server in the table; the parity test owns that
        params, _required = accepted[tool]
        unknown = keys - params
        if unknown:
            wrong.append(f"{file}:{line} calls {tool} with {sorted(unknown)}; it accepts {sorted(params)}")
    assert not wrong, ("the substrate passes an argument its tool would refuse — fastmcp raises "
                       "'Unexpected keyword argument' and the answer is never applied:\n  "
                       + "\n  ".join(wrong))


def test_every_literal_argument_a_workload_passes_is_one_its_tool_accepts(accepted):
    """The regression this exists for, stated as an invariant: a workload may not name an argument the
    server would refuse. Unknown keywords only — a MISSING required argument is not checked here,
    because a tool is legitimately called with its defaults and the schema's `required` says what the
    FUNCTION demands, not what this call site must spell out."""
    sites = _call_sites()
    assert len(sites) >= 40, f"only {len(sites)} call sites parsed — the AST shapes have moved"
    bad = []
    for path, line, tool, keys in sites:
        if tool not in accepted:
            continue                        # a tool on no server in the table; the parity test owns that
        params, _required = accepted[tool]
        unknown = keys - params
        if unknown:
            bad.append(f"{path}:{line} calls {tool} with {sorted(unknown)}; it accepts {sorted(params)}")
    assert not bad, ("a workload passes an argument its tool would refuse — fastmcp raises "
                     "'Unexpected keyword argument' and the run dies:\n  " + "\n  ".join(bad))


def test_the_check_reports_how_much_it_could_not_read():
    """An instrument that cannot fail loudly is not an instrument, and one that silently covers half of
    what it claims is worse. A call whose arguments are built in a variable is invisible to an AST, so
    the count is printed: if it ever dominates, this test is reassurance rather than a guard."""
    readable = _call_sites()
    total = 0
    for path in sorted(WORKLOADS.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            f = getattr(node, "func", None)
            if isinstance(node, ast.Call) and len(getattr(node, "args", [])) >= 3 and (
                    (f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")) == "call"):
                total += 1
    print(f"\ngateway call sites: {total}  ·  argument-checked: {len(readable)}  "
          f"·  opaque (args in a variable): {total - len(readable)}")
    assert len(readable) >= total // 2, (f"only {len(readable)} of {total} call sites have literal "
                                         "arguments — this test no longer covers most of them")
