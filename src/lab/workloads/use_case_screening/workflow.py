"""Steps 1-12 — receive a use case, derive what can be derived, and ask about the class.

The SPINE. Steps 1 and 2 are real (a submission is read through the governed store, validated and
persisted as the canonical record every later step reads); steps 3 to 11 are deterministic
pass-throughs until their agents land, each recording what it did NOT do rather than pretending.
Step 12 derives the criticality band and ends at the architect's question.

Terminal by design, like the meeting pipeline's speaker question. What approving releases rides on
the approval itself, so the design run starts without this one waiting — which is what lets a
multi-day review happen at all without pinning a consumer replica.

Nothing here reads the environment: `make_cfg` is the one config contract, and the host builds it.
"""
from __future__ import annotations

import json

from agent_framework import WorkflowBuilder, WorkflowContext, executor

from lab.platform import config
from lab.platform.contracts import (
    USE_CASE_DESIGN,
    USE_CASE_SCREENING,
    ApprovalTools,
    CollabTools,
    Continuation,
    SemanticTools,
    StorageTools,
)
from lab.workloads import gateway
from lab.workloads.usecase.derivation import Derivation
from lab.workloads.usecase.steps import SCREENING_STEPS

#: Refused at preflight rather than twenty minutes in. `collab_fetch` is deliberately absent: only
#: a submission that arrives as a handle needs it, and a deployment without the grant should degrade
#: to "upload it first" rather than be refused outright.
#: The process this workload runs, declared on every approval it raises so a channel
#: serving one pipeline can leave the others alone without guessing from a subject line.
PROCESS = USE_CASE_SCREENING.name

REQUIRED_TOOLS = (StorageTools.read_document, SemanticTools.store_spec, ApprovalTools.ask)

#: The reference corpora the exercises read, and the tool that serves each. NOT preflighted: a
#: corpus that cannot be fetched leaves its steps unable to run, which is a partial record and a
#: named gap — refusing the whole run would give a deployment missing one grant nothing at all.
CORPORA = {
    # DEPTH 1, and the reason is the honest limit of this design rather than a tuning choice.
    # The published map has 1,666 concepts to L3; projected to what a match reads that is still
    # ~45,000 tokens, and a coverage match cannot be done by putting a map that size in a prompt.
    # L1 is 395 concepts (~10,000 tokens) and fits. So the match is made at L1 and the run SAYS the
    # L2/L3 refinement was not attempted — `capability_depth` in the record, and step 5's gate asks
    # for an open question about it. Matching to L3 needs RETRIEVAL over the map, which is the
    # embedding upstream this lab does not yet have; stuffing more of the map in is not the fix.
    "capabilities": (SemanticTools.concepts, {"scheme": "healthcare-provider-v2.0", "depth": 1}),
    "ontology": (SemanticTools.ontologies, {}),
}

#: Fields a corpus record contributes to a PROMPT, by corpus. Everything else is dropped before the
#: message is built.
#:
#: This is a projection, not a truncation — no concept is lost, so a coverage match still sees the
#: whole published map and can still refuse to match. What goes is the prose: a capability record
#: carries a `definition` that a MATCH does not read, and 1,666 of them made step 5's prompt 94,000
#: tokens. Measured, on a live run that sat on step 5 for fifty-three minutes without failing —
#: which is the worst way for a size problem to present, because a hang looks like slowness and
#: slowness looks like patience.
PROMPT_FIELDS = {"capabilities": ("id", "label", "level", "parent")}

#: What one corpus may contribute to a prompt. A projection that is STILL over this is reported as
#: unavailable with its size, rather than sent — a step that silently receives half a corpus
#: answers confidently from half a corpus.
MAX_CORPUS_BYTES = 120_000


def project(name: str, corpus):
    """A corpus as a step should READ it — the fields a match needs, and nothing else."""
    fields = PROMPT_FIELDS.get(name)
    if not fields or not isinstance(corpus, list):
        return corpus
    return [{k: c[k] for k in fields if c.get(k) is not None}
            for c in corpus if isinstance(c, dict)]

#: Corpora the assessment needs and this instance does not have. NAMED, because a step that reads
#: an absent corpus answers confidently from nothing and the answer is indistinguishable from a
#: grounded one. Section 6's own readiness phasing marks these red, so their absence is the
#: documented state rather than a defect — but it is stated, not assumed.
UNAVAILABLE = {
    "landscape": "no as-is application landscape is published for this business area",
    "service_levels": "no business service levels are published; step 8 must raise gap flags",
    "source_classification": "no grounding source classification is published",
}

