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
    ReferenceTools,
    VectorStores,
    USE_CASE_DESIGN,
    USE_CASE_SCREENING,
    ApprovalTools,
    CollabTools,
    Continuation,
    SemanticTools,
    StorageTools,
)
from lab.workloads import gateway
from lab.workloads.usecase import coverage
from lab.core.usecase import capabilities
from lab.workloads.usecase import reference
from lab.workloads.usecase.steps import step_for
from lab.workloads.usecase import modeltrace, modelling
from lab.workloads.usecase.derivation import Derivation
from lab.workloads.usecase.steps import SCREENING_STEPS

#: Refused at preflight rather than twenty minutes in. `collab_fetch` is deliberately absent: only
#: a submission that arrives as a handle needs it, and a deployment without the grant should degrade
#: to "upload it first" rather than be refused outright.
#: The process this workload runs, declared on every approval it raises so a channel
#: serving one pipeline can leave the others alone without guessing from a subject line.
PROCESS = USE_CASE_SCREENING.name

#: `approvals_ask` carries its ARGUMENTS, not just its name. A tool present under the right name
#: can still reject the call when the deployed server is older than the workload — measured, at the
#: cost of a whole run.
REQUIRED_TOOLS = (StorageTools.read_document, SemanticTools.store_spec,
                  (ApprovalTools.ask, ("subject", "prompt", "items", "process")),
                  ReferenceTools.pin, (ReferenceTools.lookup, ("pin_id", "artifact_id")))

#: The reference corpora served by a TOOL, and the tool that serves each. NOT preflighted: a
#: corpus that cannot be fetched leaves its steps unable to run, which is a partial record and a
#: named gap — refusing the whole run would give a deployment missing one grant nothing at all.
CORPORA = {
    "ontology": (SemanticTools.ontologies, {}),
}

#: The capability map is read from the GOVERNED corpus under this run's pin, not from a tool: the
#: scheme names the artifact (= the gateway's relevance store), and what is fetched up front is
#: the top level (the drill's first candidates) and the leaves (what `leaves` reads whole, and
#: what the drill fallback measures) — `id, parent, level, label, path`, a version cited.
#: **Step 5 matches against the TECHNOLOGY capability map** (user decision, 18 Sep 2026), read from
#: the governed corpus under the run's pin like any other artifact — nothing about it is in this
#: file or in a prompt, so the map changes by publishing a new version and no code moves.
#:
#: It replaced the business map, which is retired until this enterprise publishes its own (see
#: `docs/decisions/2026-09-18-two-capability-maps.md`; reinstating it means building the read path
#: for THAT map — its record type, its levels and its store are its own, so a dormant setting here
#: would have promised a switch that does not exist). The technology map answers a different
#: question — *how would we do this* rather than *what ability does this exercise* — and it is the
#: one the rest of the framework actually joins on: a match returns `"Domain · Capability"`, which
#: IS the key `guardrails.cap` and `ai-capability-map.components` resolve against. So a matched
#: capability reaches its obligations and its components with no further resolution, where a
#: business-map match reached nothing this framework catalogues.
CAPABILITY_ARTIFACT = "ai-capability-map"
DOMAIN_ARTIFACT = "capability-domains"
MAP_RECORD_TYPE = "capability"
DOMAIN_RECORD_TYPE = "domain"

#: Fields a corpus record contributes to a PROMPT, by corpus. Everything else is dropped before the
#: message is built.
#:
#: This is a projection, not a truncation — no concept is lost, so a coverage match still sees the
#: whole published map and can still refuse to match. What goes is everything a MATCH does not read.
#:
#: Both halves were learned on the business map and both still apply. Sending a `definition` per
#: concept made step 5's prompt 94,000 tokens and a live run sat on it for fifty-three minutes
#: without failing — the worst way for a size problem to present, because a hang looks like
#: slowness and slowness looks like patience. Stripping the definition entirely then made every
#: match in every cloud run come back `assumption`: a label is frequently ambiguous on its own, and
#: the model was correctly reporting that it had inferred from words. So the definition travels,
#: capped — bounded prose beats no prose, and unbounded prose is what hung the run.
PROMPT_FIELDS = {"capabilities": ("id", "label", "level", "parent", "path", "definition")}

