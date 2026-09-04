"""Governance: the tool catalogue in `lab.platform.contracts` IS what each substrate MCP server registers —
both directions, per server — so a workload built against the contract can never name a tool the gateway
does not expose, and a server cannot grow a tool the contract (and the governance registry) does not know.
Offline: the server modules are imported with the environment pinned (a temp file:// store, no OTLP,
an empty reference-models dir), and the FastMCP instance is found generically (a module attribute, or
`<attr>.mcp` on a server kit) so the test survives the servers being rebuilt on a shared kit.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/governance/test_contracts_match_servers.py"""
import ast
import asyncio
import importlib
import inspect
import os
import tempfile

import pytest
import yaml
from fastmcp import FastMCP

from lab.platform import config, contracts

LITELLM_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                              "config", "litellm-config.yaml")

SERVER_MODULES = {                       # gateway alias -> the server module that registers the tools
    "storage_mcp": "lab.substrate.mcp.storage.server",
    "semantic_mcp": "lab.substrate.mcp.semantic.server",
    "ea_mcp": "lab.substrate.mcp.adoit.server",   # the ADOIT ADAPTER satisfying the vendor-neutral EA port
    "workflow_mcp": "lab.substrate.mcp.workflow.server",
    "collab_mcp": "lab.substrate.mcp.graph.server",   # the COLLABORATION port; today's adapter is Microsoft Graph
}


@pytest.fixture(scope="module")
def pinned_env():
    """Import-time pins the servers need: a throwaway store, no tracing, no licensed workbooks."""
    tmp = tempfile.mkdtemp(prefix="contracts-parity-")
    os.makedirs(os.path.join(tmp, "no-ref-models"))
    saved = {k: os.environ.get(k) for k in ("OTEL_EXPORTER_OTLP_ENDPOINT", "MCP_SHARED_SECRET")}
    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None); os.environ["MCP_SHARED_SECRET"] = "shh"
    saved_cfg = {k: getattr(config, k) for k in ("ARTIFACTS_URL", "UPLOADS_URL", "REFERENCE_MODELS_DIR")}
    config.ARTIFACTS_URL = config.UPLOADS_URL = f"file://{tmp}/store"
    config.REFERENCE_MODELS_DIR = os.path.join(tmp, "no-ref-models")
    yield
    for k, v in saved_cfg.items():
        setattr(config, k, v)
    for k, v in saved.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def _fastmcp_of(module) -> FastMCP:
    """The server's FastMCP: a module attribute, or `.mcp` on a module attribute (a server kit object)."""
    for _, v in vars(module).items():
        if isinstance(v, FastMCP):
            return v
    for _, v in vars(module).items():
        inner = getattr(v, "mcp", None)
        if isinstance(inner, FastMCP):
            return inner
    raise AssertionError(f"no FastMCP instance found in {module.__name__}")


def registered_tools(module) -> frozenset[str]:
    tools = _fastmcp_of(module).list_tools()
    if inspect.isawaitable(tools):
        tools = asyncio.run(tools)
    return frozenset(t.name for t in (tools.values() if isinstance(tools, dict) else tools))


@pytest.mark.parametrize("alias", sorted(SERVER_MODULES))
def test_contract_catalogue_equals_the_servers_registered_tools(alias, pinned_env):
    module = importlib.import_module(SERVER_MODULES[alias])
    registered, contract = registered_tools(module), contracts.SERVERS[alias].names()
    assert registered - contract == set(), f"{alias}: server tools missing from the contract"
    assert contract - registered == set(), f"{alias}: contract names no server tool"


def test_every_registered_server_forwards_trace_context():
    """`extra_headers: [traceparent, tracestate]` on EVERY server: without it the gateway drops W3C
    trace context and the server's spans land in a SEPARATE trace (verified both ways, CLAUDE.md)."""
    servers = yaml.safe_load(open(LITELLM_CONFIG, encoding="utf-8"))["mcp_servers"]
    for alias, spec in servers.items():
        assert spec.get("extra_headers") == ["traceparent", "tracestate"], alias
        assert spec.get("auth_type") == "bearer_token" and spec.get("description"), alias


VENDORS = ("adoit", "bizzdesign", "archi_", "boc")     # EA-tool product names — a PORT must not name one
# Product names that may not appear in a tool NAME or a gateway ALIAS. Deliberately a SEPARATE list
# from VENDORS: the downstream test below scans CODE with string literals preserved, and
# src/lab/substrate/review/app.py says "**Workflow graph**" — sharing one list would fail that test
# for a reason that has nothing to do with a vendor leaking into a port.
NAME_VENDORS = VENDORS + ("microsoft", "graph", "sharepoint", "onedrive", "teams", "m365",
                          "office365", "entra")


def test_no_tool_or_alias_names_a_vendor():
    """The PORT is vendor-neutral: swapping ADOIT for another EA tool is a different server satisfying
    the SAME tools under the SAME gateway alias, with no workload change. A vendor word anywhere in the
    catalogue (`adoit_search`) or in an alias (`adoit_mcp`) breaks that — the workload would have to be
    re-edited to call the replacement. The vendor lives in the SERVICE (adoit-mcp, ADOIT_MCP_URL,
    its credentials), never in the contract."""
    named = [n for n in sorted(contracts.ALL_TOOLS) + sorted(contracts.SERVERS)
             if any(v in n.lower() for v in NAME_VENDORS)]
    assert named == [], f"vendor name in the tool contract: {named}"


