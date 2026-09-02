"""Visio->ArchiMate business process as a Microsoft Agent Framework Workflow (typed graph),
agentic edition:

  ba ──▶ architect_design ──▶ store ──▶ architect_finalize ──▶ stage_import
 (reads inputs     (BA desc ->    (spec ->        (agent calls validate    (human-gated
  via gateway       engine spec)   art:// ref via  + render BY REF)          ADOIT import)
  storage tools)                   semantic-mcp)

Design rationale (see [[agent-framework-tool-calling]] / CLAUDE.md): agents DO call tools, but
only with SMALL arguments — an `art://` reference — because a large nested object passed inline
as a tool argument is emitted only stochastically (AF #2747 schema-loss), while small-arg tool
calls are reliable (measured 5/5). So the Architect emits its spec as structured output, a
deterministic node stores it BY REFERENCE (through semantic-mcp, so this host holds no store
credentials), and the Architect then calls the governed gateway-MCP `semantic_validate_model` +
`archimate_render` by that ref. A deterministic render fallback guarantees the pipeline completes
even if the model skips the call on a given run. The final ADOIT write stays deterministic +
human-gated. Governed egress is unchanged: every LLM and tool call goes through the gateway with
each agent's own identity — including the BA's reads of its inputs (storage-mcp) and the images
the deterministic node fetches for it.
"""
import asyncio
import base64
import json
import os
import re
import sys
from pathlib import Path

from agent_framework import Content, Message, WorkflowBuilder, WorkflowContext, executor
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from jsonschema import Draft7Validator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from processes.visio_to_archimate import agents as A  # noqa: E402
from processes.visio_to_archimate import inputs as I  # noqa: E402

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


def _incomplete(obj):
    """Deterministic completeness gate for the BA->Architect contract (beyond schema shape)."""
    if not obj.get("systemName") or not obj.get("summary"):
        return "missing systemName/summary"
    n = sum(len(obj.get(k, [])) for k in ("actors", "components", "data", "behaviors"))
    if n == 0:
        return "no elements described"
    names = {e["name"] for k in ("actors", "components", "data", "behaviors") for e in obj.get(k, [])}
    dangling = [r for r in obj.get("relationships", []) if r["from"] not in names or r["to"] not in names]
    if dangling:
        return f"{len(dangling)} relationship endpoint(s) reference undeclared elements"
    return None


async def _call_tools_raw(headers, mcp_url, calls):
    """Call gateway-MCP tools by name suffix; returns the raw fastmcp results (keeps `.content`,
    which is where image blocks live — `.data` is None for image results)."""
    async with Client(StreamableHttpTransport(mcp_url, headers=headers)) as c:
        names = [t.name for t in await c.list_tools()]

        def pick(suffix):
            m = [n for n in names if n.endswith(suffix)]
            if not m:
                raise RuntimeError(f"tool *{suffix} not exposed by gateway ({names})")
            return m[0]

        return [await c.call_tool(pick(sfx), args) for sfx, args in calls]


