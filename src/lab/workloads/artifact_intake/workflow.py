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

from lab.core.semantic.fabric import citations, concepts
from lab.core.semantic.fabric.catalog import describe
from lab.core.semantic.fabric.owners import OwnerMap
from lab.core.semantic.fabric.service import PERSON
from lab.core.semantic.fabric.ontology import CONTEXT_IRI, DECISION_RECORD, DELIVERED_UNDER, REFERENCES, SYNTHESISED_FROM
from lab.core.semantic.fabric import renderings
from lab.core.semantic.fabric.rungs import CONSTRUCTED, EXTRACTED, SUGGESTED
from lab.platform.contracts import (ARTIFACT_INTAKE, ARTIFACT_PUBLISH, TRANSCRIPT_TO_MINUTES, ApprovalKind,
                                    ApprovalTools, CollabTools, Continuation, SemanticTools, StorageTools)
from lab.platform import filetypes
from lab.workloads import gateway
from lab.workloads.gates import run_gated, validator_for

PROCESS = ARTIFACT_INTAKE.name

#: Refused at preflight rather than twenty minutes in. `collab_item` is deliberately absent: a title is
#: a convenience, and a deployment without the collaboration grant should still catalogue the file.
REQUIRED_TOOLS = (SemanticTools.catalog_upsert, SemanticTools.catalog_get, SemanticTools.catalog_assert,
                  SemanticTools.catalog_state, SemanticTools.vocab_link, SemanticTools.vocab_propose,
                  SemanticTools.impact, SemanticTools.embed, SemanticTools.similar, SemanticTools.edge_assert,
                  SemanticTools.store_spec, StorageTools.read_artifact, StorageTools.read_document,
                  (ApprovalTools.ask, ("subject", "prompt", "items", "process", "kind", "fields", "answer_required",
                                       "continuation", "artifacts", "requester")))

#: How much of a document the classifier is shown. A paragraph decides what a thing is ABOUT; a
#: transcript is tens of thousands of words, and an unbounded excerpt would blow the context, the cost
#: per record and the span that carries it. Enough to recognise a subject, never the document itself.
EXCERPT_CHARS = 2000

USECASE_ID = re.compile(r"\bUC-\d{1,6}\b")
PROMPT_REVIEW = ("Review this artifact's record before it is published: is the document type right, does it "
                 "belong to the delivery context shown, and is it about the subjects listed — answer keep or "
                 "drop for each. Confirm each item or type the correct value.")


#: Processes whose output is a machine's reading of the world rather than a document — one line each, so a
#: new input source declares where it sits on the ladder instead of being assumed to be the artifact itself.
#: Measured why it matters (12 Sep 2026): on one bilingual recording the tenant's own transcript returned 53
#: words and silently dropped every Arabic turn, while the same audio rendered into English returned 97.
RENDERING_BY_PROCESS: dict[str, str] = {
    "transcript_to_minutes": "transcript-translated",
    "meeting_to_transcript": "transcript",
}


def _weakest(held: str, read: str) -> str:
    """The weaker of what the record already says and what this run read.

    Subjects ACCUMULATE on a record and a record can be read more than once, so the facet must be monotone
    downward: a reclassify that reads the document body would otherwise supersede `transcript-translated`
    with `document`, leaving concepts grounded in a machine translation on a record claiming the artifact's
    own words. A record is only as strong as the weakest evidence carried on it.

    An unrecorded value is NOT treated as weak here, unlike `renderings.of` — on an input, silence means
    nobody classified the source and the conservative reading is the weakest; on a record, it means no run
    has recorded a reading yet, and there is nothing to be weaker than."""
    if not held:
        return read
    if not read:
        return held
    return held if renderings.weaker(held, than=read) else read


def _rendering_for(produced_by: str, read_as: str) -> str:
    """The rendering a reading gets: what the WRITING process read, if it read through a machine, else how
    this node read it. The writer's rendering wins — it is the one further from the artifact, and evidence is
    only as strong as its weakest hop."""
    return RENDERING_BY_PROCESS.get(str(produced_by or "").strip(), read_as)


