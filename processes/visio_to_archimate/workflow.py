"""Visio->ArchiMate business process as a Microsoft Agent Framework Workflow (typed graph),
agentic edition:

  ba ──▶ architect_design ──▶ store ──▶ architect_finalize ──▶ stage_import
 (reads Visio     (BA desc ->    (spec+views ->  (agent calls validate    (human-gated
  via read_vsdx    engine spec)   art:// ref)     + render BY REF)          ADOIT import)
  TOOL)

Design rationale (see [[agent-framework-tool-calling]] / CLAUDE.md): agents DO call tools, but
only with SMALL arguments — a file path or an `art://` spec reference — because a large nested
object passed inline as a tool argument is emitted only stochastically (AF #2747 schema-loss),
while small-arg tool calls are reliable (measured 5/5). So the Architect emits its spec as
structured output, a deterministic node stores it (getting a short `spec_ref`), and the Architect
then calls the governed gateway-MCP `semantic_validate_model` + `archimate_render` by that ref.
A deterministic render fallback guarantees the pipeline completes even if the model skips the call
on a given run. The final ADOIT write stays deterministic + human-gated. Governed egress is
unchanged: every LLM and tool call goes through the gateway with each agent's own identity.
"""
import json
import re
import sys
from pathlib import Path

from agent_framework import WorkflowBuilder, WorkflowContext, executor
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from jsonschema import Draft7Validator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import asyncio, os  # noqa: E402
from agent_framework import Content, Message  # noqa: E402  (inline image content for the BA)
BA_RUN_TIMEOUT = float(os.environ.get("BA_RUN_TIMEOUT", "900"))   # wall-clock guard per BA run
from processes.visio_to_archimate import inputs as I  # noqa: E402
from processes.visio_to_archimate import agents as A  # noqa: E402
from shared import artifacts  # noqa: E402


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


async def _call_tools(headers, mcp_url, calls):
    async with Client(StreamableHttpTransport(mcp_url, headers=headers)) as c:
        names = [t.name for t in await c.list_tools()]

        def pick(suffix):
            m = [n for n in names if n.endswith(suffix)]
            if not m:
                raise RuntimeError(f"tool *{suffix} not exposed by gateway ({names})")
            return m[0]

        return [(await c.call_tool(pick(sfx), args)).data for sfx, args in calls]


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

    def ba_agent():
        return A.make_agent("ba-agent", A.ba_instructions(), cfg["ba_cred"],
                            cfg["traceparent"], tools=[A.read_vsdx_tool(), A.read_document_tool()])

    def architect_agent(tools=None):
        return A.make_agent("architect-agent", A.architect_instructions(), cfg["ar_cred"],
                            cfg["traceparent"], tools=tools)

    @executor(id="ba")
    async def ba(inputs: dict, ctx: WorkflowContext[dict]) -> None:
        """inputs = {"diagram": <path|art://>, "requirements": [<path|art://>, ...]}.
        The diagram is a .vsdx (the BA reads it with the read_vsdx tool) or an IMAGE, which is
        attached inline to the message — kimi-k3 has vision via the gateway (verified) — so no
        parse and no extra model call. Requirements documents are read with the read_document tool."""
        with span("ba-agent") as s:
            agent = ba_agent()
            diagram, reqs = inputs["diagram"], list(inputs.get("requirements") or [])
            lines, contents = [], []
            if I.kind(diagram) == "image":
                lines.append("The system diagram is the ATTACHED IMAGE. Read every box, its label, "
                             "every arrow and its label before classifying anything.")
                contents.append(Content.from_data(I.load(diagram), I.media_type(diagram)))
            else:
                lines.append(f"The Visio diagram to analyse is: {diagram}\n"
                             f"Call read_vsdx with exactly that source.")
            for req in reqs:
                lines.append(f"A requirements document is provided: {req}\n"
                             f"Call read_document with exactly that source and use its content.")
                # figures embedded in the document (diagrams, screenshots) carry meaning the text
                # does not: extract them deterministically and attach them for the BA's vision.
                for label, data, mtype in I.extract_images(req):
                    lines.append(f"Attached: {label} — read it like a diagram or screenshot.")
                    contents.append(Content.from_data(data, mtype))
            lines.append("Then produce the JSON system description.")
            msg = Message("user", [Content.from_text("\n".join(lines)), *contents])
            s.set_attribute("ba.diagram_kind", I.kind(diagram))
            s.set_attribute("ba.requirements", len(reqs))
            r = await asyncio.wait_for(agent.run(msg), timeout=BA_RUN_TIMEOUT)
            obj = _extract_json(r.text)
            err = _schema_errors(validator, obj) or (_incomplete(obj) if obj else "no JSON")
            if err:                                  # one corrective retry, then hard reject
                r = await asyncio.wait_for(
                    agent.run(f"Your description was rejected as incomplete/invalid: {err}\n"
                              f"Fix exactly that and resend the full corrected JSON only."),
                    timeout=BA_RUN_TIMEOUT)
                obj = _extract_json(r.text)
                err = _schema_errors(validator, obj) or (_incomplete(obj) if obj else "no JSON")
                if err:
                    raise RuntimeError(f"BA output rejected (incomplete after retry): {err}")
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
        with span("store-spec"):
            spec = {**state["spec"], "standard_views": True}   # engine lays out the view catalogue
            ref = artifacts.store().put("visio-import.spec.json",
                                        json.dumps(spec).encode(), "application/json")
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
