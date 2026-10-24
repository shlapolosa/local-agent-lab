"""Read the documents, model what they describe, build the envelope, ask an architect (ADR D7, D8).

Four nodes, each a step a person could name:
1. `read` — every document through the governed store, as text. The workload holds no store credential.
2. `model` — ONE agent over the numbered, keyed inputs, gated against the domain's schema (one retry).
3. `envelope` — the deterministic mapping (`lab.core.modelling.mapping`), stored by ref.
4. `review` — the modelling gate: an architect checks the model against its citations before anything
   is drawn or imported. Terminal; approving releases nothing yet.
"""
from __future__ import annotations

from agent_framework import WorkflowBuilder, WorkflowContext, executor
from jsonschema import Draft202012Validator

from lab.core.modelling import agent_schema, mapping
from lab.core.modelling.provenance import Source
from lab.core.modelling.sources import keyed, message
from lab.platform import config
from lab.platform.contracts import ARCHITECTURE_MODELLING, ApprovalKind, ApprovalTools, SemanticTools, StorageTools
from lab.platform.filetypes import content_type_for
from lab.workloads import gateway
from lab.workloads.gates import run_gated

PROCESS = ARCHITECTURE_MODELLING.name

REQUIRED_TOOLS = (StorageTools.read_document, SemanticTools.store_spec, ApprovalTools.ask)

PROMPT = ("Review this architecture model against the documents it was drawn from. Every element and "
          "relationship cites a passage; open questions list what the citations could not settle, "
          "including anything read from an image, which no check can confirm. Accept the model, or "
          "request changes and say what is wrong.")


def make_cfg(*, credential="", mcp_url="", traceparent="", tracer=None, root_ctx=None, run_id="",
             agent=None):
    return {"headers": gateway.auth_headers(credential, traceparent),
            "mcp_url": mcp_url or config.GATEWAY_MCP_URL, "credential": credential, "tracer": tracer,
            "root_ctx": root_ctx, "run_id": run_id, "agent": agent,
            "validator": Draft202012Validator(agent_schema.schema())}


def _name(ref: str) -> str:
    return ref.rstrip("/").rsplit("/", 1)[-1]


def build_workflow(cfg):
    @executor(id="read")
    async def read(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Every document as text, in the order given. A document with no readable text is refused
        by name: a model of nothing would read like a model of a small system."""
        with gateway.node_span(cfg, "read", documents=len(state["documents"])):
            sources = []
            for ref in state["documents"]:
                text = await gateway.call(cfg, StorageTools.read_document, {"ref": ref})
                text = text if isinstance(text, str) else str(text or "")
                if not text.strip():
                    raise ValueError(f"{ref} holds no readable text")
                sources.append(Source(ref=ref, name=_name(ref), media_type=content_type_for(_name(ref)),
                                      text=text))
        await ctx.send_message(state | {"sources": keyed(sources)})

    @executor(id="model")
    async def model(state: dict, ctx: WorkflowContext[dict]) -> None:
        with gateway.node_span(cfg, "model", sources=len(state["sources"])):
            out = await run_gated(cfg["agent"], message(state["sources"]), step="model",
                                  validator=cfg["validator"])
        await ctx.send_message(state | {"output": out})

    @executor(id="envelope")
    async def envelope(state: dict, ctx: WorkflowContext[dict]) -> None:
        with gateway.node_span(cfg, "envelope"):
            env = mapping.to_envelope(state["output"], state["sources"])
            stored = await gateway.call(cfg, SemanticTools.store_spec,
                                        {"spec": env, "name": "model.envelope.json"})
            counts = {"elements": len(env["spec"]["elements"]),
                      "relations": len(env["spec"]["relations"]),
                      "open_questions": len(env["open_questions"]), "dropped": len(env["dropped"])}
        await ctx.send_message(state | {"model_ref": gateway.ref_from(stored), "counts": counts,
                                        "system": env["spec"].get("name", "")})

    @executor(id="review")
    async def review(state: dict, ctx: WorkflowContext[dict]) -> None:
        """The modelling gate (D8). Terminal."""
        with gateway.node_span(cfg, "review"):
            asked = await gateway.call(cfg, ApprovalTools.ask, {
                "subject": f"Review an architecture model — {state['system']}",
                "prompt": PROMPT,
                "items": [{"label": "decision", "samples": ["accept", "request changes"],
                           "choices": ["accept", "request changes"]}],
                "fields": ["value"],
                "summary": state["counts"],
                "artifacts": {"model_ref": state["model_ref"],
                              **{f"source_{k}_ref": s.ref for k, s in state["sources"].items()}},
                "requester": state.get("submitter", ""),
                "process": PROCESS,
                "kind": ApprovalKind.DRAFT_REVIEW.value})
        await ctx.yield_output({"approval_id": asked["request_id"],
                                "review_app": asked.get("review_app", ""),
                                "model_ref": state["model_ref"], "summary": state["counts"]})

    return (WorkflowBuilder(start_executor=read)
            .add_chain([read, model, envelope, review]).build())


async def run_workflow(cfg, inputs: dict) -> dict:
    """Preflight, then the graph: both are `gateway.run_graph`'s."""
    return await gateway.run_graph(cfg, build_workflow, inputs, what="architecture model",
                                   required=REQUIRED_TOOLS)
