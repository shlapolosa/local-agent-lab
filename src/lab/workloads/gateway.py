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

import asyncio
import functools
import json
from collections.abc import Iterable, Mapping
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from lab.platform.contracts import ArtifactRef
from lab.platform.webhook import get_json, post_json

__all__ = ["auth_headers", "call", "call_tools", "call_tools_raw", "node_span",
           "preflight", "preflight_stores", "ref_from", "resolve", "run_graph", "vector_search"]


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

    # Resolve exactly as the CALL will. Checking every tool whose name ends with a wanted suffix
    # would refuse a run because of a tool that would never be called — a stale duplicate
    # registration, or a second server exposing a same-named tool. A false refusal is worse than
    # the gap this closes.
    by_name = {t.name: t for t in tools}
    stale: list[str] = []
    for suffix, args in wanted.items():
        if not args:
            continue
        schema = getattr(by_name[resolve(by_name, suffix)], "inputSchema", None) or {}
        if schema.get("additionalProperties") is not False:
            continue
        unknown = [a for a in args if a not in (schema.get("properties") or {})]
        if unknown:
            stale.append(f"{resolve(by_name, suffix)} does not accept {unknown}")
    if stale:
        raise RuntimeError(
            f"the gateway exposes every tool this workload needs, but not every ARGUMENT: {stale}. "
            f"The deployed server is older than this workload — redeploy both from the same image "
            f"(`substrate images`). Refusing now costs nothing; finding out at the call costs the "
            f"whole run.")


async def preflight_stores(gateway_url: str, headers: Mapping[str, str],
                           required: Iterable[str], *, http=None) -> None:
    """Refuse the run if the gateway does not register every relevance store it will search.

    The same contract as `preflight` for tools, one level over: a store is registered in the
    gateway (`vector_store_registry`) and granted per team, and a name the gateway does not list —
    a renamed artifact, a stale config, a missing grant — should cost zero tokens, not a run. The
    gateway's registry listing (`/vector_store/list`) answers with the stores THIS identity may
    see, so a grant gap reads as a missing store here rather than as a 401 mid-run."""
    wanted = [s for s in required if s]
    if not wanted:
        return
    raw = await asyncio.to_thread(http or get_json,
                                  f"{gateway_url.rstrip('/')}/vector_store/list?page_size=200",
                                  headers=dict(headers or {}))
    page = json.loads(raw)
    data = page.get("data") or []
    # One page, deliberately: a registry of two hundred stores is not this lab. But a store on a
    # SECOND page must not read as "not registered", so a longer registry fails loudly here.
    if int(page.get("total_count") or 0) > len(data):
        raise RuntimeError(f"the gateway registers {page.get('total_count')} relevance stores, "
                           f"more than one page; preflight cannot see them all")
    listed = {str(v.get("vector_store_id", "")) for v in data}
    missing = sorted(set(wanted) - listed)
    if missing:
        raise RuntimeError(
            f"the gateway does not register the relevance store(s) {missing} for this identity — "
            f"the vector_store_registry and this workload are from different versions, or the "
            f"team is not granted them (object_permission.vector_stores). Registered: "
            f"{sorted(listed)}")


SEARCH_TIMEOUT_S = 120


async def vector_search(gateway_url: str, headers: Mapping[str, str], store: str, query: str, *,
                        filters: Mapping[str, Any], k: int = 8, http=None) -> list[dict]:
    """ONE relevance query over a governed store, through the gateway.

    `filters` is the run's identity — pin_id, run_id, process, field — which the corpus's façade
    requires (400 without it) so a read through this door is attributed exactly like one through
    the MCP tool. Returns the OpenAI page's `data`: each hit carries `content[0].text`, `score`,
    and `attributes` with the `record_id` an exact read can follow."""
    url = f"{gateway_url.rstrip('/')}/v1/vector_stores/{store}/search"
    body = {"query": query, "max_num_results": int(k), "filters": dict(filters)}
    # The façade embeds the query first; under a publish the embedder answers in tens of seconds,
    # not the webhook default's 30 (measured 11 Sep 2026: every search timed out mid-publish).
    poster = http or functools.partial(post_json, timeout=SEARCH_TIMEOUT_S)
    raw = await asyncio.to_thread(poster, url, body, headers=dict(headers or {}))
    return list(json.loads(raw).get("data") or [])


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

#: Waits between attempts when the gateway is restarting: a rollout takes one to three minutes and
#: the OpenAI client's own three retries span seconds, so a run an hour of tokens in died with
#: "upstream error" on every deploy (11 Sep 2026). ~4 minutes in total, then the failure is real.
RESTART_WAITS_S = (20, 40, 60, 60, 60)


def is_transient(exc: BaseException) -> bool:
    """A failure that a gateway coming back would cure — 5xx, a dropped connection, a timeout — and
    NOT one that will still be there in four minutes (a 4xx: a quota, a refused key, a bad request).
    Looks through the wrappers a client stacks around the HTTP error."""
    seen: list[BaseException] = []
    todo = [exc]
    while todo:
        e = todo.pop()
        if any(e is s for s in seen):
            continue
        seen.append(e)
        status = getattr(e, "status_code", None)
        if isinstance(status, int):
            return status >= 500
        if type(e).__name__ in ("APIConnectionError", "APITimeoutError", "ConnectError",
                                "ReadTimeout", "RemoteProtocolError", "ConnectionError", "TimeoutError"):
            return True
        todo += [a for a in getattr(e, "args", ()) if isinstance(a, BaseException)]
        if e.__cause__ is not None:
            todo.append(e.__cause__)
    text = str(exc)
    return any(m in text for m in ("Error code: 502", "Error code: 503", "Error code: 504",
                                   "Connection error", "connection reset"))


async def survive_restart(attempt, *, waits=RESTART_WAITS_S, sleep=asyncio.sleep):
    """Run `attempt()` (a coroutine factory), retrying a TRANSIENT failure across `waits`. Anything
    else — and a transient one that outlives the waits — is raised as it was."""
    for wait in waits:
        try:
            return await attempt()
        except Exception as exc:                          # noqa: BLE001 — classified, then re-raised
            if not is_transient(exc):
                raise
            print(f"gateway: transient failure ({type(exc).__name__}: {str(exc)[:90]}) — "
                  f"retrying in {wait}s", flush=True)
            await sleep(wait)
    return await attempt()


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
                    required: Iterable[Any], required_stores: Iterable[str] = ()) -> dict:
    """Preflight, publish the graph to the run board, run it, and return the one output.

    The preflight is the part that must not be forgotten: it lists the gateway's tools and refuses
    a run whose contract is not exposed, for zero tokens, rather than dying twenty minutes in on a
    tool a version-skewed gateway no longer has. `required_stores` are the relevance stores the
    run will search, checked the same way."""
    await preflight(cfg["mcp_url"], cfg["headers"], required)
    stores = [s for s in required_stores if s]
    if stores:
        await preflight_stores(cfg.get("gateway_url") or "", cfg["headers"], stores)
    workflow = build(cfg)
    if cfg.get("run_id"):
        from lab.platform import runlog
        from lab.workloads import workflowviz
        runlog.update(cfg["run_id"], mermaid=workflowviz.mermaid(workflow))
    outputs = (await workflow.run(dict(inputs))).get_outputs()
    if not outputs:
        raise RuntimeError(f"the {what} run produced no output")
    return outputs[0]