async def _excerpt(cfg, pointer: dict, *, produced_by: str = "", out: dict | None = None) -> tuple[str, str]:
    """The first `EXCERPT_CHARS` of what is being classified, and the RENDERING it came through — ("", "")
    when it cannot be read.

    Classification used to run on a TITLE, a file name and a path — never a byte of the document — and the
    subjects it produced were guesses dressed as facts: measured 6 Oct 2026, `Clinical document` on 39 of 93
    records and a meeting about a note-taking app filed under `Teleconsultation`. Content was never withheld
    by the architecture; the synthesis node already reads whole minutes through the same governed tool. Only
    this node went without.

    Two sources, two routes to the same ref: a `lab` pointer carries an `art://` ref that storage reads
    directly, while a `collab` pointer carries a HANDLE whose bytes must be streamed into the upload store
    first. The fetch is attempted ONLY for a handle, because it costs a round trip and a grant.

    Degrades, never fails: no grant, an unreadable body, a provider outage — the record is still catalogued
    from its metadata. An unclassified artifact is worse than an unlinked one, and that ordering is why this
    returns "" instead of raising.

    The RENDERING is how far the text is from the artifact (`lab.core.semantic.fabric.renderings`), and the
    two readers answer it differently. A document read as a document is the artifact's own words. A lab
    artifact is `structured` — its own fields, read rather than interpreted — UNLESS the process that wrote it
    read something else first: a minutes record's text is a machine translation of speech, two rungs down the
    ladder, and calling that "structured" would be true of the JSON and false about the evidence. So
    `RENDERING_BY_PROCESS` names the processes that read the world through a machine, which is why it lives
    here and not in the domain: `lab.core` cannot know what the lab's processes are.
    """
    ref = str(pointer.get("ref") or "")
    try:
        if not ref and pointer.get("handle"):
            got = await gateway.call(cfg, CollabTools.fetch, {"handle": str(pointer["handle"])})
            # `ref_from` defaults to `spec_ref`; collab_fetch answers with `ref`. Passing the wrong key
            # RAISED, and this function's degrade-rather-than-fail `except` swallowed it — so every
            # collab document was classified from its file name while the run reported success.
            ref = gateway.ref_from(got, "ref")
            # KEPT for the caller. A `collab://` handle is not readable by storage, and resolving it
            # costs a round trip and a grant — so the one other reader of these bytes (the diagram
            # producer) takes this ref rather than fetching the same file again or, worse, handing a
            # handle to a tool that wants a ref.
            if out is not None:
                out["content_ref"] = ref
        if out is not None and ref:
            out.setdefault("content_ref", ref)
        if not ref:
            return "", ""
        # TWO readers, and they refuse each other's files. `read_artifact` serves .json/.xml/.svg/
        # .xlsx/.html; a document goes to `read_document`, which also applies the cap itself rather
        # than decoding a whole file for the caller to slice. Asking the wrong one is not a soft
        # failure: measured 9 Oct 2026, every `.md` in the pilot library came back "is not an
        # artifact", so the collab half of the catalogue stayed filename-classified through two
        # sweeps that both reported success.
        if filetypes.kind_for(ref.rsplit("/", 1)[-1]) == "document":
            text = await gateway.call(cfg, StorageTools.read_document,
                                      {"ref": ref, "max_chars": EXCERPT_CHARS})
            read = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)[:EXCERPT_CHARS]
            # A rendering is a claim that something WAS read. An empty body would otherwise record "the
            # artifact's own words" on a record where nothing was grounded — the structured branch below is
            # careful about exactly this, and this one was not.
            return read, (_rendering_for(produced_by, "document") if read.strip() else "")
        doc = await gateway.call(cfg, StorageTools.read_artifact, {"ref": ref})
        if isinstance(doc, str):
            try:
                doc = json.loads(doc)
            except ValueError:
                return doc[:EXCERPT_CHARS], _rendering_for(produced_by, "structured")
        # A lab artifact has no `text` key — it IS the text. A minutes record parses into
        # {"summary": …, "concepts": […]}, so looking only for `text`/`content` found neither and
        # returned "" with nothing raised and nothing logged: the classifier saw a file name and
        # guessed, which is why the minutes stayed wrong after four other causes were fixed.
        text = (doc.get("text") or doc.get("content")) if isinstance(doc, dict) else doc
        if not text:
            text = json.dumps(doc, ensure_ascii=False)
        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False)
        # An EMPTY structure serialises to "{}" — truthy, and meaningless. Reading it as content would
        # hand the classifier two characters and call that evidence.
        if text.strip() in ("", "{}", "[]", "null"):
            return "", ""
        return text[:EXCERPT_CHARS], _rendering_for(produced_by, "structured")
    except Exception as e:                      # noqa: BLE001 — see the docstring: evidence is best effort
        print(f"[intake] no excerpt for {pointer.get('ref') or pointer.get('handle')}: "
              f"{type(e).__name__}: {e}", flush=True)
        return "", ""


#: How many subjects one owner card may ask about. A subject is asserted at X by a label match on a
#: grounded span, so the card is not re-checking the fabric's work — it is letting the person who knows the
#: document promote the few that matter to H. Capped because a record with a dozen subjects would otherwise
#: become a dozen questions, which is the forty-fields mistake the steward's batch card already paid for.
SUBJECT_ASK_MAX = 3


def _subject_items(state: dict, cap: int) -> tuple[list[dict], list[str]]:
    """The subject items for the owner's card, and the labels held back.

    Ranked by SALIENCE — how central the extractor found the term to THIS document — because a cap has to
    choose and "what your document is most about" is the only ordering a person would recognise. Ties and
    absent salience fall back to the label, so two runs of one record ask the same question.

    The label is the CONCEPT IRI, not the term: `check_answer` keys the answer on the item label, and two
    records' terms for one concept would collide. The human-readable name lives in the samples, which is the
    `batch_question` rule.

    Held-back subjects are NAMED rather than counted, and they stand at X untouched. Nothing is tracked and
    nothing is lost — which is what makes a cap safe here and unsafe on the candidate register, where a term
    nobody asks about is a term nobody ever asks about again."""
    salience = state.get("salience") or {}
    linked = [l for l in (state.get("linked") or []) if l.get("concept")]
    ranked = sorted(linked, key=lambda l: (-float(salience.get(l.get("term") or "", 0.0)),
                                           str(l.get("label") or l.get("term") or "")))
    asked, held = ranked[:max(0, int(cap))], ranked[max(0, int(cap)):]
    items = [{"label": f"subject:{l['concept']}",
              "choices": ["keep", "drop"],         # the ANSWERS; the sentence below only explains them
              "samples": [f"{l.get('label') or l.get('term')} — found in the content; "
                          f"keep confirms it, drop records that this document is not about it"]}
             for l in asked]
    return items, [str(l.get("label") or l.get("term") or "") for l in held]


