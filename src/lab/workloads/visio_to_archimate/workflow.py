"""Visio->ArchiMate business process as a Microsoft Agent Framework Workflow (typed graph),
agentic edition:

  ba ──▶ architect_design ──▶ store ──▶ architect_finalize ──▶ stage_import
 (reads inputs     (BA desc ->    (spec ->        (agent calls validate    (human-gated EA
  via gateway       engine spec)   art:// ref via  + render BY REF)          repository import)
  storage tools)                   semantic-mcp)

Design rationale (see [[agent-framework-tool-calling]] / CLAUDE.md): agents DO call tools, but
only with SMALL arguments — an `art://` reference — because a large nested object passed inline
as a tool argument is emitted only stochastically (AF #2747 schema-loss), while small-arg tool
calls are reliable (measured 5/5). So the Architect emits its spec as structured output, a
deterministic node stores it BY REFERENCE (through semantic-mcp, so this host holds no store
credentials), and the Architect then calls the governed gateway-MCP `semantic_validate_model` +
`archimate_render` by that ref. A deterministic render fallback guarantees the pipeline completes
even if the model skips the call on a given run. The final EA-repository write stays deterministic +
human-gated, and goes through the VENDOR-NEUTRAL port (`EATools`, gateway alias `ea_mcp`): this
workload never names ADOIT and never knows which artifacts that repository needs a human to import —
`ea_stage_import` takes the model by ref and reports back what it produced. Governed egress is
unchanged: every LLM and tool call goes through the gateway with each agent's own identity —
including the BA's reads of its inputs (storage-mcp) and the images the deterministic node fetches
for it.
"""
import asyncio
import base64
import contextlib
import json
import os
import re
from pathlib import Path

from agent_framework import Content, Message, WorkflowBuilder, WorkflowContext, executor
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from jsonschema import Draft7Validator

from lab.workloads.visio_to_archimate import agents as A
from lab.workloads.visio_to_archimate import inputs as I
from lab.workloads import gateway, ids, workflowviz  # (live run visibility: Runs board + graph)
from lab.platform import runlog
from lab.platform.contracts import ArtifactRef, EATools, SemanticTools, StorageTools
from lab.workloads.visio_to_archimate import ba_tools as BT  # (BA_MODE=tools accumulator)
from lab.workloads.visio_to_archimate import architect_tools as AT  # (ARCHITECT_MODE=tools)

HERE = Path(__file__).resolve().parent
BA_RUN_TIMEOUT = float(os.environ.get("BA_RUN_TIMEOUT", "900"))   # wall-clock guard per BA run


def _extract_json(text: str):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.S).strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        try:
            return json.loads(m.group(0)) if m else None
        except Exception:
            return None


def _schema_errors(validator, obj):
    if obj is None:
        return "not valid JSON"
    errs = sorted(validator.iter_errors(obj), key=lambda e: list(e.path))
    if not errs:
        return None
    return "; ".join(f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errs[:5])


# What the BA is told when it holds BOTH representations of one .vsdx page. The rule itself is
# stated once in prompts/ba.md + references/method.md; this is the per-run reminder that the second
# representation is actually attached, and of who wins on what.
RECONCILE_VSDX = (
    "You are ALSO given an ATTACHED IMAGE of {scope}, rendered from that .vsdx. Read "
    "BOTH representations and reconcile them: the deterministic parse wins on element identity, "
    "caption text, stencil/type_hint and native connectors; the image wins on grouping/containment "
    "(which boxes sit inside which zone or swim-lane) and on connectors the parse missed. A "
    "connector marked `recovered: \"geometry\"` was inferred from line geometry, not declared by the "
    "file — confirm it against the image, and the larger its `match_distance` the more suspect it "
    "is. Never drop a parsed element because the image did not show it clearly. Where the two "
    "genuinely disagree, keep the parse's identity and record the disagreement in openQuestions.")
# The parse covers EVERY page when no `#page` was requested, but only one page is rendered — so the
# reconciliation rule must not claim the picture shows what the BA is reading. Phase B's one-request-
# per-page split removes the asymmetry; until then the message states it.
SCOPE_SAME_PAGE = "the SAME diagram page"
SCOPE_ONE_OF_MANY = ("{label} ONLY — the parse covers every page of this workbook, so for its other "
                     "pages you have NO image and the parse is your only representation")

# OTel span name -> executor id (the graph/run-log node id). Keep in step with build_workflow's executors.
_EXECUTOR_OF_SPAN = {
    "ba-agent": "ba", "resolve-existing": "resolve_existing", "architect-design": "architect_design",
    "store-spec": "store", "architect-finalize": "architect_finalize", "stage-import": "stage_import",
}

# The resolver agent's output contract (schemas/resolve.schema.json) — gated in resolve_existing.
_RESOLVE_VALIDATOR = Draft7Validator(json.loads(
    (HERE / "schemas" / "resolve.schema.json").read_text()))