#: The steps this spine does not yet derive. Named rather than silently skipped: a screening record
#: that simply lacked these fields would be indistinguishable from one whose agents found nothing.
PENDING_STEPS = {
    "3": "frame use case", "4": "decompose elements", "5": "match capabilities",
    "6": "match realisations", "7": "assign criticality band", "8": "derive quality attributes",
    "9": "check ontology", "10": "sequence workflow", "11": "contract sources",
}

PROMPT = ("Confirm the criticality class derived for this use case. It sets the rigour of the "
          "system that gets built — the evaluation depth, the approval shape and the corroboration "
          "requirement all follow from it, and under-classification propagates into a system "
          "somebody else operates. Change it if the dominant failure mode is worse than the "
          "derivation found, and say why: an override is how the framework learns it is mis-tuned.")


def make_cfg(*, credential="", mcp_url="", traceparent="", agents=None, tracer=None,
             root_ctx=None, run_id=""):
    """The ONE config contract. Nothing below reads the environment.

    `agents` maps a step key to its agent. A step with no entry is SKIPPED and stays in
    `pending_steps` — which is how this workload ran before any agent existed and how a deployment
    missing one model still produces a partial, honest record instead of failing."""
    return {"headers": gateway.auth_headers(credential, traceparent), "mcp_url": mcp_url or config.GATEWAY_MCP_URL,
            "credential": credential, "agents": dict(agents or {}), "tracer": tracer,
            "root_ctx": root_ctx, "run_id": run_id}




