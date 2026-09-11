"""The `artifact_intake` graph: ONE changed artifact becomes a catalogued, classified, linked and reviewed record.

    identify [D] -> classify [D/A] -> associate [D] -> impact [D] -> synthesise [A, minutes only] -> overlap [D] -> ask_review [D]

Every write is a semantic-mcp tool call at a provenance RUNG (docs/fabric/notes 005): what a lab run
produced is a FACT (C), what a rule extracted is X, what a model suggested is S with a confidence, and
nothing here reaches H — that is a person's decision, taken at the approval this run ends on and applied
by the continuation runner with a grant no workload holds. The run writes only metadata and tagged drafts.

Terminal by design, like every gated pipeline in this lab: the run asks and ends; approving releases
`artifact_publish` through the continuation carried on the approval.

Nothing here reads the environment: `make_cfg` is the one config contract, and the host builds it.
"""
from __future__ import annotations

import json
import re

from agent_framework import WorkflowBuilder, WorkflowContext, executor

from lab.core.semantic.fabric.ontology import CONTEXT_IRI, DECISION_RECORD, DELIVERED_UNDER, REFERENCES
from lab.core.semantic.fabric.rungs import CONSTRUCTED, EXTRACTED, SUGGESTED
from lab.platform.contracts import (ARTIFACT_INTAKE, ARTIFACT_PUBLISH, TRANSCRIPT_TO_MINUTES, ApprovalKind,
                                    ApprovalTools, CollabTools, Continuation, SemanticTools, StorageTools)
from lab.workloads import gateway
from lab.workloads.gates import run_gated, validator_for

PROCESS = ARTIFACT_INTAKE.name

#: Refused at preflight rather than twenty minutes in. `collab_item` is deliberately absent: a title is
#: a convenience, and a deployment without the collaboration grant should still catalogue the file.
REQUIRED_TOOLS = (SemanticTools.catalog_upsert, SemanticTools.catalog_get, SemanticTools.catalog_assert,
                  SemanticTools.catalog_state, SemanticTools.vocab_link, SemanticTools.vocab_propose,
                  SemanticTools.impact, SemanticTools.embed, SemanticTools.similar, SemanticTools.edge_assert,
                  SemanticTools.store_spec, StorageTools.read_artifact,
                  (ApprovalTools.ask, ("subject", "prompt", "items", "process", "kind", "fields",
                                       "continuation", "artifacts", "requester")))

USECASE_ID = re.compile(r"\bUC-\d{1,6}\b")
PROMPT_REVIEW = ("Review this artifact's record before it is published: is the document type right, and "
                 "does it belong to the delivery context shown? Confirm each item or type the correct value.")


def make_cfg(*, credential: str = "", mcp_url: str = "", traceparent: str = "", agents: dict | None = None,
             schemas: dict | None = None, doc_types: dict | None = None, threshold: float = 0.75,
             default_label: str = "", tracer=None, root_ctx=None, run_id: str = ""):
    """The ONE config contract for every host of this process. Nothing below reads the environment.
    `agents` and `schemas` are keyed `classifier` / `synthesis`; an absent agent makes its step a pass-through."""
    from lab.platform import config
    return {"headers": gateway.auth_headers(credential, traceparent), "mcp_url": mcp_url or config.GATEWAY_MCP_URL,
            "credential": credential, "agents": dict(agents or {}), "schemas": dict(schemas or {}),
            "doc_types": dict(doc_types or {}), "threshold": float(threshold), "default_label": default_label,
            "tracer": tracer, "root_ctx": root_ctx, "run_id": run_id}


# ------------------------------------------------------------------------------------------ helpers

def _label_of(pointer: dict) -> str:
    ident = pointer.get("ref") or pointer.get("handle") or pointer.get("itemId") or pointer.get("workItem") or ""
    return str(ident).rstrip("/").split("/")[-1]


def _describe(state: dict) -> str:
    """The descriptive text the index is built on — title · type · subjects. Never a body."""
    parts = [state.get("title") or _label_of(state["pointer"])]
    if state.get("document_type"):
        parts.append(state["document_type"].rsplit("#", 1)[-1])
    parts.extend(state.get("subjects") or [])
    return " · ".join(p for p in parts if p)


def _type_label(cfg, iri: str | None) -> str:
    return (cfg["doc_types"].get(iri or "") or {}).get("label") or (iri or "").rsplit("#", 1)[-1] or "unknown"