def _repair_relations(spec: dict) -> tuple[dict, list]:
    """[D] Replace ArchiMate-illegal relations with intent-preserving LEGAL ones (skill `relrepair`,
    driven by the semantic layer's exact matrix) — e.g. the LLM's `Aggregation Component->Service`
    ("this box groups these") becomes Realization, `Component->Function` Assignment. Nothing is
    dropped or reversed; every change is returned for the reviewer. Degrades to no-op if the skill
    is unavailable (the semantic validator still reports illegals)."""
    try:
        from lab.core.archimate import relrepair
        fixed, report = relrepair.repair_spec(spec)
        return fixed, [r for r in report if r.get("replaced") != r.get("original")]
    except Exception as e:  # pragma: no cover
        print(f"[warn] relation repair unavailable: {type(e).__name__}: {e}", flush=True)
        return spec, []


def _elements_of(obj):
    """Every declared element, whichever BA group it was filed under. `BT.GROUPS` is derived from
    `ba_output.schema.json`, so adding a group is a schema-only change."""
    return [e for k in BT.GROUPS for e in obj.get(k, [])]


def _normalise_provenance(obj):
    """[D] Per-element provenance gate, IN PLACE: expand the bare-string shorthand to the object
    form so the Architect and the persisted `ba_output` artifact see one shape, and name the
    elements that declared none. Provenance is what makes a later reader able to tell a parsed
    shape from something read off a picture or lifted from a document, so it is required, not
    decorative — a miss is a gate error and the BA is asked again."""
    bad: list[str] = []
    for e in _elements_of(obj):
        prov, errs = BT.normalise_provenance(e.get("provenance"))
        if errs:
            # the accumulator already computed a precise reason ("provenance.source 'visio' is not
            # one of [...]"); carry it, so the retry fixes the actual mistake, not a category
            bad.append(f"{e.get('name') or '<unnamed>'} ({errs[0]})")
        else:
            e["provenance"] = prov
    if bad:
        return f"{len(bad)} element(s) have no valid provenance: " + "; ".join(bad[:5])
    return None


def _incomplete(obj):
    """Deterministic completeness gate for the BA->Architect contract (beyond schema shape)."""
    if not obj.get("systemName") or not obj.get("summary"):
        return "missing systemName/summary"
    if not _elements_of(obj):
        return "no elements described"
    names = {e["name"] for e in _elements_of(obj)}
    dangling = [r for r in obj.get("relationships", []) if r["from"] not in names or r["to"] not in names]
    if dangling:
        return f"{len(dangling)} relationship endpoint(s) reference undeclared elements"
    return None


def _ba_gate(validator, obj):
    """[D] THE gate between the BA agent and the Architect, in one place: every element must carry
    provenance (which is also NORMALISED in place, so the shorthand and the object form become one
    shape downstream), the document must be valid against `ba_output.schema.json`, and it must be
    complete (systemName/summary, some elements, no dangling relationship endpoints). Returns an
    error string for the corrective retry, or None when the description may pass.

    Provenance goes FIRST for two reasons: the shorthand is expanded before the schema sees it (so
    the schema validates ONE shape), and `normalise_provenance` names the offending element and the
    exact field — where the schema's `oneOf` can only say "not valid under any of the given
    schemas", which a corrective retry cannot act on. `_schema_errors(validator, None)` still
    answers "not valid JSON", so a non-document needs no branch of its own."""
    return ((_normalise_provenance(obj) if isinstance(obj, dict) else None)
            or _schema_errors(validator, obj) or _incomplete(obj))


# What this workload needs the gateway to expose, derived from the CONTRACT so a rename cannot leave a
# stale literal here. Checked ONCE before any node runs (`preflight`) — see its docstring for why.
REQUIRED_TOOLS = (
    StorageTools.read_vsdx, StorageTools.read_document, StorageTools.get, StorageTools.extract_figures,
    SemanticTools.store_spec, SemanticTools.validate_model,
    EATools.render, EATools.stage_import,
)


async def preflight(cfg) -> None:
    """Refuse the run if the gateway does not expose every tool this workload needs.

    A cloud run once failed 320 s in with "tool *adoit_request_import not exposed by gateway": the
    workload was deployed from one commit and the gateway from another, and the per-call guard in
    `_call_tools_raw` only fires at the step that needs the tool — after the reading agent has run and
    spent tokens. The tool list is knowable before the first node executes, so a version mismatch is
    refused here, naming exactly what is missing.

    Resolution is by NAME SUFFIX, identical to `_call_tools_raw`: the workload is deliberately
    alias-agnostic (the gateway prefixes `<server alias>-`), so renaming an alias does not break it
    and must not fail preflight either. What DOES break it — a renamed or withdrawn tool — is caught.
    """
    await gateway.preflight(cfg["mcp_url"], cfg.get("ar_headers") or {}, REQUIRED_TOOLS)