def build_workflow(cfg):
    """The static graph. No model chooses the next node — NFR-14 holds by construction."""

    @executor(id="receive")
    async def receive(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Step 1 — take delivery of the submission, whichever channel brought it.

        Exactly one of `submission` and `submission_handle` is required. `ProcessSpec.validate`
        cannot express an xor, so it is checked here — stated plainly rather than hidden, because
        it is the one input rule the contract does not carry."""
        with gateway.node_span(cfg, "receive"):
            ref, handle = state.get("submission", ""), state.get("submission_handle", "")
            if bool(ref) == bool(handle):
                raise ValueError(
                    "supply exactly one of `submission` (an art:// reference to an uploaded "
                    f"document) or `submission_handle` (a collab:// handle to fetch); got "
                    f"{'both' if ref else 'neither'}")
            if handle:
                fetched = await gateway.call(cfg, CollabTools.fetch, {"handle": handle})
                ref = fetched["ref"] if isinstance(fetched, dict) else str(fetched)
            state = state | {"submission": ref}
        await ctx.send_message(state)

    @executor(id="validate_and_persist")
    async def validate_and_persist(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Step 2 — read it, validate it, and persist the canonical record.

        FR-04: every later step reads the datastore, never the channel. The workload holds no store
        credential, so it reads through the governed store and persists through `semantic_store_spec`
        — the same move the Visio architect makes with its spec."""
        with gateway.node_span(cfg, "validate_and_persist"):
            text = await gateway.call(cfg, StorageTools.read_document, {"ref": state["submission"]})
            prose = text if isinstance(text, str) else json.dumps(text)
            if not prose.strip():
                raise ValueError(f'{state["submission"]} holds no readable text — a submission '
                                 f'nobody can read cannot be assessed')
            record = {
                "submission_ref": state["submission"],
                "submitter": state.get("submitter", ""),
                "attachments": list(state.get("attachments") or ()),
                "intake": dict(state.get("intake") or {}),
                "conversation": state.get("conversation", ""),
                "prose": prose,
            }
            stored = await gateway.call(cfg, SemanticTools.store_spec,
                                 {"spec": record, "name": "submission.record.json"})
            state = state | {"submission_record": record,
                             "submission_record_ref": gateway.ref_from(stored)}
        await ctx.send_message(state)

    @executor(id="corpora")
    async def corpora(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Fetch the reference corpora the exercises read. Best effort, and honest about the rest.

        A corpus that fails to fetch is RECORDED as unavailable rather than dropped: a step given
        an absent capability map answers confidently from nothing, and the answer is
        indistinguishable from one grounded in a real map. What could not be read is named, and the
        steps that needed it stay pending."""
        with gateway.node_span(cfg, "corpora"):
            fetched: dict = {}
            missing: dict = dict(UNAVAILABLE)
            for name, (tool, args) in CORPORA.items():
                try:
                    got = project(name, await gateway.call(cfg, tool, dict(args)))
                except Exception as exc:                     # noqa: BLE001 — a corpus is optional
                    missing[name] = f"{type(exc).__name__}: {exc}"[:200]
                    continue
                size = len(json.dumps(got, ensure_ascii=False, default=str))
                if size > MAX_CORPUS_BYTES:
                    missing[name] = (f"{size} bytes after projection, over the "
                                     f"{MAX_CORPUS_BYTES} a prompt may carry — the steps that "
                                     f"read it are not run rather than run on part of it")
                    continue
                # An EMPTY corpus is unavailable, not present. A step handed `None` or `{}` reads
                # an absent capability map and answers from nothing, which is the exact failure
                # fetching it was meant to prevent — and the tool having answered at all makes it
                # look grounded.
                if got:
                    fetched[name] = got
                else:
                    missing[name] = "the corpus was served but is empty"
            # Said in the record, not just in a comment: a reader must be able to tell that the
            # coverage map is L1 without going and reading this module.
            state = state | {"corpora": fetched, "corpora_unavailable": missing,
                             "capability_depth": CORPORA["capabilities"][1].get("depth")}
        await ctx.send_message(state)

    @executor(id="derive")
    async def derive(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Steps 3-11 — the pre-work exercises, in order, each gated before the next sees it.

        Agents never call each other: this node is the mediator, and every output passes a
        deterministic gate with one corrective retry before it becomes context for anything after
        it. A step whose agent is not wired yet stays in `pending_steps` rather than having its
        field omitted — an absent coverage map and one an agent produced empty are different
        findings, and only one of them is a gap flag.
        """
        with gateway.node_span(cfg, "derive"):
            d = Derivation(available={"submission": state["submission_record"]["prose"],
                                      **(state.get("corpora") or {})},
                           pending=dict(PENDING_STEPS))
            for step in SCREENING_STEPS:
                # The label is what this process calls the step ("match capabilities"), so a
                # deferred one reads as the exercise a person recognises rather than as its key.
                await d.run_step(cfg, step, label=PENDING_STEPS.get(step.number, step.key))
            derived, pending = d.derived, d.pending

            screening = {"pending_steps": pending,
                         "corpora_unavailable": dict(state.get("corpora_unavailable") or {}),
                         "capability_depth": state.get("capability_depth"),
                         "submission_ref": state["submission_record_ref"], **derived}
            stored = await gateway.call(cfg, SemanticTools.store_spec,
                                 {"spec": screening, "name": "screening.json"})
            state = state | {"screening": screening,
                             "criticality_band": (derived.get("criticality_band") or {}).get("band", ""),
                             "screening_ref": gateway.ref_from(stored)}
        await ctx.send_message(state)

    @executor(id="ask_criticality")
    async def ask_criticality(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Step 12 — derive the class, then ask an architect to confirm it. Terminal."""
        with gateway.node_span(cfg, "ask_criticality"):
            # Derived by step 7 when its agent ran. Absent, the question still goes to an
            # architect — with nothing proposed, which is honest: an unasked question is
            # worse than one whose default is blank.
            band = state.get("criticality_band") or ""
            summary = {
                "attachments": len(state.get("attachments") or ()),
                "intake_groups": len(state.get("intake") or {}),
                "pending_steps": len(PENDING_STEPS),
                "criticality_band": band,
            }
            # What approving RELEASES. Carried on the approval rather than as a static edge, because
            # no registry entry could hold THIS run's refs — and validated at construction, so a
            # typo fails now rather than as a human approving and nothing happening.
            cont = Continuation(
                process=USE_CASE_DESIGN.name,
                inputs={"submission_ref": state["submission_record_ref"],
                        "screening_ref": state["screening_ref"],
                        "submitter": state.get("submitter", ""),
                        "conversation": state.get("conversation", "")},
                answer_input="criticality", requester=state.get("submitter", ""))
            asked = await gateway.call(cfg, ApprovalTools.ask, {
                "subject": "Confirm the criticality class of a submitted use case",
                "prompt": PROMPT,
                "items": [{"label": "criticality_class",
                           "samples": ["routine", "business-critical", "safety-of-life"]},
                          {"label": "justification", "samples": []}],
                "continuation": cont.to_dict(),
                "artifacts": {"submission": state["submission_record_ref"],
                              "screening": state["screening_ref"]},
                "requester": state.get("submitter", ""),
                "process": PROCESS})
            out = {"approval_id": asked["request_id"],
                   "review_app": asked.get("review_app", ""),
                   "submission_ref": state["submission_record_ref"],
                   "screening_ref": state["screening_ref"],
                   "criticality_band": band,
                   "summary": summary}
        await ctx.yield_output(out)

    return (WorkflowBuilder(start_executor=receive)
            .add_chain([receive, validate_and_persist, corpora, derive, ask_criticality]).build())


async def run_workflow(cfg, inputs: dict) -> dict:
    """Preflight, then the graph. Both are `gateway.run_graph`'s — the preflight rule
    in particular was paid for once by a cloud failure and should not exist per
    workload, because the copy that will lack it is the next one."""
    return await gateway.run_graph(cfg, build_workflow, inputs, what="screening",
                                   required=REQUIRED_TOOLS)