# -------------------------------------------------------------------------------------------- graph

def build_workflow(cfg):
    schemas = cfg.get("schemas") or {}
    classify_gate = validator_for(schemas["classifier"]) if schemas.get("classifier") else None
    synth_gate = validator_for(schemas["synthesis"]) if schemas.get("synthesis") else None

    @executor(id="identify")
    async def identify(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Mint or find the artifact's identity; a lab output gets its type as a FACT and its delivery
        edge from the run's context (both rung C, inside the upsert)."""
        with gateway.node_span(cfg, "identify"):
            pointer = dict(state["pointer"])
            title, hints = "", {}
            if pointer.get("handle"):
                try:
                    item = await gateway.call(cfg, CollabTools.item, {"handle": pointer["handle"]})
                    title = str(item.get("name") or "")
                    hints = {k: item.get(k) for k in ("path", "modified", "created", "size") if item.get(k)}
                except Exception as e:                  # noqa: BLE001 — a title is a convenience
                    hints = {"title_lookup": f"{type(e).__name__}: {e}"}
            title = title or _label_of(pointer)
            row = await gateway.call(cfg, SemanticTools.catalog_upsert, {
                "pointer": pointer, "title": title[:300], "produced_by": state.get("produced_by") or "",
                "context": state.get("context") or "", "source_kind": pointer.get("source", "")})
            state = state | {"iri": row["iri"], "title": title, "hints": hints,
                             "document_type": row.get("document_type") or "", "row": row}
        await ctx.send_message(state)

    @executor(id="classify")
    async def classify(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Type: a fact when a lab process produced it, else the classifier's suggestion at S. Subjects:
        label-matched into the vocabulary at X; misses parked as candidates. Owner and label are never
        guessed — the label is the site default at C when nothing better is known."""
        with gateway.node_span(cfg, "classify"):
            suggestion = None
            if cfg["agents"].get("classifier") and classify_gate is not None:
                brief = {"title": state["title"], "name": _label_of(state["pointer"]),
                         "path": (state.get("hints") or {}).get("path", ""),
                         "produced_by": state.get("produced_by") or "",
                         "document_types": [{"iri": k, **v} for k, v in cfg["doc_types"].items()],
                         "hints": state.get("hints") or {}}
                suggestion = await run_gated(cfg["agents"]["classifier"], json.dumps(brief, ensure_ascii=False),
                                             step="classification", validator=classify_gate)
                # The schema pins the URN's SHAPE; the closed set is the fabric's. A type the fabric does not
                # know is not a suggestion, it is a hallucination — dropped here, named in the rationale.
                if suggestion.get("document_type") and suggestion["document_type"] not in cfg["doc_types"]:
                    suggestion["rationale"] = (f"[unknown type {suggestion['document_type']} dropped] "
                                               + str(suggestion.get("rationale") or ""))[:400]
                    suggestion["document_type"] = None
            subjects = list((suggestion or {}).get("subjects") or [])
            confidence = float((suggestion or {}).get("confidence") or 0.0)
            if not state.get("document_type") and (suggestion or {}).get("document_type"):
                await gateway.call(cfg, SemanticTools.catalog_assert, {
                    "iri": state["iri"], "field": "document_type", "value": suggestion["document_type"],
                    "rung": SUGGESTED, "method": "classifier-agent", "confidence": confidence})
                state = state | {"document_type": suggestion["document_type"], "type_rung": SUGGESTED}
            else:
                state = state | {"type_rung": CONSTRUCTED if state.get("document_type") else ""}
            linked, missed = [], []
            if subjects:
                out = await gateway.call(cfg, SemanticTools.vocab_link, {"iri": state["iri"], "terms": subjects})
                linked, missed = out.get("linked") or [], out.get("missed") or []
                for term in missed:
                    await gateway.call(cfg, SemanticTools.vocab_propose,
                                       {"label": term, "actor": "classifier-agent",
                                        "definition": f"proposed while classifying {state['title']}"})
            if cfg.get("default_label"):
                await gateway.call(cfg, SemanticTools.catalog_assert, {
                    "iri": state["iri"], "field": "sensitivity_label", "value": cfg["default_label"],
                    "rung": CONSTRUCTED, "method": "site-default"})
            state = state | {"subjects": subjects, "linked": linked, "missed": missed,
                             "confidence": confidence, "rationale": (suggestion or {}).get("rationale", "")}
        await ctx.send_message(state)

    @executor(id="associate")
    async def associate(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Rung 1 (the run's context) was written at identify. For a document a person edited: an id in
        the title is EXTRACTED (X); the contexts of the nearest indexed artifacts are SUGGESTED (S) —
        and only above the threshold; nothing at all marks the artifact unassociated for the owner."""
        with gateway.node_span(cfg, "associate"):
            candidates: list[dict] = []
            if state.get("context"):
                state = state | {"association": "run-context", "candidates": candidates}
            else:
                m = USECASE_ID.search(state["title"] or "")
                if m:
                    key = f"usecase:{m.group(0)}"
                    await gateway.call(cfg, SemanticTools.edge_assert, {
                        "subject": state["iri"], "predicate": DELIVERED_UNDER,
                        "object": CONTEXT_IRI + key, "rung": EXTRACTED, "method": "id-in-title"})
                    state = state | {"association": "id-in-title", "context": key, "candidates": candidates}
                else:
                    near = await gateway.call(cfg, SemanticTools.similar,
                                              {"text": _describe(state), "limit": 5})
                    seen: dict[str, float] = {}
                    for n in near or []:
                        c = n.get("context") or ""
                        if c and n.get("score", 0) > seen.get(c, 0):
                            seen[c] = float(n["score"])
                    candidates = [{"context": c, "score": s} for c, s in sorted(seen.items(), key=lambda t: -t[1])]
                    if candidates and candidates[0]["score"] >= cfg["threshold"]:
                        best = candidates[0]
                        await gateway.call(cfg, SemanticTools.edge_assert, {
                            "subject": state["iri"], "predicate": DELIVERED_UNDER,
                            "object": CONTEXT_IRI + best["context"], "rung": SUGGESTED,
                            "method": "nearest-neighbour", "confidence": best["score"]})
                        state = state | {"association": "nearest-neighbour", "candidates": candidates}
                    else:
                        await gateway.call(cfg, SemanticTools.catalog_state,
                                           {"iri": state["iri"], "state": "pending", "unassociated": True})
                        state = state | {"association": "unassociated", "candidates": candidates}
        await ctx.send_message(state)

    @executor(id="impact")
    async def impact(state: dict, ctx: WorkflowContext[dict]) -> None:
        """What this change may have invalidated — trusted rungs only, read-only, shown to the reviewer."""
        with gateway.node_span(cfg, "impact"):
            hits = await gateway.call(cfg, SemanticTools.impact, {"iri": state["iri"]})
            state = state | {"impact": [{"iri": h.get("iri"), "title": h.get("title"), "rung": h.get("rung")}
                                        for h in (hits or [])]}
        await ctx.send_message(state)

    @executor(id="synthesise")
    async def synthesise(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Minutes only: one decision-record DRAFT per decision, each a lab artifact of its own — type a
        FACT (the fabric drafted it), referencing the minutes (C). Any other type passes straight through."""
        with gateway.node_span(cfg, "synthesise"):
            drafts: list[dict] = []
            agent = cfg["agents"].get("synthesis")
            ref = state["pointer"].get("ref")
            if state.get("produced_by") == TRANSCRIPT_TO_MINUTES.name and agent and synth_gate is not None and ref:
                doc = await gateway.call(cfg, StorageTools.read_artifact, {"ref": ref})
                minutes = doc if isinstance(doc, dict) else json.loads(doc)
                if isinstance(minutes, dict) and "text" in minutes and "decisions" not in minutes:
                    minutes = json.loads(minutes["text"])
                got = await run_gated(agent, json.dumps(minutes, ensure_ascii=False), step="decision records",
                                      validator=synth_gate)
                stem = state["iri"].rsplit(":", 1)[-1]
                for rec in got.get("records") or []:
                    name = f"{stem}.{rec['id']}.decision-record.json"
                    stored = await gateway.call(cfg, SemanticTools.store_spec, {"spec": rec, "name": name})
                    dref = gateway.ref_from(stored)
                    row = await gateway.call(cfg, SemanticTools.catalog_upsert, {
                        "pointer": {"source": "lab", "ref": dref}, "title": rec["title"][:300],
                        "context": state.get("context") or "", "source_kind": "lab"})
                    await gateway.call(cfg, SemanticTools.catalog_assert, {
                        "iri": row["iri"], "field": "document_type", "value": DECISION_RECORD,
                        "rung": CONSTRUCTED, "method": "drafted-by-fabric"})
                    await gateway.call(cfg, SemanticTools.edge_assert, {
                        "subject": row["iri"], "predicate": REFERENCES, "object": state["iri"],
                        "rung": CONSTRUCTED, "method": "drafted-from"})
                    drafts.append({"iri": row["iri"], "ref": dref, "title": rec["title"], "id": rec["id"]})
            state = state | {"drafts": drafts}
        await ctx.send_message(state)

    @executor(id="overlap")
    async def overlap(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Index the record's DESCRIPTIVE text, then ask the index what it resembles. A proposal for the
        reviewer, never a decision; a deployment without an embedder records that and moves on."""
        with gateway.node_span(cfg, "overlap"):
            overlap_, note = [], ""
            try:
                await gateway.call(cfg, SemanticTools.embed, {"iri": state["iri"], "text": _describe(state)})
                near = await gateway.call(cfg, SemanticTools.similar, {"iri": state["iri"], "limit": 3})
                overlap_ = [{"iri": n.get("iri"), "title": n.get("title"), "score": n.get("score")}
                            for n in (near or []) if float(n.get("score") or 0) >= cfg["threshold"]]
            except Exception as e:                      # noqa: BLE001 — overlap is evidence, not a gate
                note = f"{type(e).__name__}: {e}"
            state = state | {"overlap": overlap_, "overlap_note": note}
        await ctx.send_message(state)

    @executor(id="ask_review")
    async def ask_review(state: dict, ctx: WorkflowContext[dict]) -> None:
        """The owner's question, and the end of the run. `association` when the record has no context to
        stand under; `draft-review` otherwise. Approving releases `artifact_publish`."""
        with gateway.node_span(cfg, "ask_review"):
            items = [{"label": "document_type",
                      "samples": [f"suggested: {_type_label(cfg, state.get('document_type'))}"
                                  + (f" ({state['confidence']:.2f})" if state.get("type_rung") == SUGGESTED else " (fact)"),
                                  state.get("rationale") or ""]}]
            kind = ApprovalKind.DRAFT_REVIEW
            if not state.get("context"):
                kind = ApprovalKind.ASSOCIATION
                items.append({"label": "context",
                              "samples": [f"{c['context']} ({c['score']:.2f})" for c in state.get("candidates") or []]
                              or ["no candidate: type the delivery context as <kind>:<id>, or 'none'"]})
            summary = {"impact": len(state.get("impact") or []), "overlap": len(state.get("overlap") or []),
                       "drafts": len(state.get("drafts") or []), "subjects": len(state.get("linked") or []),
                       "candidates_proposed": len(state.get("missed") or [])}
            cont = Continuation(process=ARTIFACT_PUBLISH.name, inputs={"artifact_iri": state["iri"]},
                                requester=state.get("requester") or "")
            artifacts = {f'{d["id"]} {d["title"][:60]}'.strip(): d["ref"] for d in state.get("drafts") or []}
            asked = await gateway.call(cfg, ApprovalTools.ask, {
                "kind": kind.value,
                "subject": f'{state["title"]} — {"where does this belong?" if kind is ApprovalKind.ASSOCIATION else "review the record"}',
                "prompt": PROMPT_REVIEW + f" Summary: {json.dumps(summary)}.",
                "items": items, "fields": ["value"], "continuation": cont.to_dict(),
                "artifacts": artifacts, "requester": state.get("requester") or "", "process": PROCESS})
            row = await gateway.call(cfg, SemanticTools.catalog_get, {"iri": state["iri"]})
            counts: dict[str, int] = {}
            for link in (row or {}).get("links") or []:
                counts[link["rung"]] = counts.get(link["rung"], 0) + 1
            out = {"artifact_iri": state["iri"], "approval_id": asked.get("request_id"),
                   "draft_refs": [d["ref"] for d in state.get("drafts") or []], "rung_counts": counts,
                   "kind": kind.value, "association": state.get("association"), "summary": summary}
        await ctx.yield_output(out)

    return (WorkflowBuilder(start_executor=identify)
            .add_chain([identify, classify, associate, impact, synthesise, overlap, ask_review]).build())


async def run_workflow(cfg, inputs: dict):
    return await gateway.run_graph(cfg, build_workflow, inputs, what="artifact intake", required=REQUIRED_TOOLS)


__all__ = ["REQUIRED_TOOLS", "PROCESS", "DECISION_RECORD", "make_cfg", "build_workflow", "run_workflow"]