async def _propose_relations(cfg, state: dict) -> None:
    """A diagram's arrows, resolved against the vocabulary and parked as questions for a steward.

    Best effort, and deliberately: a run must not fail because a diagram could not be read or the queue
    could not be reached. The arrows are `storage_read_vsdx`'s own `connectors`, and the resolution —
    which box names a concept, which is ambiguous, which is a gap — belongs to `semantic_vocab_relation_
    candidates`, where it is pure and tested. Attempted only for a diagram, because the read costs a
    grant and a round trip."""
    # The NAME comes from the title, not from the pointer: a `collab://` handle ends in a Graph item id
    # with no extension (`collab://item/<driveId>/<itemId>`), so every collab-sourced artifact — which
    # is the whole pilot library — looked like "not a diagram" and this returned before it began.
    name = str(state.get("title") or "")
    if filetypes.kind_for(name) != "vsdx":        # the one input whose arrows are machine-readable
        return
    # ...and the REF is the one `_excerpt` already resolved. Storage cannot read a handle; passing one
    # raises, and this function's degrade-rather-than-fail `except` would swallow it — the same trap
    # `_excerpt`'s own docstring records paying for once.
    ref = str(state.get("content_ref") or state.get("pointer", {}).get("ref") or "")
    if not ref:
        print(f"[intake] {name}: no readable ref, so no relations proposed", flush=True)
        return
    try:
        parsed = await gateway.call(cfg, StorageTools.read_vsdx, {"ref": ref})
        arrows = (parsed or {}).get("connectors") or []
        if not arrows:
            return
        found = await gateway.call(cfg, SemanticTools.relation_candidates,
                                   {"arrows": arrows, "scheme": cfg.get("vocabulary", "")})
        for c in (found or {}).get("candidates") or []:
            await gateway.call(cfg, SemanticTools.relation_propose,
                               {"scheme": cfg.get("vocabulary", ""), "subject": c.get("subject", ""),
                                "predicate": c.get("predicate", ""), "object": c.get("object", ""),
                                "evidence": f"drawn on {name}"})
        gaps = (found or {}).get("gaps") or []
        print(f"[intake] {name}: {len((found or {}).get('candidates') or [])} relation(s) proposed, "
              f"{len(gaps)} box(es) the vocabulary cannot name{': ' + ', '.join(gaps[:5]) if gaps else ''}",
              flush=True)
    except Exception as e:                          # noqa: BLE001 — a diagram is evidence, not a gate
        # NAMED, because "the grant is missing" and "the diagram had no arrows" look identical in a log
        # that only says nothing happened — which is how a producer contributes nothing for weeks.
        why = "not granted" if "not exposed" in str(e) or "permission" in str(e).lower() else type(e).__name__
        print(f"[intake] no relations from {name} ({why}): {e}", flush=True)


def make_cfg(*, credential: str = "", mcp_url: str = "", traceparent: str = "", agents: dict | None = None,
             schemas: dict | None = None, doc_types: dict | None = None, threshold: float = 0.75,
             default_label: str = "", owners: OwnerMap | None = None, overlap_threshold: float = 0.85,
             subject_floor: float = 0.0, extract_first: bool = False, subject_ask_max: int = SUBJECT_ASK_MAX,
             vocabulary: str = "", tracer=None, root_ctx=None, run_id: str = ""):
    """The ONE config contract for every host of this process. Nothing below reads the environment.
    `agents` and `schemas` are keyed by agent KIND (`agents.SKILL`); an absent agent makes its step a
    pass-through. `extract_first` picks which reader supplies the SUBJECTS — the classifier shown the
    vocabulary, or the extractor shown none of it; the document TYPE comes from the classifier either
    way."""
    from lab.platform import config
    return {"headers": gateway.auth_headers(credential, traceparent), "mcp_url": mcp_url or config.GATEWAY_MCP_URL,
            "credential": credential, "agents": dict(agents or {}), "schemas": dict(schemas or {}),
            "doc_types": dict(doc_types or {}), "threshold": float(threshold), "default_label": default_label,
            "extract_first": bool(extract_first),
            "owners": owners or OwnerMap.empty(), "overlap_threshold": float(overlap_threshold),
            "subject_floor": float(subject_floor), "subject_ask_max": int(subject_ask_max),
            "vocabulary": vocabulary, "tracer": tracer, "root_ctx": root_ctx, "run_id": run_id}


# ------------------------------------------------------------------------------------------ helpers

def _label_of(pointer: dict) -> str:
    ident = pointer.get("ref") or pointer.get("handle") or pointer.get("itemId") or pointer.get("workItem") or ""
    return str(ident).rstrip("/").split("/")[-1]


async def _vocabulary(cfg: dict) -> list[dict]:
    """The concepts the classifier may CHOOSE from, read through the gateway at classification time.

    Shown rather than remembered: a document's subjects used to be free text the agent invented, which then had
    to match a concept's label exactly to become a link — so an honest synonym became a miss. A vocabulary small
    enough to show (the domain ontology is ~130 concepts, where a capability map is thousands) turns the step
    from guessing into choosing. A deployment with no vocabulary configured, or a read that fails, degrades to
    the old behaviour rather than failing the run: an unclassified record is worse than an unlinked one."""
    if not cfg.get("vocabulary"):
        return []
    try:
        got = await gateway.call(cfg, SemanticTools.concepts, {"scheme": cfg["vocabulary"], "kind": ""})
        return [{k: c.get(k) for k in ("id", "label", "definition", "module") if c.get(k)} for c in got or []]
    except Exception as e:                      # noqa: BLE001 — a vocabulary that cannot be read is not a gate
        print(f"[intake] vocabulary {cfg['vocabulary']} unreadable: {type(e).__name__}: {e}", flush=True)
        return []


def _describe(state: dict) -> str:
    """The index's descriptive text, spelled in ONE place (`catalog.describe`) from the LINKED concepts' labels —
    never the agent's raw terms — so a re-index from the catalog alone reproduces it exactly."""
    return describe(state.get("title") or _label_of(state["pointer"]), state.get("document_type") or "",
                    [l["label"] for l in state.get("linked") or []])


def _type_label(cfg, iri: str | None) -> str:
    return (cfg["doc_types"].get(iri or "") or {}).get("label") or (iri or "").rsplit("#", 1)[-1] or "unknown"


# -------------------------------------------------------------------------------------------- graph

