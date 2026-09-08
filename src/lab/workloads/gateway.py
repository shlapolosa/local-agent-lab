"""How a workload talks to the gateway's MCP surface — the ONE implementation, shared by every
business process.

A workload holds no tool credentials and reaches every capability through the gateway, so this is
the only transport it has. It lived inside the first workload until a second one needed it; putting
it here is the DRY rule ("one home per piece of logic", and a helper used by more than one workload
belongs to the tier, not to a process).

Two behaviours are the reason this is shared rather than copied:

  * **Tools are resolved by NAME SUFFIX.** The gateway exposes `<server alias>-<tool>`, and a
    workload is deliberately ALIAS-AGNOSTIC: renaming an alias must not break a running process.
    Both the preflight and the per-call path resolve identically, or preflight would pass on a name
    the call then fails to find.
  * **A version mismatch costs zero tokens.** The tools a run needs are knowable before the first
    node executes. A cloud run once died 320 seconds in, after an agent had already spent its
    budget, because the workload and the gateway were deployed from different commits — so the whole
    list is checked up front and the run is refused with the missing names spelled out.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from lab.platform.contracts import ArtifactRef

__all__ = ["auth_headers", "call", "call_tools", "call_tools_raw", "node_span",
           "preflight", "ref_from", "resolve", "run_graph"]


def resolve(exposed: Iterable[str], suffix: str) -> str:
    """The gateway's name for a tool, matched by suffix. Raises naming what is exposed."""
    names = list(exposed)
    match = [n for n in names if n.endswith(suffix)]
    if not match:
        raise RuntimeError(f"tool *{suffix} not exposed by gateway ({names})")
    return match[0]


async def preflight(mcp_url: str, headers: Mapping[str, str], required: Iterable[Any]) -> None:
    """Refuse the run if the gateway cannot serve what this workload will ask of it.

    Two checks, and the second exists because the first was not enough. A required entry is either
    a tool NAME, or a `(name, arguments)` pair naming the arguments this workload sends.

    **Names.** Resolution is by suffix, identically to `call_tools_raw`, so renaming a gateway alias
    does not fail preflight — what DOES fail it is a renamed or withdrawn tool.

    **Arguments.** A tool can be present under the right name and still reject the call, because the
    deployed server is older than the workload and its schema has no such property. Measured: a
    screening run passed preflight, spent fifty-five minutes and six model calls deriving a
    complete record, and died at the approval on `'process' was unexpected` — a workflow-mcp four
    days older than the workload. Name-only preflight cannot see that, and it is the same version
    skew the name check was built for, one level down. The whole point of preflight is to cost
    ZERO tokens; a check that stops one class of skew and waves the next one through is half an
    instrument.

    Argument checking is best-effort by design: a server that publishes no `inputSchema`, or one
    that accepts extra properties, is not second-guessed. Only a schema that explicitly closes
    itself (`additionalProperties: false`) and omits a property we will send is a refusal — which
    is exactly the case that fails at call time.
    """
    wanted = {(r if isinstance(r, str) else r[0]): (() if isinstance(r, str) else tuple(r[1]))
              for r in required}
    async with Client(StreamableHttpTransport(mcp_url, headers=dict(headers or {}))) as c:
        tools = await c.list_tools()
    exposed = [t.name for t in tools]
    missing = [t for t in wanted if not any(n.endswith(t) for n in exposed)]
    if missing:
        raise RuntimeError(
            f"gateway does not expose {missing} — this workload and the gateway are running different "
            f"versions, or this identity is not granted those servers. Redeploy both from the same "
            f"image (the deploy CLI's `substrate images` shows what each service runs) or fix "
            f"the team grant. Exposed: {sorted(exposed)}")

    stale: list[str] = []
    for tool in tools:
        args = next((a for suffix, a in wanted.items() if tool.name.endswith(suffix)), ())
        schema = getattr(tool, "inputSchema", None) or {}
        if not args or schema.get("additionalProperties") is not False:
            continue
        unknown = [a for a in args if a not in (schema.get("properties") or {})]
        if unknown:
            stale.append(f"{tool.name} does not accept {unknown}")
    if stale:
        raise RuntimeError(
            f"the gateway exposes every tool this workload needs, but not every ARGUMENT: {stale}. "
            f"The deployed server is older than this workload — redeploy both from the same image "
            f"(`substrate images`). Refusing now costs nothing; finding out at the call costs the "
            f"whole run.")


