"""The Visio->ArchiMate business process as a Microsoft Agent Framework Workflow (typed graph).

    ingest ──▶ BA agent ──▶ Architect agent ──▶ finalize
   (read_vsdx)  (describe)     (formalise)     (render + stage import)

Agents are pure structured-output nodes (text->JSON); every tool call — reading the Visio,
validating against the semantic matrix, rendering, staging the ADOIT import — is a deterministic
node. Governed egress is unchanged: agent LLM calls go through the gateway (metered, PII-scanned)
with each agent's own credential; the tool nodes call the gateway MCP with the Architect's
identity (which holds the ADOIT/semantic grants). Schema/legality failures loop back once inside
the owning node, keeping the graph linear.

`run_workflow(cfg)` builds and runs the graph and returns the final output dict.
"""
import json
import re
import sys

from agent_framework import WorkflowBuilder, WorkflowContext, executor
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from jsonschema import Draft7Validator

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]
                       / ".claude" / "skills" / "visio-reader" / "scripts"))
from read_vsdx import read_vsdx  # noqa: E402


def _extract_json(text: str):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S).strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        return json.loads(m.group(0)) if m else None


async def _call_tools(headers, mcp_url, calls):
    """Open one governed MCP session and run a sequence of (suffix, args) calls; return list of
    .data. Tools are addressed by suffix (the gateway prefixes server names)."""
    async with Client(StreamableHttpTransport(mcp_url, headers=headers)) as c:
        names = [t.name for t in await c.list_tools()]

        def pick(suffix):
            m = [n for n in names if n.endswith(suffix)]
            if not m:
                raise RuntimeError(f"tool *{suffix} not exposed by gateway (visible: {names})")
            return m[0]

        out = []
        for suffix, args in calls:
            res = await c.call_tool(pick(suffix), args)
            out.append(res.data)
        return out