_call_tools_raw = gateway.call_tools_raw    # the ONE gateway-MCP transport (lab.workloads.gateway)
_call_tools = gateway.call_tools


_ref_from = gateway.ref_from


_rid = ids.rid   # one relation-id formula in the repo (src/lab/workloads/ids.py), shared with the accumulators


async def _ea_search_many(headers, mcp_url, terms, scope="all", per=5, cap=60):
    """Search the EA repository for many names in one gateway MCP session; merge unique candidates by
    id. Each term -> ea_search(name_like=term) — the vendor-neutral port, so which EA tool is behind
    the gateway alias is not this workload's business. Returns (candidates, error): `error` is None on
    success, else a short description. A failed search MUST be surfaced by the caller — it must never
    look like "genuinely new" (review finding C-H3: fail loud, not open)."""
    seen, out = set(), []
    try:
        async with Client(StreamableHttpTransport(mcp_url, headers=headers)) as c:
            names = [t.name for t in await c.list_tools()]
            tool = next((n for n in names if n.endswith(EATools.search)), None)
            if not tool:
                return [], (f"{EATools.search} not exposed to this identity (grant {EATools.SERVER} to the "
                            f"team / restart the gateway)")
            for term in terms:
                if not term or len(term) < 3:
                    continue
                r = await c.call_tool(tool, {"name_like": term, "scope": scope, "limit": per})
                items = r.data if isinstance(r.data, list) else (json.loads(r.content[0].text) if r.content else [])
                for it in items or []:
                    if it.get("id") and it["id"] not in seen:
                        seen.add(it["id"]); out.append(it)
                if len(out) >= cap:
                    break
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:160]}"
        print(f"[warn] EA repository search failed: {err}", flush=True)
        return out, err
    return out, None


def _images_from(result) -> list[tuple[bytes, str, str]]:
    """(bytes, media_type, label) from a storage_get / storage_extract_figures result: the server
    returns image content blocks each followed by a text label. Images ride the gateway as MCP
    ImageContent (base64); a text-only result means the gateway flattened them — surface that."""
    out, pending = [], None
    for block in getattr(result, "content", []) or []:
        t = getattr(block, "type", "")
        if t == "image":
            if pending:
                out.append((*pending, ""))
            pending = (base64.b64decode(block.data), block.mimeType)
        elif t == "text" and pending:
            out.append((*pending, block.text))
            pending = None
    if pending:
        out.append((*pending, ""))
    return out


def _tool_results(r):
    """Map tool-name -> parsed result from an agent response (MCP results arrive as JSON strings;
    content objects are class Content with a .type of function_call / function_result)."""
    by_id, out = {}, {}
    for m in r.messages:
        for c in m.contents:
            t = getattr(c, "type", "")
            if t == "function_call":
                by_id[getattr(c, "call_id", None)] = getattr(c, "name", "") or ""
            elif t == "function_result":
                name = by_id.get(getattr(c, "call_id", None), "")
                res = getattr(c, "result", None)
                if isinstance(res, str):
                    try:
                        res = json.loads(res)
                    except Exception:
                        pass
                out[name] = res
    return out


def _pick_result(results: dict, suffix: str):
    for name, res in results.items():
        if name.endswith(suffix):
            return res
    return None