async def call_tools_raw(headers: Mapping[str, str], mcp_url: str, calls) -> list[Any]:
    """Call gateway-MCP tools by name suffix; returns the RAW fastmcp results.

    Raw because `.content` is where image blocks live — `.data` is None for an image result, so a
    caller that needs pictures cannot use the convenience wrapper below.
    """
    async with Client(StreamableHttpTransport(mcp_url, headers=dict(headers or {}))) as c:
        names = [t.name for t in await c.list_tools()]
        return [await c.call_tool(resolve(names, sfx), args) for sfx, args in calls]


async def call_tools(headers: Mapping[str, str], mcp_url: str, calls) -> list[Any]:
    """The `.data`-only convenience wrapper — everything that is not an image."""
    return [r.data for r in await call_tools_raw(headers, mcp_url, calls)]


def ref_from(res: Any, key: str = "spec_ref") -> str:
    """The `art://` ref out of an MCP result — a dict, or a JSON string (MCP results can arrive as
    strings) — validated as a well-formed reference, so a malformed one fails HERE rather than three
    tool calls later where the cause is no longer obvious."""
    return str(ArtifactRef.parse((res if isinstance(res, dict) else json.loads(res))[key]))


# --------------------------------------------------------------- the shape every workflow shares
#
# `auth_headers`, `node_span`, `call` and `run_graph` were written seven times, once per workload,
# and the duplication had stopped being cheaper than the coupling. The precedent in CLAUDE.md is
# the decisive one: `lab.platform.streams` exists because three blocking-read rules were each
# learned once and fixed in whichever copy happened to be in front of somebody. `run_graph` carries
# a preflight rule that was paid for by a 320-second cloud failure; it should not exist seven
# times, because the eighth copy is the one that will not have it.
#
# What is deliberately NOT here is `make_cfg`. Its SIGNATURE is each process's config contract —
# `agents`, `authority_table`, `languages`, `schema` — and collapsing those into one would make
# every workload's configuration the union of every other's.

def auth_headers(credential: str, traceparent: str = "") -> dict[str, str]:
    """The headers a workload calls the gateway with: its own credential, and the trace it belongs
    to. The traceparent is what joins the gateway's and every MCP server's spans to THIS run."""
    headers = {"Authorization": f"Bearer {credential}"} if credential else {}
    if traceparent:
        headers["traceparent"] = traceparent
    return headers


def node_span(cfg: Mapping[str, Any], node: str):
    """A run-log span for one node, or nothing when the run is not on the board (a CLI or test
    run). A null context rather than a branch at every call site."""
    import contextlib

    from lab.platform import runlog
    rid = cfg.get("run_id")
    return runlog.span_node(rid, node) if rid else contextlib.nullcontext()


async def call(cfg: Mapping[str, Any], suffix: str, args: Mapping[str, Any]) -> Any:
    """ONE governed tool call, by suffix. Suffix rather than full name because the gateway prefixes
    a server's alias and a workload must stay alias-agnostic."""
    return (await call_tools(cfg["headers"], cfg["mcp_url"], [(suffix, args)]))[0]


async def run_graph(cfg: Mapping[str, Any], build, inputs: Mapping[str, Any], *, what: str,
                    required: Iterable[str]) -> dict:
    """Preflight, publish the graph to the run board, run it, and return the one output.

    The preflight is the part that must not be forgotten: it lists the gateway's tools and refuses
    a run whose contract is not exposed, for zero tokens, rather than dying twenty minutes in on a
    tool a version-skewed gateway no longer has."""
    await preflight(cfg["mcp_url"], cfg["headers"], required)
    workflow = build(cfg)
    if cfg.get("run_id"):
        from lab.platform import runlog
        from lab.workloads import workflowviz
        runlog.update(cfg["run_id"], mermaid=workflowviz.mermaid(workflow))
    outputs = (await workflow.run(dict(inputs))).get_outputs()
    if not outputs:
        raise RuntimeError(f"the {what} run produced no output")
    return outputs[0]