#: How much of a definition a match may read. The technology map's run to a sentence or two — the
#: rationale for the row plus the products — and the cap is what keeps a map that GROWS from
#: silently becoming a prompt nobody sized.
DEFINITION_CHARS = 300

#: More rows than any published map holds. `reference.records` REFUSES a read the server truncated,
#: because the surviving subset is ordered by a content hash and nothing downstream could tell it
#: was partial — so a map that outgrows this fails loudly rather than being matched over in part.
MAP_LIMIT = 5000

#: What one step's prompt may carry. A corpus over it is recorded as unavailable by name rather than
#: sent in part: a step that silently receives half a corpus answers confidently from half a corpus.
MAX_CORPUS_BYTES = 200_000

#: What this run pins: the technology capability map its coverage match reads, and the domains that
#: give it its top level. Both are corpus artifacts, so which map a run matched against is part of
#: the record and a new version is a publish, never a deploy.
REFERENCE_ARTIFACTS = (CAPABILITY_ARTIFACT, DOMAIN_ARTIFACT)

def required_stores() -> tuple[str, ...]:
    """The relevance stores this run must be granted — none, and it REFUSES rather than returning
    an empty tuple when the configured matcher needs one.

    The technology capability map is 74 rows read whole; it has no store. A deployment configured
    for `vector` or `translate` therefore preflighted clean, ran for ten minutes, and then deferred
    step 5 because the search seam raised — leaving readiness gate A unevidenced and the reason
    buried in `pending_steps`, all for a configuration typo. Preflight is where that costs zero
    tokens, which is the whole reason it exists.
    """
    if config.COVERAGE_MATCHER in coverage.STORE_BACKED:
        raise RuntimeError(
            f"COVERAGE_MATCHER={config.COVERAGE_MATCHER!r} searches a relevance store, and the "
            f"technology capability map has none — it is a register read whole. "
            f"Configure `leaves` or `drill`.")
    return ()


def project(name: str, corpus):
    """A corpus as a step should READ it — the fields a match needs, and nothing else.

    Prose is TRUNCATED rather than dropped: `definition` is what makes a match a lookup instead of
    a guess, and its first sentences carry the meaning."""
    fields = PROMPT_FIELDS.get(name)
    if not fields or not isinstance(corpus, list):
        return corpus
    out = []
    for c in corpus:
        if not isinstance(c, dict):
            continue
        row = {k: c[k] for k in fields if c.get(k) is not None}
        if isinstance(row.get("definition"), str) and len(row["definition"]) > DEFINITION_CHARS:
            row["definition"] = row["definition"][:DEFINITION_CHARS].rstrip() + "…"
        out.append(row)
    return out

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


def make_cfg(*, credential="", mcp_url="", gateway_url="", traceparent="", agents=None,
             tracer=None, root_ctx=None, run_id=""):
    """The ONE config contract. Nothing below reads the environment.

    `agents` maps a step key to its agent. A step with no entry is SKIPPED and stays in
    `pending_steps` — which is how this workload ran before any agent existed and how a deployment
    missing one model still produces a partial, honest record instead of failing."""
    return {"headers": gateway.auth_headers(credential, traceparent), "mcp_url": mcp_url or config.GATEWAY_MCP_URL,
            "gateway_url": gateway_url or config.GATEWAY_URL,
            "credential": credential, "agents": dict(agents or {}), "tracer": tracer,
            "root_ctx": root_ctx, "run_id": run_id, "process": PROCESS}