def build_workflow(cfg):
    """cfg: dict with ba_agent, architect_agent, mcp_headers, mcp_url, schema, tracer, root_ctx,
    model_name (for the ArchiMate model), outdir (local-dev convenience)."""
    tracer = cfg["tracer"]
    root_ctx = cfg["root_ctx"]
    validator = Draft7Validator(cfg["schema"])

    def span(name):
        return tracer.start_as_current_span(name, context=root_ctx)

    @executor(id="ingest")
    async def ingest(path: str, ctx: WorkflowContext[dict]) -> None:
        with span("ingest") as s:
            parsed = read_vsdx(path)
            s.set_attribute("visio.shapes", len(parsed["shapes"]))
            s.set_attribute("visio.connectors", len(parsed["connectors"]))
            await ctx.send_message({"path": path, "parsed": parsed})

    @executor(id="ba")
    async def ba(state: dict, ctx: WorkflowContext[dict]) -> None:
        with span("ba-agent") as s:
            agent = cfg["ba_agent"]
            r = await agent.run("Parsed Visio diagram:\n" + json.dumps(state["parsed"]))
            obj = _extract_json(r.text)
            errs = _schema_errors(validator, obj)
            if errs:                                   # one corrective retry, self-contained
                r = await agent.run(
                    f"Your previous output failed schema validation: {errs}\n"
                    f"Here it is: {json.dumps(obj)}\nFix exactly those problems and resend the "
                    f"full corrected JSON only.")
                obj = _extract_json(r.text)
                errs = _schema_errors(validator, obj)
                if errs:
                    raise RuntimeError(f"BA output still schema-invalid after retry: {errs}")
            n = sum(len(obj.get(k, [])) for k in ("actors", "components", "data", "behaviors"))
            s.set_attribute("ba.elements", n)
            s.set_attribute("ba.relationships", len(obj.get("relationships", [])))
            state["ba_output"] = obj
            await ctx.send_message(state)

    @executor(id="architect")
    async def architect(state: dict, ctx: WorkflowContext[dict]) -> None:
        with span("architect-agent") as s:
            agent = cfg["architect_agent"]
            r = await agent.run("BA system description:\n" + json.dumps(state["ba_output"]))
            spec = _extract_json(r.text)
            if not spec or "elements" not in spec:
                raise RuntimeError(f"Architect did not return a spec: {(r.text or '')[:200]!r}")
            # governed semantic legality check (Architect identity); loop back once on illegal
            sem = (await _call_tools(cfg["mcp_headers"], cfg["mcp_url"],
                                     [("semantic_validate_model", {"spec": spec})]))[0]
            if sem["illegal"]:
                detail = "; ".join(
                    f"{i['relation']} {i['source']}->{i['target']} not permitted (allowed: "
                    f"{', '.join(i['allowed'][:5]) or 'nothing'})" for i in sem["illegal"])
                r = await agent.run(
                    f"The semantic validator rejected these relationships: {detail}\n"
                    f"Correct exactly those relations (re-type to the weakest legal relation; do "
                    f"not drop any) and resend the full spec JSON only.")
                spec = _extract_json(r.text)
                sem = (await _call_tools(cfg["mcp_headers"], cfg["mcp_url"],
                                         [("semantic_validate_model", {"spec": spec})]))[0]
            s.set_attribute("spec.elements", len(spec.get("elements", [])))
            s.set_attribute("spec.relations", len(spec.get("relations", [])))
            s.set_attribute("semantic.illegal", len(sem["illegal"]))
            s.set_attribute("semantic.warnings", len(sem["warnings"]))
            state["spec"] = spec
            state["semantic"] = {"illegal": sem["illegal"], "warnings": sem["warnings"]}
            await ctx.send_message(state)

    @executor(id="finalize")
    async def finalize(state: dict, ctx: WorkflowContext[dict]) -> None:
        with span("finalize") as s:
            spec = state["spec"]
            model_name = spec.get("name") or cfg.get("model_name", "Visio Import")
            # the Architect emits elements+relations; let the engine lay out the standard layered
            # view catalogue deterministically (motivation->strategy->business->app->tech).
            spec = {**spec, "standard_views": True}
            render, = await _call_tools(cfg["mcp_headers"], cfg["mcp_url"], [
                ("archimate_render",
                 {"spec": spec, "basename": "visio-import", "outdir": cfg.get("outdir")}),
            ])
            summary = {"elements": len(spec.get("elements", [])),
                       "relations": len(spec.get("relations", [])),
                       "views": len(render["views"]),
                       "violations": len(render["violations"]),
                       "warnings": len(render["warnings"]),
                       "semantic_illegal": len(state["semantic"]["illegal"]),
                       "semantic_warnings": len(state["semantic"]["warnings"])}
            req, = await _call_tools(cfg["mcp_headers"], cfg["mcp_url"], [
                ("adoit_request_import",
                 {"xml_ref": render["xml_ref"], "svg_refs": render["svg_refs"],
                  "model_name": model_name, "summary": summary, "requester": "architect-agent"}),
            ])
            s.set_attribute("render.views", len(render["views"]))
            s.set_attribute("approval.request_id", req["request_id"])
            await ctx.yield_output({
                "request_id": req["request_id"], "status": req["status"],
                "review_app": req.get("review_app"), "xml_ref": render["xml_ref"],
                "svg_refs": render["svg_refs"], "summary": summary, "spec": spec,
                "semantic": state["semantic"]})

    return WorkflowBuilder(start_executor=ingest).add_chain(
        [ingest, ba, architect, finalize]).build()


def _schema_errors(validator, obj):
    if obj is None:
        return "not valid JSON"
    errs = sorted(validator.iter_errors(obj), key=lambda e: list(e.path))
    if not errs:
        return None
    return "; ".join(f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errs[:5])


async def run_workflow(cfg, path: str):
    wf = build_workflow(cfg)
    result = await wf.run(path)
    outputs = result.get_outputs()
    if not outputs:
        raise RuntimeError("workflow produced no output")
    return outputs[0]