def build_workflow(cfg):
    tracer, root_ctx = cfg["tracer"], cfg["root_ctx"]
    validator = Draft7Validator(cfg["schema"])

    @contextlib.contextmanager
    def span(name):
        """One executor step: an OTel span joined to the run's root span, AND a live run-log node
        (start / done / fail + elapsed) so the review app's Runs board shows which step a run is in.
        Node ids are normalised to the executor ids (`architect-finalize` -> `architect_finalize`) so
        the board can highlight the node on the WorkflowViz graph. No run_id (a bare test) = OTel only."""
        rid = cfg.get("run_id")
        # The run-log/graph node id is the EXECUTOR id (what WorkflowViz emits); OTel span names stay
        # descriptive. One table, so a span name can never silently miss its node (review finding A-F4).
        node = _EXECUTOR_OF_SPAN.get(name, name.replace("-", "_"))
        node_cm = runlog.span_node(rid, node) if rid else contextlib.nullcontext()
        with node_cm, tracer.start_as_current_span(name, context=root_ctx) as s:
            yield s

    def architect_agent(tools=None):
        return A.make_agent("architect-agent", A.architect_instructions(), cfg["ar_cred"],
                            cfg["traceparent"], tools=tools)

    async def _render_page(diagram: str):
        """The .vsdx page as an image: `(bytes, media_type, label)`, or `(None, reason)`.

        By REF it is the governed `storage_render_vsdx` (the workload holds no store credentials);
        by PATH it is the same renderer in-process (dev). The picture is a SECOND representation,
        never the only one, so nothing here raises — but the REASON is returned and recorded rather
        than swallowed, because "this host has no LibreOffice" (expected) and "the tool is not
        granted to this team / the gateway was not restarted" (a governance fault) and "the gateway
        flattened the image blocks" (a transport regression) are three different problems that must
        not look identical after the fact. They are not raised: the tool is new, so a deployment
        that has not been restarted must still complete its runs on the parse alone."""
        try:
            if I.is_ref(diagram):
                res, = await _call_tools_raw(cfg["ba_headers"], cfg["mcp_url"],
                                             [(StorageTools.render_vsdx, {"ref": diagram})])
                imgs = _images_from(res)
                if not imgs:
                    return None, f"{StorageTools.render_vsdx} returned no image content (flattened?)"
                return imgs[0], None
            norm = I.render_page(diagram)
            return (norm, None) if norm else (None, "the page rendered to nothing readable")
        except Exception as e:
            return None, f"{type(e).__name__}: {str(e)[:160]}"

    async def _ba_message(diagram: str, reqs: list[str]) -> tuple[Message, dict]:
        """Build the BA's message: what to read (and with which tool), plus every image attached
        inline — the diagram itself when it is an image, and the figures embedded in each
        requirements document. Refs are fetched THROUGH THE GATEWAY (storage_get /
        storage_extract_figures, BA identity); paths are parsed locally (dev)."""
        lines, contents, attrs = [], [], {"ba.images": 0}
        dk = I.kind(diagram)
        if dk == "image":
            lines.append("The system diagram is the ATTACHED IMAGE. Read every box, its label, "
                         "every arrow and its label before classifying anything.")
            if I.is_ref(diagram):
                res, = await _call_tools_raw(cfg["ba_headers"], cfg["mcp_url"], [(StorageTools.get, {"ref": diagram})])
                imgs = _images_from(res)
                if not imgs:
                    raise RuntimeError(f"{StorageTools.get} returned no image content for {diagram}")
                contents += [Content.from_data(d, mt) for d, mt, _ in imgs]
            else:
                contents.append(Content.from_data(I.load(diagram), I.media_type(diagram)))
        else:
            tool = StorageTools.read_vsdx if I.is_ref(diagram) else "read_vsdx"
            lines.append(f"The Visio diagram to analyse is: {diagram}\nCall {tool} with exactly that source.")
            # SECOND representation of the SAME page: the rendered picture. Optional by design —
            # it needs LibreOffice + a rasteriser on the storage-mcp host (or this one, for a dev
            # path). When that is missing the run continues on the parse alone and says so.
            page, reason = await _render_page(diagram)
            attrs["ba.rendered"] = bool(page)
            if page:
                data, mtype, label = page
                one_page = bool(I.split_page(diagram)[1])
                scope = SCOPE_SAME_PAGE if one_page else SCOPE_ONE_OF_MANY.format(
                    label=label or "one page of it")
                lines.append(RECONCILE_VSDX.format(scope=scope))
                contents.append(Content.from_data(data, mtype))
            else:
                attrs["ba.render_error"] = reason or ""
                print(f"[warn] no image representation for {diagram}: {reason}", flush=True)
                lines.append("No rendered image of this diagram is available, so the structured "
                             "parse is your ONLY representation of it. Read grouping and containment "
                             "from the parse's own evidence, and record anything the parse cannot "
                             "settle — including connectors you can tell are missing — in "
                             "openQuestions.")
        for req in reqs:
            tool = StorageTools.read_document if I.is_ref(req) else "read_document"
            lines.append(f"A requirements document is provided: {req}\n"
                         f"Call {tool} with exactly that source and use its content.")
            # figures embedded in the document (diagrams, screenshots) carry meaning the text does
            # not: extracted deterministically (server-side for refs) and attached for the BA's vision
            if I.is_ref(req):
                res, = await _call_tools_raw(cfg["ba_headers"], cfg["mcp_url"],
                                             [(StorageTools.extract_figures, {"ref": req})])
                figs = [(label, d, mt) for d, mt, label in _images_from(res)]
            else:
                figs = I.extract_images(req)
            for label, data, mtype in figs:
                lines.append(f"Attached: {label or 'embedded figure'} — read it like a diagram or screenshot.")
                contents.append(Content.from_data(data, mtype))
        lines.append("Then produce the JSON system description.")
        attrs["ba.images"] = len(contents)
        return Message("user", [Content.from_text("\n".join(lines)), *contents]), attrs

    async def _run_ba(agent, msg):
        r = await asyncio.wait_for(agent.run(msg), timeout=BA_RUN_TIMEOUT)
        obj = _extract_json(r.text)
        err = _ba_gate(validator, obj)
        if err:
            # One corrective retry. It MUST re-send the original contents (the diagram image +
            # figures): the client is stateless (store=False), so a bare text correction would run
            # in a fresh conversation blind to the diagram — verified it then also returns "no
            # elements". "no JSON" almost always means the previous turn spent its whole output
            # budget reasoning (finish=incomplete); tell it to emit the JSON FIRST.
            note = (f"Your previous answer was rejected: {err}. Re-read the attached diagram and "
                    f"documents above and resend ONLY the corrected JSON system description. Output "
                    f"the JSON object FIRST, before any reasoning, so it is not truncated.")
            retry = Message("user", [*msg.contents, Content.from_text(note)])
            r = await asyncio.wait_for(agent.run(retry), timeout=BA_RUN_TIMEOUT)
            obj = _extract_json(r.text)
            err = _ba_gate(validator, obj)
            if err:
                raise RuntimeError(f"BA output rejected (incomplete after retry): {err}")
        return obj

    async def _run_ba_tools(agent, msg, acc):
        """BA_MODE=tools: the model BUILDS its output through small, per-call-validated accumulator
        tools (ba_tools.py); the document is assembled by code and passes the SAME gate as the JSON
        path. The retry keeps the accumulator (the model adds what is missing, it does not start over)
        and re-sends the diagram contents (stateless client)."""
        await asyncio.wait_for(agent.run(msg), timeout=BA_RUN_TIMEOUT)
        acc.last_finish or acc.finish()
        obj = acc.result()
        err = _ba_gate(validator, obj)
        if err:
            note = (f"Your description is incomplete: {err}. Re-read the attached diagram and documents "
                    f"above; add what is missing with add_elements / add_relationships (fix any rejected "
                    f"items), then call finish() again and reply 'done'.")
            retry = Message("user", [*msg.contents, Content.from_text(note)])
            await asyncio.wait_for(agent.run(retry), timeout=BA_RUN_TIMEOUT)
            acc.last_finish or acc.finish()
            obj = acc.result()
            err = _ba_gate(validator, obj)
            if err:
                raise RuntimeError(f"BA output rejected (incomplete after retry): {err}")
        return obj

    @executor(id="ba")
    async def ba(inputs: dict, ctx: WorkflowContext[dict]) -> None:
        """inputs = {"diagram": <path|art://>, "requirements": [<path|art://>, ...]}.
        Refs -> the BA's tools are the gateway's storage_mcp read tools and the node fetches images
        through the gateway; paths -> local function tools (dev). Either way kimi-k3 reads images
        inline (vision via the gateway, verified) — no parse, no extra model call."""
        with span("ba-agent") as s:
            diagram, reqs = inputs["diagram"], list(inputs.get("requirements") or [])
            by_ref = I.is_ref(diagram) or any(I.is_ref(r) for r in reqs)
            msg, attrs = await _ba_message(diagram, reqs)
            # BA_MODE=tools -> the model builds its output through validated accumulator tools
            # (structured + deterministic by construction); default json -> one-shot JSON + gate.
            use_tools = os.environ.get("BA_MODE", "json").strip().lower() == "tools"
            acc = BT.BAAccumulator() if use_tools else None
            build_tools = BT.make_tools(acc) if use_tools else []
            instr = A.ba_instructions() + (A.ba_tools_addendum() if use_tools else "")
            s.set_attributes({"ba.diagram_kind": I.kind(diagram), "ba.requirements": len(reqs),
                              "ba.by_ref": by_ref, "ba.mode": "tools" if use_tools else "json", **attrs})
            if by_ref:
                mcp = A.ba_tools(cfg["ba_headers"])          # governed reads with the BA's identity
                async with mcp:
                    agent = A.make_agent("ba-agent", instr, cfg["ba_cred"],
                                         cfg["traceparent"], tools=[mcp, *build_tools])
                    obj = await (_run_ba_tools(agent, msg, acc) if use_tools else _run_ba(agent, msg))
            else:
                agent = A.make_agent("ba-agent", instr, cfg["ba_cred"], cfg["traceparent"],
                                     tools=[A.read_vsdx_tool(), A.read_document_tool(), *build_tools])
                obj = await (_run_ba_tools(agent, msg, acc) if use_tools else _run_ba(agent, msg))
            s.set_attribute("ba.elements", len(_elements_of(obj)))
            # [D] persist the gate-validated BA output by reference: per-element layer/provenance stay
            # auditable after the run and the approval can link to them (never a raw-agent artifact —
            # this is written AFTER the jsonschema gate in _run_ba).
            # A workload holds NO store credentials: persist through the gateway (semantic_store_spec
            # accepts any JSON document), with the identity that holds the MCP grants.
            res, = await _call_tools(cfg["ar_headers"], cfg["mcp_url"],
                                     [(SemanticTools.store_spec, {"spec": obj, "name": "visio-import.ba_output.json"})])
            ba_ref = _ref_from(res)
            s.set_attribute("ba.output_ref", ba_ref)
            await ctx.send_message({"inputs": inputs, "ba_output": obj, "ba_output_ref": ba_ref})

    @executor(id="resolve_existing")
    async def resolve_existing(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Existing-architecture-aware step: search the EA repository for objects related to the
        described system, then decide NEW vs UPDATE and match BA elements to existing repository ids
        (so the Architect reuses them instead of duplicating). Degrades to NEW if it is unreachable."""
        with span("resolve-existing") as s:
            ba = state["ba_output"]
            names = [ba.get("systemName", "")] + [e.get("name", "") for e in _elements_of(ba)]
            # Tool nodes use the ARCHITECT identity (it holds the EA/semantic grants) — review C-H3.
            cands, search_err = await _ea_search_many(cfg["ar_headers"], cfg["mcp_url"], names[:16])
            s.set_attributes({"resolve.candidates": len(cands), "resolve.search_error": search_err or ""})
            if not cands:
                existing = {"decision": "NEW", "domain": ba.get("systemName", "Unassigned"),
                            "base_model": None, "matched": {}, "candidates": [],
                            "search_failed": bool(search_err),
                            "rationale": (f"EA repository search FAILED ({search_err}) — NEW is UNVERIFIED, "
                                          f"review for duplicates" if search_err
                                          else "no related objects found in the EA repository")}
            else:
                agent = A.make_agent("resolve-agent", A.resolve_instructions(), cfg["ar_cred"], cfg["traceparent"])
                prompt = ("BA system description:\n" + json.dumps(ba) +
                          "\n\nExisting EA repository candidates:\n" + json.dumps(cands))
                r = await asyncio.wait_for(agent.run(prompt), timeout=BA_RUN_TIMEOUT)
                existing = _extract_json(r.text) or {}
                # [D] gate the resolver's structured output on its schema (review C-M6). An agent step
                # never flows un-validated onward; here the safe fallback is NEW with the rejection recorded.
                gate = _schema_errors(_RESOLVE_VALIDATOR, existing) if existing else "no JSON"
                if gate:
                    s.set_attribute("resolve.gate_errors", str(gate)[:300])
                    print(f"[warn] resolver output rejected by schema gate: {gate} — falling back to NEW", flush=True)
                    existing = {"decision": "NEW", "domain": ba.get("systemName", "Unassigned"),
                                "base_model": None, "matched": {},
                                "rationale": f"resolver output rejected by the schema gate: {str(gate)[:200]}"}
                existing.setdefault("decision", "NEW")
                existing.setdefault("domain", ba.get("systemName", "Unassigned"))
                existing.setdefault("matched", {})
                existing["candidates"] = cands
                existing["search_failed"] = bool(search_err)
            s.set_attributes({"resolve.decision": existing["decision"], "resolve.domain": existing["domain"],
                              "resolve.matched": len(existing.get("matched", {}))})
            state["existing"] = existing
            await ctx.send_message(state)

    @executor(id="architect_design")
    async def architect_design(state: dict, ctx: WorkflowContext[dict]) -> None:
        with span("architect-design") as s:
            ex = state.get("existing") or {}
            # ARCHITECT_MODE=tools -> the model BUILDS the spec through accumulator tools with per-call
            # ArchiMate legality (illegal relations rejected at emission); default json -> one-shot spec.
            arch_tools = os.environ.get("ARCHITECT_MODE", "json").strip().lower() == "tools"
            acc = AT.ArchitectAccumulator() if arch_tools else None
            if arch_tools:
                agent = A.make_agent("architect-agent",
                                     A.architect_instructions() + A.architect_tools_addendum(),
                                     cfg["ar_cred"], cfg["traceparent"], tools=AT.make_tools(acc))
            else:
                agent = architect_agent()
            s.set_attribute("architect.mode", "tools" if arch_tools else "json")
            ctx_block = ""
            if ex.get("matched") or ex.get("decision") == "UPDATE":
                ctx_block = ("\n\nEXISTING ARCHITECTURE (from the EA repository). Decision: "
                             f"{ex.get('decision')} in domain '{ex.get('domain')}'. For every element below "
                             "that is the SAME as one you emit, use its adoit_id VERBATIM as the element `id` "
                             "(do not slug a new one) so it updates in place; slug fresh ids only for genuinely "
                             "new elements. Put every element's `folder` = the domain.\n"
                             + json.dumps(ex.get("matched", {})))
            prompt = "BA system description:\n" + json.dumps(state["ba_output"]) + ctx_block
            if arch_tools:
                await agent.run(prompt)
                acc.last_finish or acc.finish()
                spec = acc.result()
                if not spec.get("elements"):
                    await agent.run("Your model has no elements, or finish() reported errors. Add what is "
                                    "missing with the tools, call finish() again, and reply 'done'.")
                    acc.last_finish or acc.finish()
                    spec = acc.result()
                if not spec.get("elements"):
                    raise RuntimeError("Architect (tools mode) produced no spec")
            else:
                r = await agent.run(prompt)
                spec = _extract_json(r.text)
                if not spec or "elements" not in spec:
                    r = await agent.run("That was not a valid engine spec. Resend ONLY the JSON object "
                                        "with keys name, id, elements[], relations[].")
                    spec = _extract_json(r.text)
                if not spec or "elements" not in spec:
                    raise RuntimeError(f"Architect produced no spec: {(r.text or '')[:160]!r}")
            # deterministic guarantees the model can't be relied on for: stable relation ids, and the
            # domain folder on every element (drives ADOIT organisation + reuse regardless of the LLM).
            domain = ex.get("domain")
            for e in spec.get("elements", []):
                if domain and not e.get("folder"):
                    e["folder"] = domain
            for rel in spec.get("relations", []):
                rel.setdefault("id", _rid(rel.get("src"), rel.get("type"), rel.get("tgt")))
            # [D] legalise relations against the ArchiMate matrix BEFORE the spec is stored/rendered
            spec, repairs = _repair_relations(spec)
            state["repairs"] = repairs
            s.set_attributes({"spec.relation_repairs": len(repairs),
                              "spec.elements": len(spec.get("elements", [])),
                              "spec.reused_ids": sum(1 for e in spec.get("elements", [])
                                                     if e.get("id") in {m.get("adoit_id") for m in ex.get("matched", {}).values()})})
            state["spec"] = spec
            await ctx.send_message(state)

    @executor(id="store")
    async def store(state: dict, ctx: WorkflowContext[dict]) -> None:
        # By reference through semantic-mcp (credential-free, granted to every team): this host
        # keeps no artifact-store credentials. Inline spec is fine here — deterministic code, not
        # a model, emits the argument (AF #2747 only bites LLM-emitted nested args).
        with span("store-spec") as s:
            spec = {**state["spec"], "standard_views": True}   # engine lays out the view catalogue
            res, = await _call_tools(cfg["ar_headers"], cfg["mcp_url"],
                                     [(SemanticTools.store_spec, {"spec": spec, "name": "visio-import.spec.json"})])
            ref = _ref_from(res)
            s.set_attribute("spec.ref", ref)
            state["spec"], state["spec_ref"] = spec, ref
            await ctx.send_message(state)

    @executor(id="architect_finalize")
    async def architect_finalize(state: dict, ctx: WorkflowContext[dict]) -> None:
        with span("architect-finalize") as s:
            ref = state["spec_ref"]
            mcp = A.architect_tools(cfg["ar_headers"])           # gateway MCP: validate + render only
            async with mcp:
                agent = architect_agent(tools=[mcp])
                prompt = (f"The finished ArchiMate spec is stored at reference '{ref}'.\n"
                          f"1) Call {SemanticTools.gateway(SemanticTools.validate_model)} with "
                          f"{{\"spec_ref\": \"{ref}\"}} to check legality.\n"
                          f"2) Call {EATools.gateway(EATools.render)} with "
                          f"{{\"spec_ref\": \"{ref}\", \"basename\": \"visio-import\"}} to render it.\n"
                          f"Then reply 'done'.")
                r = await agent.run(prompt)
                res = _tool_results(r)
            sem = _pick_result(res, SemanticTools.validate_model)
            render = _pick_result(res, EATools.render)
            # deterministic fallbacks — guarantee the pipeline completes even if the model skipped a call
            if not (isinstance(sem, dict) and "illegal" in sem):
                sem, = await _call_tools(cfg["ar_headers"], cfg["mcp_url"],
                                         [(SemanticTools.validate_model, {"spec_ref": ref})])
            if not (isinstance(render, dict) and render.get("xml_ref")):
                render, = await _call_tools(cfg["ar_headers"], cfg["mcp_url"],
                                            [(EATools.render, {"spec_ref": ref, "basename": "visio-import"})])
            s.set_attribute("agent.called_render", bool(_pick_result(res, EATools.render)))
            s.set_attribute("semantic.illegal", len(sem.get("illegal", [])))
            state["semantic"] = {"illegal": sem.get("illegal", []), "warnings": sem.get("warnings", [])}
            state["xml_ref"], state["svg_refs"] = render["xml_ref"], render.get("svg_refs", {})
            state["views"] = len(render.get("views", {}))
            await ctx.send_message(state)

    @executor(id="stage_import")
    async def stage_import(state: dict, ctx: WorkflowContext[dict]) -> None:
        with span("stage-import") as s:
            spec = state["spec"]
            ex = state.get("existing") or {}
            matched = ex.get("matched", {})
            summary = {"elements": len(spec.get("elements", [])), "relations": len(spec.get("relations", [])),
                       "views": state["views"], "semantic_illegal": len(state["semantic"]["illegal"]),
                       "semantic_warnings": len(state["semantic"]["warnings"]),
                       # existing-architecture resolution — the reviewer approves as update vs new
                       "decision": ex.get("decision", "NEW"), "domain": ex.get("domain"),
                       "base_model": ex.get("base_model"), "matched_existing": len(matched),
                       "new_elements": max(0, len(spec.get("elements", [])) - len(matched)),
                       "resolve_rationale": ex.get("rationale"),
                       "ba_output_ref": state.get("ba_output_ref"),
                       # a failed repository search means "NEW" is unverified — the reviewer must know (C-H3)
                       "search_failed": bool(ex.get("search_failed", False)),
                       # deterministic relation repairs (illegal -> legal), shown to the reviewer
                       "relation_repairs": len(state.get("repairs", [])),
                       "repair_notes": [r.get("reason", "") for r in state.get("repairs", [])][:12]}
            # ONE call to the EA-repository port: it takes the model BY REF, produces whatever THIS
            # repository needs a human to import (this workload must not know what that is — a
            # spreadsheet here, nothing at all on a write-capable tenant) and stages it for approval.
            # The already-rendered views ride along so the repository need not render them again.
            req, = await _call_tools(cfg["ar_headers"], cfg["mcp_url"], [
                (EATools.stage_import,
                 {"spec_ref": state["spec_ref"], "xml_ref": state["xml_ref"], "svg_refs": state["svg_refs"],
                  "model_name": spec.get("name", "Visio Import"), "summary": summary,
                  "requester": "architect-agent"})])
            artifacts = req.get("artifacts") or {}          # the staged MODEL (xml + previews)
            # [] from a repository that writes over its own API; opaque {ref,label,note} entries otherwise
            to_import = req.get("import_artifacts") or []
            s.set_attributes({"approval.request_id": req["request_id"],
                              "import.artifacts": len(to_import)})
            await ctx.yield_output({
                "request_id": req["request_id"], "status": req["status"],
                "review_app": req.get("review_app"),
                "xml_ref": artifacts.get("xml_ref") or state["xml_ref"],
                "svg_refs": artifacts.get("svg_refs") or state["svg_refs"],
                "import_artifacts": to_import,
                "summary": summary, "spec": spec, "semantic": state["semantic"]})

    return WorkflowBuilder(start_executor=ba).add_chain(
        [ba, resolve_existing, architect_design, store, architect_finalize, stage_import]).build()


def make_cfg(*, ba_cred: str, ar_cred: str, traceparent: dict, schema: dict, tracer, root_ctx,
             mcp_url: str | None = None, run_id: str | None = None) -> dict:
    """The workflow's configuration contract, built in ONE place for every host (CLI/consumer via
    host.run_once, DevUI via devui_entry) so it cannot drift — review A-F12 found DevUI's hand-built copy
    lacked `run_id` and both carried a dead `outdir`. Keys the executors read:
      ba_cred / ar_cred      each agent's own credential (spend attributes per key)
      traceparent            W3C headers for this run — the agents' LLM calls join the trace
      ba_headers / ar_headers  Bearer + traceparent: the BA reads inputs through storage-mcp with ITS
                             identity; tool nodes + the Architect's tools use the Architect's identity
                             (its key holds the ADOIT/semantic grants)
      mcp_url                the gateway's MCP endpoint (default: config.GATEWAY_MCP_URL)
      schema                 the BA output contract (jsonschema)
      tracer / root_ctx      OTel tracer + the run's root span context (node spans join it)
      run_id                 run-log key for the review app's Runs board (the trace id in host.run_once);
                             None = OTel only. DevUI builds cfg once per SESSION and sets this PER RUN
                             (`devui_entry.instrument_runs`) — the executors read it lazily, once per node,
                             so a DevUI run is a first-class row on the board like any other."""
    from lab.platform import config
    return {
        "ba_cred": ba_cred, "ar_cred": ar_cred,
        "traceparent": dict(traceparent),
        "ba_headers": {"Authorization": f"Bearer {ba_cred}", **traceparent},
        "ar_headers": {"Authorization": f"Bearer {ar_cred}", **traceparent},
        "mcp_url": mcp_url or config.GATEWAY_MCP_URL,
        "schema": schema,
        "tracer": tracer, "root_ctx": root_ctx,
        "run_id": run_id,
    }


async def run_workflow(cfg, inputs):
    """inputs: {"diagram": <path|art://>, "requirements": [...]} — a bare str is a diagram only."""
    if not isinstance(inputs, dict):
        inputs = {"diagram": inputs, "requirements": []}
    await preflight(cfg)          # a version mismatch must cost 0 tokens, not a whole BA turn
    wf = build_workflow(cfg)
    rid = cfg.get("run_id")
    if rid:        # live Runs board: the graph (WorkflowViz Mermaid) whose node ids the run-log reports against
        runlog.update(rid, mermaid=workflowviz.mermaid(wf) or "")
    result = await wf.run(inputs)
    outs = result.get_outputs()
    if not outs:
        raise RuntimeError("workflow produced no output")
    return outs[0]