async def fetch_capabilities(cfg, pin_id: str) -> list[dict]:
    """The technology capability map, whole, under the pin, attributed to the coverage map.

    WHOLE and not by key: it is a small complete register (74 rows), and CAFÉ's own rule for such an
    artifact is to read every record rather than "the relevant rows" — a selection would decide
    relevance before the step whose job that is. `reference.records` with an empty key returns every
    record of a `whole` artifact whatever the limit.

    An empty read is NOT an error: step 5 then takes its declared default and the gap is stated on
    the record, rather than a corpus outage being presented as a use case that matched nothing.
    """
    rows = await reference.records(cfg, pin_id, CAPABILITY_ARTIFACT, record_type=MAP_RECORD_TYPE,
                                   key={}, field="coverage_map", limit=MAP_LIMIT)
    domains = await reference.records(cfg, pin_id, DOMAIN_ARTIFACT, record_type=DOMAIN_RECORD_TYPE,
                                      key={}, field="coverage_map", limit=MAP_LIMIT)
    return capabilities.concepts(rows, domains)


async def match_capabilities(cfg, d, pin_id: str) -> dict:
    """Step 5, by whichever capability matcher this deployment runs.

    The strategies live in `lab.workloads.usecase.coverage` with the evidence for choosing between
    them. The corpus and the two seams are supplied HERE — which artifact a run reads, and that it
    reads it under this pin attributed to this field, is the workload's decision; how the map is
    matched is not.

    The grain is `capabilities.LEVEL`, the map's own: CAFÉ's M4 is domain -> capability -> product
    and only the first two are rows. It is passed rather than left to the default, which is 3 and
    would yield NO candidates over a two-level map — indistinguishable downstream from "nothing is
    relevant".

    The technology map has no relevance store, so a store-backed matcher has nothing to search and
    `search` says so by name instead of returning an empty result.
    """
    async def children(ids, level):
        found: list[dict] = []
        for ident in ids:
            found += [c for c in (d.available.get("capabilities") or [])
                      if c.get("parent") == ident and c.get("level") == level]
        return found

    async def search(query, k):
        # Unreachable while `required_stores()` refuses a store-backed matcher at preflight. Kept,
        # and loud, because the seam is part of the matcher contract and a silent empty result here
        # would read as "the map knows nothing about this function".
        raise RuntimeError(
            f"{CAPABILITY_ARTIFACT} has no relevance store to search — it is a register read whole. "
            f"Configure COVERAGE_MATCHER as `leaves` or `drill`.")

    if not (d.available.get("capabilities") or []):
        # No map. Run the step with NO context override so `capabilities` is genuinely absent from
        # the pool and `run_step` takes the declared default — every matcher passes the candidate
        # list AS context, and an empty list present under that name looks like a published map
        # with nothing in it, which defers instead of defaulting.
        await d.run_step(cfg, step_for("5"), label="match capabilities")
        return {}

    return await coverage.match(
        cfg, d, d.available.get("capabilities") or [],
        name=config.COVERAGE_MATCHER, children=children, search=search,
        project=lambda rows: project("capabilities", rows), budget=MAX_CORPUS_BYTES,
        deepest=capabilities.LEVEL)