# What a repository ADAPTER may know and nothing downstream of the port may: the EA product itself,
# and the FILE FORMAT this particular product happens to need a human to import.
DOWNSTREAM = VENDORS + ("xlsx", "excel", "spreadsheet", "objects.xls")

# The modules an approval passes THROUGH on its way from the adapter to the human who decides it.
DOWNSTREAM_MODULES = ("src/lab/platform/contracts.py",
                      "src/lab/substrate/mcp/workflow/approval_tools.py",
                      "src/lab/substrate/review/app.py")


def _code_without_prose(path):
    """The module's CODE — every docstring replaced, comments dropped by unparse. Prose may name ADOIT
    (it explains why the adapter exists); executable code downstream of the port may not."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    for n in ast.walk(tree):
        if (isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body
                and isinstance(n.body[0], ast.Expr)
                and isinstance(getattr(n.body[0].value, "value", None), str)):
            n.body[0] = ast.Expr(ast.Constant("<docstring>"))
    return ast.unparse(ast.fix_missing_locations(tree))


def test_nothing_downstream_of_the_ea_port_names_a_vendor_or_its_file_format():
    """The PORT was neutralised (`ea_search`, `ea_stage_import`, alias `ea_mcp`); this is the ratchet
    for everything the approval flows through AFTER it. The reviewer's experience is unchanged — same
    downloads, same guidance — but the knowledge lives on the ADAPTER, which labels its own artifacts
    and writes its own instructions; the approval carries them as an opaque {ref, label, note} list and
    the review app RENDERS them. So:

      * the approval KIND may not name a vendor (`adoit-import` -> `ea-import`);
      * a process's declared OUTPUTS may not name one, nor the file format of one repository's import
        (`xlsx_ref` -> `import_artifacts`) — a workload's caller must not learn what ADOIT:CE needs;
      * the review app's decision path may not KNOW what a spreadsheet is: no vendor word, no file
        format, in executable code (docstrings still explain the history).

    Adding a repository adapter that needs a different file must therefore change the adapter only."""
    named = [k.value for k in contracts.ApprovalKind if any(v in k.value.lower() for v in DOWNSTREAM)]
    assert named == [], f"vendor name in the approval kind: {named}"

    outputs = sorted({o for spec in contracts.PROCESSES.values() for o in spec.outputs
                      if any(v in o.lower() for v in DOWNSTREAM)})
    assert outputs == [], f"vendor name in a process's declared outputs: {outputs}"

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    offenders = {}
    for rel in DOWNSTREAM_MODULES:
        code = _code_without_prose(os.path.join(root, rel)).lower()
        hits = sorted({v for v in DOWNSTREAM if v in code})
        if hits:
            offenders[rel] = hits
    assert offenders == {}, f"vendor/file-format knowledge downstream of the port: {offenders}"


def split_catalogues() -> dict[str, type]:
    """Every catalogue that declares a READ/WRITE grant split — derived from the registry, so a new
    one is covered the moment it is registered instead of the day someone remembers this test."""
    return {c.SERVER: c for c in contracts.SERVERS.values() if getattr(c, "WRITE", ())} | \
           {contracts.ApprovalTools.SERVER: contracts.ApprovalTools}


def test_a_split_catalogue_really_splits_its_tools_in_two():
    """The shape the ACL depends on: READ and WRITE partition the catalogue, so a grant built from
    them can neither omit a tool nor hand one over twice."""
    assert set(split_catalogues()) >= {"workflow_mcp", "collab_mcp"}
    assert contracts.ApprovalTools.WRITE == ("approvals_decide",)      # exactly one tool writes a decision
    assert set(contracts.ApprovalTools.READ) < contracts.WorkflowTools.names()
    for alias, cat in split_catalogues().items():
        read, write = set(cat.READ), set(cat.WRITE)
        assert read and write and not (read & write), alias
        assert read | write == set(cat.names()) or cat is contracts.ApprovalTools, alias


def test_no_grant_hands_a_team_a_guarded_write_by_accident():
    """A catalogue with a WRITE grant carries tools that must NOT reach a workload's own agents:
    `approvals_decide` records a PERSON's decision to release an EA-repository write, and
    `collab_watch` creates egress to a caller-supplied URL plus a durable provider-side object that
    outlives the run. Granting such a SERVER without naming its tools (`mcp_tool_permissions`) hands
    those over silently — a submitting agent approving its own run, or an agent subscribing the
    tenant to a destination of its choosing. Today no provisioning script grants either server; this
    is the ratchet that keeps a future one honest, for every split catalogue there ever is."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    offenders = []
    for base, _, files in os.walk(os.path.join(root, "scripts")):
        for f in (x for x in files if x.endswith(".py")):
            src = open(os.path.join(base, f), encoding="utf-8").read()
            for alias in split_catalogues():
                for line in src.splitlines():
                    if f'"{alias}"' in line and "mcp_servers" in line and "mcp_tool_permissions" not in src:
                        offenders.append(f"{f}: {line.strip()}")
    assert offenders == [], ("a server with a guarded WRITE grant was granted without a per-tool "
                            f"ACL: {offenders}")


def test_every_gateway_server_alias_has_a_contract():
    """The contract's aliases ARE the gateway's `mcp_servers` keys — read from litellm-config.yaml, because
    the alias is what `StorageTools.gateway()` bakes into the agents' `allowed_tools`: rename one in the
    YAML only and an agent silently gets zero tools."""
    registered = set(yaml.safe_load(open(LITELLM_CONFIG, encoding="utf-8"))["mcp_servers"])
    assert registered == set(contracts.SERVERS) == set(SERVER_MODULES)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
