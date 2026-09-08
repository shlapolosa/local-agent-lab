"""Step 27 — create the work items and catalog entries an approved investment authorised.

Reached only by approving the investment. CR-20 ("no work item or catalog entry created before
architect approval") is enforced by the GRANT rather than by this code: no earlier process in the
pipeline is granted a write tool at all, so there is no branch anybody could take the wrong way.

**FR-42 — idempotent and reversible — and both halves are structural rather than careful.**

*Idempotent*, because the staging key is a digest of the investment reference and the CONTENT being
staged. Re-running the same approved package computes the same key and stages the same artifacts;
nothing accumulates. Keying on the RUN would have made every retry look like new work, which is the
failure mode a retry is supposed to fix. And keying on the investment reference ALONE would be
worse than either: a corrected package would silently reuse the key of the one it replaced, so the
system would insist nothing had changed while holding something different.

*Reversible*, because nothing is written. Everything is STAGED for a human to release, on the
`ea_stage_import` model — a list of typed `ImportArtifact`s with the adapter's own label and note,
which a review surface renders as downloads without knowing what any of them is. Undoing a staged
import means not importing it. That is a weaker guarantee than a transactional write and a much
more honest one: the target work-item tracker is not built, and a fabricated write against a system
that does not exist would report success it could not have had.
"""
from __future__ import annotations

import hashlib
import json

from agent_framework import WorkflowBuilder, WorkflowContext, executor

from lab.platform import config
from lab.platform.contracts import ImportArtifact, SemanticTools, StorageTools
from lab.workloads import gateway

REQUIRED_TOOLS = (StorageTools.read_artifact, SemanticTools.store_spec)

WORK_ITEM_NOTE = ("Import as the work item tree for this use case. Every item names an owner and "
                  "the obligations it carries; an item with no owner was refused upstream.")
CATALOG_NOTE = ("Import as the portal catalog entry. It is keyed on the investment, so releasing "
                "this twice updates one entry rather than creating a second.")


def make_cfg(*, credential="", mcp_url="", traceparent="", tracer=None,
             root_ctx=None, run_id=""):
    return {"headers": gateway.auth_headers(credential, traceparent), "mcp_url": mcp_url or config.GATEWAY_MCP_URL,
            "credential": credential, "tracer": tracer, "root_ctx": root_ctx,
            "run_id": run_id}




async def _read(cfg, ref: str) -> dict:
    raw = await gateway.call(cfg, StorageTools.read_artifact, {"ref": ref})
    return raw if isinstance(raw, dict) else json.loads(raw or "{}")


def staging_key(investment_ref: str, content: object) -> str:
    """The idempotency key: the investment PLUS a digest of what is being staged.

    Both halves are load-bearing. Without the content, a corrected package would reuse the key of
    the one it replaced and the system would insist nothing had changed. Without the investment,
    two use cases that happened to produce identical work items would collide."""
    body = json.dumps(content, sort_keys=True, ensure_ascii=False, default=str)
    return f"{investment_ref}#{hashlib.sha256(body.encode()).hexdigest()[:16]}"


def build_workflow(cfg):
    @executor(id="provision")
    async def provision(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Stage the work item tree and the catalog entry. Terminal.

        What is staged comes from step 25, through the investment package that approved it — never
        drafted here. A provisioning run that wrote its own work items would be creating work
        nobody approved, which is precisely what CR-20 exists to stop, one process too late for the
        grant to help."""
        with gateway.node_span(cfg, "provision"):
            investment = await _read(cfg, state["investment_ref"])
            design_ref = investment.get("design_ref", "")
            design = await _read(cfg, design_ref) if design_ref else {}
            delivery = design.get("delivery_artifacts") or {}
            work_items = list(delivery.get("work_items") or ())
            catalog = dict(delivery.get("catalog_entry") or {})

            staged = {"investment_ref": state["investment_ref"], "design_ref": design_ref,
                      "authorisation": dict(state.get("authorisation") or {}),
                      "work_items": work_items, "catalog_entry": catalog,
                      "gate_conditions": list(investment.get("gate_conditions") or ())}
            staged["idempotency"] = staging_key(state["investment_ref"],
                                                {"work_items": work_items, "catalog": catalog})

            stored = await gateway.call(cfg, SemanticTools.store_spec,
                                 {"spec": staged, "name": "provisioning.staged.json"})
            ref = gateway.ref_from(stored)

            # Typed, so a review surface renders the label and the note and offers a download
            # without knowing what any of these files is. Nothing is staged that has no content:
            # an empty artifact on the page reads as "released and empty", not "never drafted".
            artifacts = []
            if work_items:
                artifacts.append(ImportArtifact(
                    ref=ref, label=f"Work item tree ({len(work_items)} items)",
                    note=WORK_ITEM_NOTE, media_type="application/json"))
            if catalog:
                artifacts.append(ImportArtifact(
                    ref=ref, label=f'Catalog entry — {catalog.get("name", "unnamed")}',
                    note=CATALOG_NOTE, media_type="application/json"))

            out = {"provisioned": bool(artifacts),
                   "work_items_ref": ref if work_items else "",
                   "catalog_ref": ref if catalog else "",
                   "idempotency": staged["idempotency"],
                   "import_artifacts": [a.__dict__ for a in artifacts],
                   "summary": {"work_items": len(work_items),
                               "catalog_entries": 1 if catalog else 0,
                               "staged": bool(artifacts),
                               # Not a footnote. An investment approved WITH conditions still has
                               # them open when the work is created, and whoever picks the tree up
                               # is the person who has to close them.
                               "gate_conditions": len(staged["gate_conditions"])}}
        await ctx.yield_output(out)

    # One node, so no chain: `add_chain` needs two. Step 27 is a single staged write
    # whose approval already happened — there is nothing to sequence it with.
    return WorkflowBuilder(start_executor=provision).build()


async def run_workflow(cfg, inputs: dict) -> dict:
    """Preflight, then the graph. Both are `gateway.run_graph`'s — the preflight rule
    in particular was paid for once by a cloud failure and should not exist per
    workload, because the copy that will lack it is the next one."""
    return await gateway.run_graph(cfg, build_workflow, inputs, what="provisioning",
                                   required=REQUIRED_TOOLS)