def _live_record(cfg):
    """A publisher that puts the record SO FAR on the run board after every step, or None.

    Why it has to exist at all: the record was stored once, at the end, and its ref reached the
    board only through the workflow's final output — so for the entire window in which a person
    watches a run, no step could show what it had actually produced, and a run that died showed
    nothing ever. `wfr-c53cdaa27bdb` (18 Sep 2026) died at step 7 holding four steps of real
    output that no surface could display.

    Written under its OWN field. `screening_ref` means "the screening record" and other consumers
    read it — the notifier, the fabric ingest, the design run — so pointing it at a half-built
    record mid-run would be a lie told to everything downstream, to serve one page. The review app
    prefers `record_ref` while a run is live and falls back to `screening_ref` once it is done.

    Returns None when the run is not on the board (a CLI or test run): nothing to publish to.
    """
    from lab.platform import runlog

    run_id = cfg.get("run_id")
    if not run_id:
        return None

    async def publish(record: dict) -> None:
        # Awaited in order, never concurrent: two partial records landing out of sequence would
        # make the roadmap go backwards, which is worse than one arriving a second late. It is one
        # small gateway call between steps that each take tens of seconds.
        stored = await gateway.call(cfg, SemanticTools.store_spec,
                                    {"spec": record, "name": "screening.partial.json"})
        runlog.update(run_id, record_ref=gateway.ref_from(stored))

    return publish


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
            pinned = await reference.pin(cfg, REFERENCE_ARTIFACTS)
            fetched: dict = {}
            missing: dict = dict(UNAVAILABLE)
            # The map, from the corpus under the pin. Not size-checked here: a matcher decides
            # what of it goes into a prompt (`coverage.resolve` measures the leaves), so the
            # working set is not the prompt.
            try:
                rows = project("capabilities", await fetch_capabilities(cfg, pinned["pin_id"]))
                if rows:
                    fetched["capabilities"] = rows
                else:
                    missing["capabilities"] = "the pinned map served no rows"
            except Exception as exc:                         # noqa: BLE001 — a corpus is optional
                missing["capabilities"] = f"{type(exc).__name__}: {exc}"[:200]
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
                             "pin_id": pinned["pin_id"],
                             "pinned_versions": pinned["versions"]}
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
                           pending=dict(PENDING_STEPS),
                           publish=_live_record(cfg))
            for step in SCREENING_STEPS:
                if step.key == "coverage_map":
                    # Run by the configured matcher, not by this loop. The keys are spelled
                    # out rather than merged from the return, so what this executor adds to the
                    # state is readable here — `test_workflow_state_keys` reads exactly this and
                    # would otherwise have no way to tell a written key from a typo.
                    drilled = await match_capabilities(cfg, d, state["pin_id"])
                    # 0 and [], not None: the drill returns nothing when the coverage agent is
                    # unwired or its corpus was unavailable, and those are exactly the runs where a
                    # reader most needs the record to say how deep the match went.
                    state = state | {"capability_depth": drilled.get("capability_depth", 0),
                                     "coverage_trail": drilled.get("coverage_trail") or []}
                    await modelling.grow(cfg, d, step.key)
                    continue
                # The label is what this process calls the step ("match capabilities"), so a
                # deferred one reads as the exercise a person recognises rather than as its key.
                await d.run_step(cfg, step, label=PENDING_STEPS.get(step.number, step.key))
                # Onto the ONE architecture model the run grows: every later step reads it as
                # data, and the views a reviewer sees are projections of it.
                await modelling.grow(cfg, d, step.key)
            derived, pending = d.derived, d.pending

            screening = {"pending_steps": pending,
                         # Steps that recorded their DECLARED default because this tenant has not
                         # published the corpus they read — listed apart from pending (did not run)
                         # and from derived, so a reader sees what rests on an assumption.
                         "defaulted_steps": dict(d.defaulted),
                         "corpora_unavailable": dict(state.get("corpora_unavailable") or {}),
                         # How deep the capability match actually reached, and the trail it took —
                         # a final L3 list alone cannot be checked, because a leaf under a branch
                         # nobody should have opened looks exactly like a leaf under one they should.
                         "capability_depth": state.get("capability_depth"),
                         "coverage_trail": state.get("coverage_trail"),
                         # The versions this screening cited, for the design run to compare.
                         "pin_id": state["pin_id"],
                         "pinned_versions": state["pinned_versions"],
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
                "defaulted_steps": sorted((state.get("screening") or {}).get("defaulted_steps") or {}),
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
                "fields": ["value"],                   # one thing to say per label, not a voice
                "summary": summary,                    # what this screening found, before the refs
                "continuation": cont.to_dict(),
                "artifacts": {"submission": state["submission_record_ref"],
                              "screening": state["screening_ref"],
                              # The per-step model trace, while it is on: one tab per step.
                              **({"svg_refs": trace_tabs} if (trace_tabs := modeltrace.tabs(
                                  state.get("screening") or {})) else {})},
                "requester": state.get("submitter", ""),
                "process": PROCESS})
            out = {"approval_id": asked["request_id"],
                   "review_app": asked.get("review_app", ""),
                   # The problem as step 3 framed it, one line: what a person recognises this run
                   # by when they come looking for it later.
                   "subject": str(((state.get("screening") or {}).get("frame") or {})
                                  .get("problem", ""))[:160],
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
                                   required=REQUIRED_TOOLS, required_stores=required_stores())