def build_workflow(cfg):
    schemas = cfg.get("schemas") or {}
    classify_gate = validator_for(schemas["classifier"]) if schemas.get("classifier") else None
    extract_gate = validator_for(schemas["extractor"]) if schemas.get("extractor") else None
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
                    hints = {k: item.get(k) for k in ("path", "modified", "created", "size", "label", "author") if item.get(k)}
                except Exception as e:                  # noqa: BLE001 — a title is a convenience
                    hints = {"title_lookup": f"{type(e).__name__}: {e}"}
            title = title or _label_of(pointer)
            row = await gateway.call(cfg, SemanticTools.catalog_upsert, {
                "pointer": pointer, "title": title[:300], "produced_by": state.get("produced_by") or "",
                "context": state.get("context") or "", "source_kind": pointer.get("source", "")})
            state = state | {"iri": row["iri"], "title": title, "hints": hints,
                             "document_type": row.get("document_type") or "", "row": row,
                             "revised": bool(row.get("revised")), "previous_version": row.get("previous_version") or ""}
        await ctx.send_message(state)

    @executor(id="classify")
    async def classify(state: dict, ctx: WorkflowContext[dict]) -> None:
        """Type: a fact when a lab process produced it, else the classifier's suggestion at S. Subjects:
        label-matched into the vocabulary at X; misses parked as candidates. Owner and label are never
        guessed — the label is the site default at C when nothing better is known."""
        with gateway.node_span(cfg, "classify"):
            # Bound HERE, not in the branch below: a run with no classifier reads nothing, and a rendering
            # left unbound made the no-agent path raise rather than simply have nothing to record.
            suggestion, rendering = None, ""
            # READ ONCE, for both readers. The excerpt used to be fetched inside the classifier's branch,
            # which made the extractor depend on a classifier being configured for its own evidence.
            read: dict = {}
            excerpt, rendering = await _excerpt(cfg, state["pointer"],
                                                produced_by=state.get("produced_by") or "", out=read)
            state = state | {"content_ref": read.get("content_ref", "")}
            # WHAT EACH READER IS SHOWN. The facts about the artifact are common; the VOCABULARY and the
            # closed type set belong to the classifier alone. Handing them to the extractor would make the
            # inversion a second taxonomy-first call — every test still passing, because the schema
            # constrains only the OUTPUT. This split IS the inversion; it is not a tidying.
            facts = {"title": state["title"], "name": _label_of(state["pointer"]),
                     "path": (state.get("hints") or {}).get("path", ""),
                     "produced_by": state.get("produced_by") or "",
                     "hints": state.get("hints") or {}}
            if excerpt:                          # absent, not empty: the prompt must not read "" as "blank document"
                facts["excerpt"] = excerpt
            if cfg["agents"].get("classifier") and classify_gate is not None:
                brief = {**facts,
                         "document_types": [{"iri": k, **v} for k, v in cfg["doc_types"].items()],
                         "concepts": await _vocabulary(cfg)}
                if not excerpt:
                    # Four of the five causes announced themselves by RAISING; one returned "" quietly and
                    # cost a day. A degrade-by-design path must never be silent about degrading.
                    print(f"[intake] no excerpt for {state['pointer'].get('ref') or state['pointer'].get('handle')}: "
                          f"nothing readable came back", flush=True)
                suggestion = await run_gated(cfg["agents"]["classifier"], json.dumps(brief, ensure_ascii=False),
                                             step="classification", validator=classify_gate)
                # What the classifier was ASKED and what it ANSWERED, on one line. Six out-of-band
                # reconstructions of this brief returned no subjects while production returned four, and
                # nothing recorded the difference — a classification whose inputs are invisible can only
                # be argued about. Sizes and names, never the excerpt itself: a span and a log line are
                # not places for document content.
                print(f"[intake] classified {str(state.get('title'))[:48]!r} "
                      f"excerpt={len(brief.get('excerpt') or '')}ch concepts={len(brief.get('concepts') or [])} "
                      f"types={len(brief.get('document_types') or [])} -> "
                      f"type={(suggestion or {}).get('document_type') or '-'} "
                      f"subjects={(suggestion or {}).get('subjects')}", flush=True)
                # The schema pins the URN's SHAPE; the closed set is the fabric's. A type the fabric does not
                # know is not a suggestion, it is a hallucination — dropped here, named in the rationale.
                if suggestion.get("document_type") and suggestion["document_type"] not in cfg["doc_types"]:
                    suggestion["rationale"] = (f"[unknown type {suggestion['document_type']} dropped] "
                                               + str(suggestion.get("rationale") or ""))[:400]
                    suggestion["document_type"] = None
            subjects = list((suggestion or {}).get("subjects") or [])
            confidence = float((suggestion or {}).get("confidence") or 0.0)
            # EXTRACT-FIRST. The classifier keeps the document TYPE — a closed set of ten, where being
            # shown the options is appropriate — and the SUBJECTS come instead from a reader that was
            # shown no vocabulary at all. A term may be inferred; its evidence may not, so a span absent
            # from the excerpt takes its term with it.
            ungrounded, grounded_any, salience, extracted = 0, False, {}, False
            if cfg.get("extract_first") and cfg["agents"].get("extractor") and extract_gate is not None:
                extracted = True
                # `facts`, never `brief`: see the split above. The extractor is given the TEXT and what
                # the artifact IS, and nothing it could pick an answer from.
                got = await run_gated(cfg["agents"]["extractor"], json.dumps(facts, ensure_ascii=False),
                                      step="extraction", validator=extract_gate)
                terms = list((got or {}).get("terms") or [])
                kept = [x for x in terms if concepts.ground(str(x.get("evidence_span") or ""), excerpt)]
                ungrounded = len(terms) - len(kept)
                grounded_any = bool(kept)
                subjects = [str(x.get("term") or "") for x in kept]
                # How central the extractor found each term. Carried because the owner's card ranks by it:
                # a cap has to choose, and "the ones this document is most about" is the only ordering a
                # person would recognise. Absent is 0.0, which sorts last without being an error.
                salience = {str(x.get("term") or ""): float(x.get("salience") or 0.0) for x in kept}
                print(f"[intake] extracted {len(terms)} term(s), {len(kept)} grounded, "
                      f"{ungrounded} discarded", flush=True)
            # A subject the model is GUESSING at never becomes a link. The excerpt fixed what the
            # classifier can SEE; this is what it does when it sees nothing that fits, and the two are
            # different defects: measured 9 Oct 2026, minutes whose content had been read correctly were
            # still filed under `Clinical document` because the vocabulary is healthcare-shaped and
            # something always looks close. Absent is NOT zero — a classifier that declares no
            # per-subject confidence is trusted exactly as before, or the floor becomes an outage.
            # A subject MISSING from the declaration is a guess, not a generosity: the schema requires the
            # number, so its absence means the model declined to stand behind that subject. Optional, it
            # was simply never emitted — the floor was inert while every test passed (9 Oct 2026).
            floor, declared = cfg.get("subject_floor") or 0.0, (suggestion or {}).get("subject_confidence") or {}
            # ONLY the classifier's own subjects. The floor reads `subject_confidence`, which the CLASSIFIER
            # declares for the terms IT chose — an extracted term is not a key in it, so every one scored
            # 0.0 and a shipped floor of 0.6 dropped the lot. `vocab_link` was then called with an empty
            # list, which RETRACTS every rung-X subject on the record: the estate-wide erasure the blind
            # guard exists to stop, arriving through a door the guard cannot see, because these terms
            # grounded perfectly well before the floor ate them. Salience is the extract-first dial and it
            # is a DIFFERENT QUANTITY — how central a term is to the document, not how sure a model is of a
            # match — which is why it is not folded into this one.
            unsure = [t for t in subjects if float(declared.get(t, 0.0)) < floor] if floor and not extracted else []
            if unsure:
                subjects = [t for t in subjects if t not in unsure]
                print(f"[intake] dropped {len(unsure)} subject(s) below the {floor} floor: {unsure}", flush=True)
            # HOW this run read the artifact, recorded BEFORE anything is linked from it, and at X because it
            # is derived from which reader answered rather than suggested by anybody. A reader weighing a
            # concept's evidence asks the record, not each assertion: one run reads one excerpt, so every
            # term it grounds shares this rendering.
            # Monotone downward against what the record already holds — see `_weakest`. Read off the ROW,
            # because a reclassify starts a fresh state and would otherwise compare against nothing.
            rendering = _weakest(str((state.get("row") or {}).get("rendering") or ""), rendering)
            if rendering and rendering != (state.get("row") or {}).get("rendering"):
                await gateway.call(cfg, SemanticTools.catalog_assert, {
                    "iri": state["iri"], "field": "rendering", "value": rendering,
                    "rung": EXTRACTED, "method": "read-as"})
                state = state | {"rendering": rendering}
            if not state.get("document_type") and (suggestion or {}).get("document_type"):
                await gateway.call(cfg, SemanticTools.catalog_assert, {
                    "iri": state["iri"], "field": "document_type", "value": suggestion["document_type"],
                    "rung": SUGGESTED, "method": "classifier-agent", "confidence": confidence})
                # The ONE facet a reclassify may still raise a card for. Note the branch condition: a type is
                # only ever asserted onto a record that has NONE, so re-reading a typed record cannot change
                # it and will ask nobody — a model's second opinion never displaces a decided type.
                state = state | {"document_type": suggestion["document_type"], "type_rung": SUGGESTED,
                                 "type_changed": True}
            else:
                # A prior answer can go STALE, and the gate had no way to say so: measured 9-10 Oct 2026, a
                # BRS was confirmed as the sentinel `No type fits` when genuinely no type fitted, the scheme
                # then GAINED `requirements-specification`, the file was edited so the record went back to
                # pending, and the classifier read it correctly — but the card rebuilt its item from the
                # recorded value alone, so the better answer never reached the person, who confirmed the
                # stale one again. The suggestion is CARRIED (never asserted: a decided type is a person's
                # to change) so the card can offer it beside the default. Not for a type the producing
                # PROCESS decided: that is deterministic, and a second opinion on it would be noise on every
                # minutes card.
                recorded, produced = state.get("document_type") or "", state.get("produced_by") or ""
                by_process = bool(produced) and (cfg["doc_types"].get(recorded) or {}).get("produced_by") == produced
                proposed = (suggestion or {}).get("document_type") or ""
                state = state | {"type_rung": CONSTRUCTED if recorded else "",
                                 "suggested_type": "" if by_process or proposed == recorded else proposed}
            linked, missed, conflicts, retracted = [], [], [], []
            cited, cited_missed = [], []
            # `if subjects` would skip the call on an empty answer, and `vocab_link` is where supersession
            # happens — so a record could only ever GAIN subjects and "nothing applies" was unrepresentable
            # (measured 9 Oct 2026: the classifier returned none for a bake-off transcript and the record
            # kept four links from the run before). An empty answer from a classifier that RAN is an
            # opinion; a run where NEITHER reader ran has none, which is why the guard tests whether a
            # reader answered and not whether the list is empty.
            # "I could not ground anything" is NOT "I grounded nothing". `vocab_link` replaces the
            # extracted subject set wholesale, and `_excerpt` returns "" on ANY failure — a missing
            # grant, a provider outage, an empty artifact. Composed naively, one storage blip means zero
            # terms, an empty link call, and every rung-X subject on that record retracted; swept across
            # the estate that erases the subject graph. So a run that extracted terms and grounded NONE
            # of them leaves the prior set standing and says so.
            # "I could not READ it" and "I read it and found nothing" are different answers, and only the
            # second may replace a subject set. The condition used to test `ungrounded > 0`, which an
            # extractor shown no text does not satisfy: it honestly answers `{"terms": []}` (schema-valid,
            # no minItems), so nothing was ungrounded, nothing grounded, and the guard read it as an
            # opinion — emptying the set and retracting every rung-X subject on the record. A run with no
            # excerpt has no opinion, whatever the model said.
            blind = bool(cfg.get("extract_first")) and not grounded_any and (ungrounded > 0 or not excerpt)
            if blind:
                why = f"{ungrounded} term(s) and nothing grounded" if ungrounded else "nothing readable to extract from"
                print(f"[intake] {why} — leaving the subjects as they are rather than retracting them", flush=True)
            # EITHER reader having run is an opinion. The gate used to test the classifier alone, which was
            # right while the classifier was the only source of subjects and became wrong the moment the
            # extractor supplied them: an extractor-only run grounded its terms and linked none of them,
            # silently. `extracted` is the extract-first half of the same question.
            if (suggestion is not None or extracted) and not blind:
                out = await gateway.call(cfg, SemanticTools.vocab_link, {"iri": state["iri"], "terms": subjects})
                linked, missed = out.get("linked") or [], out.get("missed") or []
                # What a RE-READ took back: subjects an earlier pass extracted that this one no longer
                # stands behind. Carried on the run because a re-classification whose removals are invisible
                # is indistinguishable from one that did nothing.
                retracted = out.get("retracted") or []
                # Subjects a person already said this record is NOT about. Named on the run, because a
                # term that matched and was suppressed is invisible otherwise — it looks like the
                # classifier simply stopped finding it.
                if out.get("excluded"):
                    print(f"[intake] {len(out['excluded'])} subject(s) suppressed by an owner's answer: "
                          f"{out['excluded']}", flush=True)
                # A term the vocabulary gives TWO meanings is neither linked nor missed: it is a steward's
                # decision. Carried on the run so a person reading it can see that two terms went to a
                # steward — without this it is invisible everywhere except the curated graph.
                conflicts = out.get("conflicts") or []
                for term in missed:
                    # TIER 2. No LABEL matched this term, but a DEFINITION may: ask what it MEANS before
                    # proposing to invent a concept for it. Measured 17 Oct 2026, ZERO of 30 terms on real
                    # prose matched a label — the extractor says "dispense confirmation callback" and the
                    # vocabulary says `Dispense` — so without this every one of them would become a
                    # proposal for a concept the fabric already holds.
                    #
                    # The two questions cost a steward very different amounts: "is this another word for
                    # X?" is seconds, and "what does this mean and where does it sit?" is not. Asking the
                    # expensive one by default is how 45 terms became 58 cards.
                    alias_of = ""
                    try:
                        found = await gateway.call(cfg, SemanticTools.concept_match,
                                                   {"term": term, "scheme": cfg.get("vocabulary", "")})
                        found = found if isinstance(found, dict) else {}
                        alias_of = str(found.get("concept") or "")
                    except Exception as e:                   # noqa: BLE001 — a suggestion, never a gate
                        # The term still reaches the register: an unavailable tier means the steward is
                        # asked the expensive question, not that the word is lost.
                        print(f"[intake] no concept match for {term[:40]!r}: {type(e).__name__}", flush=True)
                    # `proposed_for` is THIS artifact, and leaving it out quietly disabled two features that
                    # are implemented and tested in the service. `vocab_propose` keeps one row per term and
                    # accumulates the artifacts behind it, so without it every candidate carried no count and
                    # no provenance (measured 12 Oct 2026: 45 candidates, 0 with either). The frequency
                    # threshold then reads a count that is always null and asks about every term on first
                    # sight — 58 open concept-admission cards — and admission propagates to exactly
                    # `proposed_for`, so admitting a concept re-matched no document at all. The register was
                    # recording that a word was unknown while forgetting who had used it.
                    await gateway.call(cfg, SemanticTools.vocab_propose,
                                       {"label": term, "actor": "classifier-agent", "scheme": cfg.get("vocabulary", ""),
                                        "proposed_for": state["iri"], "alias_of": alias_of,
                                        "definition": f"proposed while classifying {state['title']}"})
            # WHAT THIS DIAGRAM SAYS CONNECTS. Its boxes are terms and its arrows are relations, so a
            # diagram is the one artifact that carries how the things a corpus is about are CONNECTED
            # rather than just which they are — and the vocabulary's ontology half has no other sharp
            # feeder. It proposes a QUESTION and never a relation: the arrow says two concepts connect
            # and not how, and a predicate the fabric invented would be an edge no author drew, which
            # the derived rung would then reason over as if somebody had.
            await _propose_relations(cfg, state)
            # WHAT THIS DOCUMENT CITES. Impact walks INBOUND over `references`, and the only producer of
            # that edge was a synthesised draft pointing back at its source — so an authored document that
            # cited another in prose produced nothing, and impact over it returned nothing and always
            # would have (measured 12 Oct 2026 on three eRx documents citing each other by name).
            # Search PROPOSES and a pure rule DISPOSES: `citations.resolve` links only an unambiguous
            # match and drops the rest, because a wrong edge puts a document inside the blast radius of a
            # change that cannot affect it and nothing on screen would say so. Rung X — read out of the
            # text, confirmed by nobody.
            for cite in (suggestion or {}).get("references") or []:
                try:
                    found = await gateway.call(cfg, SemanticTools.search, {"text": cite, "limit": 5})
                    rows = found if isinstance(found, list) else (found or {}).get("results") or []
                    target = citations.resolve(cite, [{"iri": r.get("iri"), "title": r.get("title")}
                                                      for r in rows], exclude=state["iri"])
                except Exception as e:                       # noqa: BLE001 — a citation is evidence, not a gate
                    print(f"[intake] citation {cite[:48]!r} unresolved: {type(e).__name__}", flush=True)
                    continue
                if not target:
                    cited_missed.append(cite)
                    continue
                await gateway.call(cfg, SemanticTools.edge_assert,
                                   {"subject": state["iri"], "predicate": REFERENCES, "object": target,
                                    "rung": EXTRACTED, "method": "cited-in-content"})
                cited.append({"citation": cite, "object": target})
            # owner and label are LOOKED UP at C (FR-2.2.2): the item's own label, else the site default; the owner
            # map, else the run's requester, else the item's author — never the model. Unresolved → the review asks.
            hints = state.get("hints") or {}
            label, how = (hints.get("label"), "item-label") if hints.get("label") else (cfg.get("default_label"), "site-default")
            if label:
                await gateway.call(cfg, SemanticTools.catalog_assert, {
                    "iri": state["iri"], "field": "sensitivity_label", "value": label, "rung": CONSTRUCTED, "method": how})
            owner, method = cfg["owners"].resolve(state["pointer"], produced_by=state.get("produced_by") or "",
                                                  requester=state.get("requester") or "", path=str(hints.get("path") or ""),
                                                  author=str(hints.get("author") or ""))
            if owner:
                await gateway.call(cfg, SemanticTools.catalog_assert, {
                    "iri": state["iri"], "field": "owner", "value": PERSON + owner, "rung": CONSTRUCTED, "method": method})
            state = state | {"subjects": subjects, "linked": linked, "missed": missed, "owner": owner,
                             "conflicts": conflicts, "retracted": retracted, "unsure": unsure,
                             # how many readings were dropped for want of evidence — a reviewer judging a
                             # thin set of subjects should know whether the reader said little or was
                             # disbelieved, and they are very different things
                             "ungrounded": ungrounded, "salience": salience,
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
            state = state | {"impact": [{"iri": h.get("iri"), "title": h.get("title"), "rung": h.get("rung"),
                                         "state": h.get("state"), "owner": h.get("owner")}
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
                    # `produced_by` is THIS process: the fabric drafted it. The source record's upsert
                    # (above) passes the field and this one did not, so every synthesised draft was
                    # catalogued as an orphan — 66 of them live, measured 12 Oct 2026. An orphaned lab
                    # record is precisely what `fabric_hygiene.is_working_file` read as a working file, so
                    # the fabric's own products sat one catalogue-wide hygiene pass from being withdrawn.
                    # A record that cannot say what made it cannot be told from somebody's leftovers.
                    row = await gateway.call(cfg, SemanticTools.catalog_upsert, {
                        "pointer": {"source": "lab", "ref": dref}, "title": rec["title"][:300],
                        "produced_by": ARTIFACT_INTAKE.name,
                        "context": state.get("context") or "", "source_kind": "lab"})
                    await gateway.call(cfg, SemanticTools.catalog_assert, {
                        "iri": row["iri"], "field": "document_type", "value": DECISION_RECORD,
                        "rung": CONSTRUCTED, "method": "drafted-by-fabric"})
                    await gateway.call(cfg, SemanticTools.edge_assert, {
                        "subject": row["iri"], "predicate": REFERENCES, "object": state["iri"],
                        "rung": CONSTRUCTED, "method": "drafted-from"})
                    await gateway.call(cfg, SemanticTools.edge_assert, {          # what rung D derives the context from
                        "subject": row["iri"], "predicate": SYNTHESISED_FROM, "object": state["iri"],
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
                # only a PUBLISHED twin is a duplicate to adjudicate (FR-3.3.1); a pending one is another draft
                overlap_ = [{"iri": n.get("iri"), "title": n.get("title"), "score": n.get("score")}
                            for n in (near or []) if n.get("state") == "published"
                            and float(n.get("score") or 0) >= cfg["overlap_threshold"]]
            except Exception as e:                      # noqa: BLE001 — overlap is evidence, not a gate
                note = f"{type(e).__name__}: {e}"
            state = state | {"overlap": overlap_, "overlap_note": note}
        await ctx.send_message(state)

    @executor(id="ask_review")
    async def ask_review(state: dict, ctx: WorkflowContext[dict]) -> None:
        """The owner's question, and the end of the run. `association` when the record has no context to
        stand under; `draft-review` otherwise. Approving releases `artifact_publish`.

        A RECLASSIFY asks nobody. Re-reading the back catalogue would otherwise raise a card per record —
        a SECOND card for records whose first is still open — and the queue would become unusable at the
        moment its contents finally became worth reading (measured 7 Oct 2026: ~90 records classified from
        their file names, ~40 approvals already waiting). Nothing is lost by staying quiet: subjects live at
        rung X whichever pass produced them, so whoever opens the existing card sees the better ones. The
        document TYPE is the exception — that is a facet a person confirms, and letting a sweep change it
        silently would promote a model's second opinion over somebody's decision."""
        if state.get("reason") == "reclassify" and not state.get("type_changed"):
            # Quiet, but NOT silent: the run still reports what it did, because a re-classification whose
            # outcome nobody can see is the instrument problem this lab keeps meeting. `approval_id` is
            # empty, which is what says no card was raised.
            with gateway.node_span(cfg, "ask_review"):
                row = await gateway.call(cfg, SemanticTools.catalog_get, {"iri": state["iri"]})
                counts: dict[str, int] = {}
                for link in (row or {}).get("links") or []:
                    counts[link["rung"]] = counts.get(link["rung"], 0) + 1
                await ctx.yield_output({"artifact_iri": state["iri"], "approval_id": "", "draft_refs": [],
                                        "rung_counts": counts, "kind": "", "reclassified": True,
                                        "association": state.get("association"),
                                        "summary": {"subjects": len(state.get("linked") or []),
                                                    "candidates_proposed": len(state.get("missed") or []),
                       # named, not counted: a floor nobody can see is a floor nobody can tune
                       "dropped_unsure": state.get("unsure") or [],
                                                    "retracted": len(state.get("retracted") or [])}})
            return
        with gateway.node_span(cfg, "ask_review"):
            type_samples = [f"suggested: {_type_label(cfg, state.get('document_type'))}"
                            + (f" ({state['confidence']:.2f})" if state.get("type_rung") == SUGGESTED else " (fact)"),
                            state.get("rationale") or ""]
            # Both readings, in words a reviewer can act on — see `classify`: the recorded value stays the
            # default, and the rationale that follows is this run's, which is why the offer goes directly
            # above it. Nothing is added when the two agree, or a card grows a line that says nothing.
            if state.get("suggested_type"):
                type_samples.insert(1, f"this now reads as: {_type_label(cfg, state['suggested_type'])} "
                                       f"({state['confidence']:.2f}) — answer it if it is right; "
                                       f"{_type_label(cfg, state.get('document_type'))} stays the default")
            items = [{"label": "document_type", "samples": type_samples,
                       # Every type the fabric knows, by the label `DOC_TYPES.resolve` accepts. The samples
                       # beside them carry the suggestion and its score, which is not an answer.
                       "choices": sorted(v.get("label", "") for v in cfg["doc_types"].values() if v.get("label"))}]
            asked_subjects, held_back = _subject_items(state, cfg.get("subject_ask_max") or SUBJECT_ASK_MAX)
            items += asked_subjects
            if not state.get("owner"):
                items.append({"label": "owner", "samples": ["unresolved: no owner-map rule, no requester, no author — type the owner's email"]})
            if state.get("overlap"):
                items.append({"label": "overlap",
                              "choices": ["keep"] + [f"duplicate-of:{o['iri']}" for o in state["overlap"]],
                              "samples": [f"{o['title']} ({o['score']:.2f}) — answer duplicate-of:{o['iri']} to withdraw this record as its duplicate"
                                          for o in state["overlap"]] + ["or answer keep"]})
            kind = ApprovalKind.DRAFT_REVIEW
            if not state.get("context"):
                kind = ApprovalKind.ASSOCIATION
                items.append({"label": "context",
                              # The context keys ALONE, with the score beside them rather than inside
                              # them: "project:alpha (0.92)" was offered as a pick and accepted, and a
                              # rung-H association was written under a context that does not exist.
                              "choices": [str(c["context"]) for c in state.get("candidates") or []] + ["none"],
                              "samples": [f"{c['context']} ({c['score']:.2f})" for c in state.get("candidates") or []]
                              or ["no candidate: type the delivery context as <kind>:<id>, or 'none'"]})
            summary = {"impact": len(state.get("impact") or []), "overlap": len(state.get("overlap") or []),
                       "drafts": len(state.get("drafts") or []), "subjects": len(state.get("linked") or []),
                       "candidates_proposed": len(state.get("missed") or []),
                       # a term the vocabulary gives two meanings: neither linked nor proposed, a steward's call
                       "terms_for_a_steward": len(state.get("conflicts") or []),
                       # NAMED, not counted: a floor nobody can see is a floor nobody can tune, and the
                       # reviewer is the person best placed to say the model was right to hesitate
                       "dropped_unsure": state.get("unsure") or [],
                       # ...and what the run took AWAY. `vocab_link` replaces the extracted subject set
                       # wholesale, so a re-read silently retracts whatever it no longer stands behind.
                       # The reclassify branch reported this on the run and the card did not, which left
                       # the one person asked to confirm the record as the only one not told. Named for
                       # the same reason as `dropped_unsure`: a reviewer can only object to a removal
                       # they can see.
                       "retracted": state.get("retracted") or [],
                       # how many readings were dropped for want of evidence — a reviewer judging a thin
                       # set of subjects should know whether the reader said little or was disbelieved
                       "ungrounded": state.get("ungrounded") or 0}
            cont = Continuation(process=ARTIFACT_PUBLISH.name, inputs={"artifact_iri": state["iri"]},
                                requester=state.get("requester") or "")
            artifacts = {f'{d["id"]} {d["title"][:60]}'.strip(): d["ref"] for d in state.get("drafts") or []}
            asked = await gateway.call(cfg, ApprovalTools.ask, {
                "kind": kind.value,
                "subject": f'{state["title"]} — {"where does this belong?" if kind is ApprovalKind.ASSOCIATION else "review the record"}',
                # The subjects NOT asked about, by name. A cap that said "and 2 more" would leave a person
                # unable to tell a subject that was held back from one the fabric never found.
                "prompt": (f"Also about: {', '.join(held_back)} (unchanged). " if held_back else "")
                          + (f"NEW VERSION {state['pointer'].get('version', '')} of a record already reviewed "
                           f"(previous version {state.get('previous_version') or '?'}) — review it again. "
                           if state.get("revised") else "") + PROMPT_REVIEW + f" Summary: {json.dumps(summary)}.",
                "items": items, "fields": ["value"], "continuation": cont.to_dict(),
                "artifacts": artifacts, "requester": state.get("requester") or "", "process": PROCESS})
            # A NEW VERSION that published records reference: tell their owners (FR-5.3.2) — a notice through the
            # same gate, so every channel carries it and nothing is released by acknowledging it.
            notice_id = ""
            affected = [h for h in state.get("impact") or [] if state.get("revised") and h.get("state") == "published"]
            if affected:
                told = await gateway.call(cfg, ApprovalTools.ask, {
                    "kind": ApprovalKind.IMPACT_NOTICE.value, "answer_required": False,
                    "subject": f'{state["title"]} changed — {len(affected)} published record(s) reference it',
                    "prompt": (f'A new version ({state["pointer"].get("version", "?")}) of "{state["title"]}" was recorded. '
                               "These published records reference it and may need a look; acknowledge when seen."),
                    "items": [{"label": h["iri"], "samples": [f'{h.get("title") or h["iri"]} · owner {str(h.get("owner") or "?").rsplit(":", 1)[-1]}']}
                              for h in affected],
                    "fields": ["value"], "requester": state.get("requester") or "", "process": PROCESS})
                notice_id = told.get("request_id") or ""
            row = await gateway.call(cfg, SemanticTools.catalog_get, {"iri": state["iri"]})
            counts: dict[str, int] = {}
            for link in (row or {}).get("links") or []:
                counts[link["rung"]] = counts.get(link["rung"], 0) + 1
            out = {"artifact_iri": state["iri"], "approval_id": asked.get("request_id"),
                   "draft_refs": [d["ref"] for d in state.get("drafts") or []], "rung_counts": counts,
                   "kind": kind.value, "association": state.get("association"), "summary": summary,
                   "notice_id": notice_id}
        await ctx.yield_output(out)

    return (WorkflowBuilder(start_executor=identify)
            .add_chain([identify, classify, associate, impact, synthesise, overlap, ask_review]).build())


async def run_workflow(cfg, inputs: dict):
    return await gateway.run_graph(cfg, build_workflow, inputs, what="artifact intake", required=REQUIRED_TOOLS)


__all__ = ["REQUIRED_TOOLS", "PROCESS", "DECISION_RECORD", "make_cfg", "build_workflow", "run_workflow"]