async def _call_tools(headers, mcp_url, calls):
    return [r.data for r in await _call_tools_raw(headers, mcp_url, calls)]


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

    def span(name):
        return tracer.start_as_current_span(name, context=root_ctx)

    def architect_agent(tools=None):
        return A.make_agent("architect-agent", A.architect_instructions(), cfg["ar_cred"],
                            cfg["traceparent"], tools=tools)

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
                res, = await _call_tools_raw(cfg["ba_headers"], cfg["mcp_url"], [("storage_get", {"ref": diagram})])
                imgs = _images_from(res)
                if not imgs:
                    raise RuntimeError(f"storage_get returned no image content for {diagram}")
                contents += [Content.from_data(d, mt) for d, mt, _ in imgs]
            else:
                contents.append(Content.from_data(I.load(diagram), I.media_type(diagram)))
        else:
            tool = "storage_read_vsdx" if I.is_ref(diagram) else "read_vsdx"
            lines.append(f"The Visio diagram to analyse is: {diagram}\nCall {tool} with exactly that source.")
        for req in reqs:
            tool = "storage_read_document" if I.is_ref(req) else "read_document"
            lines.append(f"A requirements document is provided: {req}\n"
                         f"Call {tool} with exactly that source and use its content.")
            # figures embedded in the document (diagrams, screenshots) carry meaning the text does
            # not: extracted deterministically (server-side for refs) and attached for the BA's vision
            if I.is_ref(req):
                res, = await _call_tools_raw(cfg["ba_headers"], cfg["mcp_url"],
                                             [("storage_extract_figures", {"ref": req})])
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
        err = _schema_errors(validator, obj) or (_incomplete(obj) if obj else "no JSON")
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
            err = _schema_errors(validator, obj) or (_incomplete(obj) if obj else "no JSON")
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
            s.set_attributes({"ba.diagram_kind": I.kind(diagram), "ba.requirements": len(reqs),
                              "ba.by_ref": by_ref, **attrs})
            if by_ref:
                mcp = A.ba_tools(cfg["ba_headers"])          # governed reads with the BA's identity
                async with mcp:
                    agent = A.make_agent("ba-agent", A.ba_instructions(), cfg["ba_cred"],
                                         cfg["traceparent"], tools=[mcp])
                    obj = await _run_ba(agent, msg)
            else:
                agent = A.make_agent("ba-agent", A.ba_instructions(), cfg["ba_cred"],
                                     cfg["traceparent"], tools=[A.read_vsdx_tool(), A.read_document_tool()])
                obj = await _run_ba(agent, msg)
            s.set_attribute("ba.elements",
                            sum(len(obj.get(k, [])) for k in ("actors", "components", "data", "behaviors")))
            await ctx.send_message({"path": diagram, "inputs": inputs, "ba_output": obj})

    @executor(id="architect_design")
    async def architect_design(state: dict, ctx: WorkflowContext[dict]) -> None:
        with span("architect-design") as s:
            agent = architect_agent()
            r = await agent.run("BA system description:\n" + json.dumps(state["ba_output"]))
            spec = _extract_json(r.text)
            if not spec or "elements" not in spec:
                r = await agent.run("That was not a valid engine spec. Resend ONLY the JSON object "
                                    "with keys name, id, elements[], relations[].")
                spec = _extract_json(r.text)
            if not spec or "elements" not in spec:
                raise RuntimeError(f"Architect produced no spec: {(r.text or '')[:160]!r}")
            s.set_attribute("spec.elements", len(spec.get("elements", [])))
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
                                     [("semantic_store_spec", {"spec": spec, "name": "visio-import.spec.json"})])
            ref = res["spec_ref"] if isinstance(res, dict) else json.loads(res)["spec_ref"]
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
                          f"1) Call semantic_mcp-semantic_validate_model with {{\"spec_ref\": \"{ref}\"}} "
                          f"to check legality.\n"
                          f"2) Call adoit_mcp-archimate_render with "
                          f"{{\"spec_ref\": \"{ref}\", \"basename\": \"visio-import\"}} to render it.\n"
                          f"Then reply 'done'.")
                r = await agent.run(prompt)
                res = _tool_results(r)
            sem = _pick_result(res, "semantic_validate_model")
            render = _pick_result(res, "archimate_render")
            # deterministic fallbacks — guarantee the pipeline completes even if the model skipped a call
            if not (isinstance(sem, dict) and "illegal" in sem):
                sem, = await _call_tools(cfg["ar_headers"], cfg["mcp_url"],
                                         [("semantic_validate_model", {"spec_ref": ref})])
            if not (isinstance(render, dict) and render.get("xml_ref")):
                render, = await _call_tools(cfg["ar_headers"], cfg["mcp_url"],
                                            [("archimate_render", {"spec_ref": ref, "basename": "visio-import"})])
            s.set_attribute("agent.called_render", bool(_pick_result(res, "archimate_render")))
            s.set_attribute("semantic.illegal", len(sem.get("illegal", [])))
            state["semantic"] = {"illegal": sem.get("illegal", []), "warnings": sem.get("warnings", [])}
            state["xml_ref"], state["svg_refs"] = render["xml_ref"], render.get("svg_refs", [])
            state["views"] = len(render.get("views", {}))
            await ctx.send_message(state)

    @executor(id="stage_import")
    async def stage_import(state: dict, ctx: WorkflowContext[dict]) -> None:
        with span("stage-import") as s:
            spec = state["spec"]
            summary = {"elements": len(spec.get("elements", [])), "relations": len(spec.get("relations", [])),
                       "views": state["views"], "semantic_illegal": len(state["semantic"]["illegal"]),
                       "semantic_warnings": len(state["semantic"]["warnings"])}
            req, = await _call_tools(cfg["ar_headers"], cfg["mcp_url"], [
                ("adoit_request_import",
                 {"xml_ref": state["xml_ref"], "svg_refs": state["svg_refs"],
                  "model_name": spec.get("name", "Visio Import"), "summary": summary,
                  "requester": "architect-agent"})])
            s.set_attribute("approval.request_id", req["request_id"])
            await ctx.yield_output({
                "request_id": req["request_id"], "status": req["status"],
                "review_app": req.get("review_app"), "xml_ref": state["xml_ref"],
                "svg_refs": state["svg_refs"], "summary": summary, "spec": spec,
                "semantic": state["semantic"]})

    return WorkflowBuilder(start_executor=ba).add_chain(
        [ba, architect_design, store, architect_finalize, stage_import]).build()


async def run_workflow(cfg, inputs):
    """inputs: {"diagram": <path|art://>, "requirements": [...]} — a bare str is a diagram only."""
    if not isinstance(inputs, dict):
        inputs = {"diagram": inputs, "requirements": []}
    wf = build_workflow(cfg)
    result = await wf.run(inputs)
    outs = result.get_outputs()
    if not outs:
        raise RuntimeError("workflow produced no output")
    return outs[0]
