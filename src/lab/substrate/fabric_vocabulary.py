"""The steward's gate: a PERSON's answer about the VOCABULARY, applied as curation.

The sibling of `fabric_curator`, which applies a person's answer about one ARTIFACT — same stream, same runner,
same registry, so a second domain is an applier and one `register` line rather than a branch in the runner.

What it is for. A document uses a term the vocabulary has no concept for, and the fabric parks it as a
candidate; or a term means two things and no document can honestly be linked to it. Neither is a question a
model may settle: admitting a concept widens what every future document is classified against, and choosing
between two meanings narrows it. Both are `SemanticTools.PROMOTE`, the grant that reaches no workload — so the
answer is applied HERE, by the continuation runner, with the channel-authenticated human as the actor.

`plan` is pure: given the approval's payload and the person's answer it says which tool calls to make; `apply`
makes them. Four answers, because the honest ones are not two: **admit** the concept, say it **existing** under
another name (the commonest correction, and a second concept for it would be the duplicate the vocabulary
exists to prevent), **decline** it, or **settle** an ambiguity by naming the meaning to keep.
"""
from __future__ import annotations

import json

from lab.core.semantic.fabric.service import concept_id_for
from lab.platform import config
from lab.core.semantic.fabric.ontology import SUBJECT
from lab.core.semantic.fabric.rungs import EXTRACTED
from lab.platform.contracts import ApprovalKind, ApprovalTools, SemanticTools, answer_value
from lab.substrate import answer_appliers, fabric_gateway

KINDS = (ApprovalKind.CONCEPT_ADMISSION.value,)
#: what a steward may answer. `settle` belongs to a conflict; the other three to a candidate.
DECISIONS = ("admit", "existing", "decline", "settle")
METHOD = "steward-review"


def applies_to(kind: str) -> bool:
    return str(kind or "") in KINDS


def _one(answer: dict, label: str, default: str = "") -> str:
    entry = (answer or {}).get(label)
    return answer_value(entry) if entry else default


def question(payload: dict) -> list[dict]:
    """The items a person is asked, ONE THING PER LABEL.

    `contracts.answer_value` refuses two fields under one label, so a question that bundled the definition and
    the module would be unanswerable on every surface at once — and the completeness gate, the review app's
    form and the Teams card all stay generic because no question is special."""
    if payload.get("concepts"):                       # an ambiguity: which meaning survives
        return [{"label": "decision", "samples": [f"settle — or decline to leave {payload.get('term')!r} ambiguous"]},
                {"label": "keep", "samples": [f"{c} — the meaning to keep; the other is superseded and still resolves"
                                              for c in payload["concepts"]]}]
    label = str(payload.get("label") or "")
    return [
        {"label": "decision",
         "samples": [f"admit — put {label!r} in {payload.get('scheme')!r}; "
                     "existing — it is already there under another name; decline — it is not a concept",
                     f"proposed by {payload.get('proposed_by') or 'a run'}"]},
        {"label": "concept_id",
         "samples": [f"the id it takes, joined on by every consumer (default {concept_id_for(label)})",
                     "for 'existing': the id it already has"]},
        {"label": "definition", "samples": [f"what {label!r} means, in one sentence"]},
        {"label": "module", "samples": ["the part of the vocabulary it belongs to"]},
        {"label": "broader", "samples": ["the concept it sits under, by id — or leave it at the top"]},
    ]


def _batch_plan(candidates: list[dict], answer: dict, actor: str) -> list[tuple[str, dict]]:
    """One verdict per TERM, from the one card a steward triaged. Pure.

    `admit` accepts the parked candidate as it stands — the batch card does not ask for an id, a
    definition or a parent, because eight terms times five fields is forty fields and nobody triages
    forty. A term that deserves that detail gets the single-term card instead.

    `decline` is RECORDED, not merely left on the approval: the reconciler's "already asked" memory is a
    set in the process, so a restart used to re-ask everything a steward had just dismissed — measured
    10 Oct 2026, 71 open cards became 101 in one afternoon while nobody decided anything."""
    by_iri = {str(c.get("iri") or ""): c for c in candidates}
    calls: list[tuple[str, dict]] = []
    for label, entry in (answer or {}).items():
        candidate = by_iri.get(label)
        if candidate is None:
            raise ValueError(f"{label!r} is not one of the terms on this card")
        verdict = answer_value(entry).strip()
        head, _, target = verdict.partition(":")
        head = head.strip().lower()
        if head == "decline":
            calls.append((SemanticTools.vocab_decline,
                          {"candidate": label, "actor": actor, "reason": f"a steward declined {candidate.get('label')!r}"}))
        elif head == "existing":
            if not target.strip():
                raise ValueError(f"{verdict!r} names no concept — answer 'existing:<concept id>'")
            calls.append((SemanticTools.vocab_amend,
                          {"concept_id": target.strip(), "scheme": str(candidate.get("scheme") or ""),
                           "alt": str(candidate.get("label") or ""), "actor": actor,
                           "reason": f"a steward said this term means {target.strip()}"}))
        elif head == "admit":
            calls.append((SemanticTools.promote, {"subject": label, "actor": actor, "method": METHOD}))
        else:
            raise ValueError(f"{verdict!r} is not admit, existing:<id> or decline")
    return calls


def plan(payload: dict, answer: dict, actor: str) -> list[tuple[str, dict]]:
    """The calls that make the vocabulary say what the steward said. Pure."""
    if not actor:
        raise ValueError("a curation decision names the person: actor is required")
    # A BATCH is recognised by what the card CARRIES, never by a flag somebody must remember to set: the
    # asker put the terms in `context`, so an answer keyed on them is a batch and anything else is not.
    facts = payload.get("context") or payload
    batch = facts.get("candidates") if isinstance(facts, dict) else None
    if batch:
        return _batch_plan(list(batch), answer, actor)
    payload = facts
    decision = _one(answer, "decision").strip().lower()
    if not decision:
        raise ValueError("the steward's answer carries no decision")
    if decision not in DECISIONS:
        raise ValueError(f"{decision!r} is not one of {', '.join(DECISIONS)}")
    scheme = str(payload.get("scheme") or "")
    if not scheme:
        raise ValueError("the question names no scheme, and a concept with no home cannot be looked up")

    if decision == "decline":
        return []                                     # recorded on the approval; the vocabulary is untouched

    if decision == "settle":
        keep = _one(answer, "keep")
        options = list(payload.get("concepts") or [])
        if keep not in options:
            raise ValueError(f"{keep!r} is not one of the meanings in question: {', '.join(options)}")
        term = str(payload.get("term") or "")
        return [(SemanticTools.vocab_retire,
                 {"concept_id": other, "scheme": scheme, "resolves_to": keep, "actor": actor,
                  "reason": f"a steward kept {keep} for {term!r}"})
                for other in options if other != keep]

    label = str(payload.get("label") or "")
    if decision == "existing":
        # NOT a second concept: the term becomes another way of saying the one that is already there, so the
        # next document using it is linked instead of proposing the same candidate again.
        return [(SemanticTools.vocab_amend,
                 {"concept_id": _one(answer, "concept_id"), "scheme": scheme, "alt": label, "actor": actor,
                  "reason": f"a steward said this term means {_one(answer, 'concept_id')}"})]

    # admit: park the steward's OWN candidate and accept it, so what is admitted is what they answered — the
    # asker's parked candidate carries the model's guess at the definition, and the id may be corrected here.
    parked = {"label": label, "actor": actor, "scheme": scheme,
              "concept_id": _one(answer, "concept_id") or concept_id_for(label),
              "definition": _one(answer, "definition"), "module": _one(answer, "module"),
              "broader": _one(answer, "broader")}
    return [(SemanticTools.vocab_propose, {k: v for k, v in parked.items() if v}),
            (SemanticTools.promote, {"actor": actor, "method": METHOD})]


PROMPT = ("The vocabulary the fabric classifies documents against needs a decision only a person can make. "
          "Answer each item; what you decide is applied in your name and takes effect for every document "
          "classified from then on.")


BATCH_PROMPT = ("Triage the terms documents have asked for and the vocabulary has no concept for. "
                "For each: ADMIT it, say it ALREADY EXISTS under a concept you name, or DECLINE it. "
                "A decline is remembered — the term will not be asked about again.")


def batch_question(candidates: list[dict]) -> list[dict]:
    """ONE item per term, ONE word per item — the shape the speaker card proved (the meeting owner tags N
    speakers on one card, so a steward triages N terms on one).

    Keyed on the candidate IRI, not the label: `check_answer` keys the answer on the item label and
    requires each exactly once, and two spellings of one word would collide. The LABEL a person reads is
    in the samples, with the evidence they triage on — how many documents asked, which is the whole point
    of counting.

    Deliberately NOT the five fields the single-term card asks (decision, id, definition, module,
    broader): eight terms would be forty fields, and nobody triages forty fields. The detailed form stays
    for a term that deserves care; this one asks only what volume needs."""
    out = []
    for c in candidates:
        label = str(c.get("label") or "")
        asked = c.get("proposals")
        evidence = f"asked for by {asked} documents" if asked else "asked for by an earlier run"
        out.append({"label": str(c.get("iri") or ""), "samples": [
            f"{label!r} — {evidence}, for {c.get('scheme') or 'the vocabulary'}",
            f"admit — add it as a concept (id {concept_id_for(label)}) \u00b7 "
            f"existing:<id> — it is another name for a concept already there \u00b7 "
            "decline — it is not a concept, and nobody will be asked again"]})
    return out


def _unanswered(candidate: dict) -> bool:
    """Not yet put to a steward. `asked` is the register's own `fab:InReview`, so it survives a restart."""
    return not candidate.get("asked")


def _wanted_enough(candidate: dict, threshold: int) -> bool:
    """Whether this term has been asked for often enough to be worth a steward's attention.

    `proposals` is how many DISTINCT artifacts used the word. A term met once is usually somebody's
    phrasing rather than a gap in the vocabulary, and asking about every one of them buries the few that
    matter — the same way an undecided backlog buries a channel.

    A candidate from BEFORE the count existed carries none, and is always asked about: reading a missing
    count as zero would silence the whole back catalogue the moment the threshold landed."""
    proposals = candidate.get("proposals")
    return proposals is None or int(proposals) >= threshold


async def ask_open(*, call=None, seen: set[str] | None = None, limit: int = 10,
                   threshold: int | None = None, batch: bool = True) -> list[dict]:
    """Ask a steward about what the vocabulary cannot answer: terms it has no concept for, and words it gives
    two meanings. Returns the approvals raised.

    Nothing else raises this question, so this is what makes the gate reachable. `seen` is the set already
    asked about — asking the same conflict every sweep would bury the approvals that need somebody, exactly as
    an undecided backlog does to a channel, and a conflict stays open until a person answers it."""
    go = call or fabric_gateway.call
    # A caller may still pass `seen` to add to what the GATE knows — the reconciler no longer does, and
    # that parameter exists now only for a driver narrowing one tick's work, never as the memory.
    # The REGISTER says what has been asked (`asked`, from `fab:InReview`), because a set in this process
    # forgot every open question on restart and raised a second card for the same terms. `seen` remains for
    # a caller narrowing one tick's work, and is never the memory.
    seen = set() if seen is None else set(seen)
    conflicts, candidates = [_read(x) for x in await go([(SemanticTools.vocab_conflicts, {}),
                                                        (SemanticTools.vocab_candidates, {})])]
    # filter THEN slice: slicing first means that once the first `limit` conflicts have been asked about,
    # the next one is never reached again for the life of the process
    fresh = _fresh(conflicts, seen, limit)
    raised = []
    # The threshold governs INTERRUPTION, not visibility: `vocab_candidates` still returns everything and a
    # steward may read the parked set whenever they choose. Bounding what is VISIBLE rather than what is
    # pushed would turn "parked" into "hidden", which is the defect this layer keeps producing in new places.
    want = config.FABRIC_CANDIDATE_THRESHOLD if threshold is None else threshold
    wanted = _fresh([c for c in candidates if _unanswered(c) and _wanted_enough(c, want)], seen, limit)
    if batch and wanted:
        # ONE card for every term at once. A card per candidate produced 101 open approvals against ~37 of
        # everything else (measured 10 Oct 2026), which buries the owner's questions and the steward's alike.
        got = (await go([(ApprovalTools.ask, {
            "kind": ApprovalKind.CONCEPT_ADMISSION.value,
            "subject": f"{len(wanted)} terms the vocabulary has no concept for",
            "prompt": BATCH_PROMPT, "items": batch_question(wanted), "fields": ["value"],
            # `proposed_for` rides the card so an ADMISSION can reach exactly the documents that asked
            # (FR-1.1.5) without re-reading the catalogue — see `_propagate`.
            "context": {"candidates": [{"iri": c.get("iri"), "label": c.get("label"),
                                        "scheme": c.get("scheme"),
                                        "proposed_for": list(c.get("proposed_for") or [])}
                                       for c in wanted]},
            "process": "documentation-fabric"})]))[0]
        got = json.loads(got) if isinstance(got, str) else (got or {})
        for c in wanted:                       # the REGISTER remembers, not this process
            await go([(SemanticTools.vocab_asked, {"candidate": str(c.get("iri") or ""),
                                                   "request_id": str(got.get("request_id") or "")})])
            seen.add(str(c.get("iri") or ""))
        raised += [{**c, "request_id": str(got.get("request_id") or "")} for c in wanted]
        wanted = []
    for c in wanted:
        payload = {"kind": ApprovalKind.CONCEPT_ADMISSION.value, "scheme": c.get("scheme", ""),
                   "label": c.get("label", ""), "candidate": c.get("iri", ""),
                   "proposed_by": c.get("proposed_by", "")}
        raised.append(await _ask(go, payload, seen, c,
                                 f'{c.get("label")!r} has no concept — should the vocabulary gain one?'))
    for c in fresh:
        payload = {"kind": ApprovalKind.CONCEPT_ADMISSION.value, "scheme": c.get("scheme", ""),
                   "term": c.get("term", ""), "concepts": list(c.get("concepts") or []),
                   "conflict": c.get("iri", "")}
        raised.append(await _ask(go, payload, seen, c,
                                 f'{c.get("term")!r} means more than one thing — which meaning is it?'))
    return raised


def _read(x):
    return (json.loads(x) if isinstance(x, str) else x) or []


def _fresh(rows: list, seen: set[str], limit: int) -> list:
    """Filter THEN slice: slicing first means that once the first `limit` rows have been asked about, the
    next one is never reached again for the life of the process."""
    return [r for r in rows if str(r.get("iri") or "") not in seen][:limit]


async def _ask(go, payload: dict, seen: set[str], row: dict, subject: str) -> dict:
    got = (await go([(ApprovalTools.ask, {
        "kind": ApprovalKind.CONCEPT_ADMISSION.value, "subject": subject, "prompt": PROMPT,
        "items": question(payload), "fields": ["value"], "context": payload,
        "process": "documentation-fabric"})]))[0]
    got = json.loads(got) if isinstance(got, str) else (got or {})
    seen.add(str(row.get("iri") or ""))
    return {**payload, "request_id": str(got.get("request_id") or "")}


#: Why a propagated link is EXTRACTED and not constructed: the term genuinely was in those documents'
#: content. That it had no concept on the day they were read is a fact about the VOCABULARY, not about
#: how the fabric came to know what the document says.
ADMISSION_METHOD = "vocabulary-admission"


def _propagate(candidate: dict, concept: str, actor: str) -> list[tuple[str, dict]]:
    """Link the documents that asked for a term to the concept a steward just admitted (FR-1.1.5).

    A concept admitted but not propagated changes nothing — the documents whose words prompted it stay
    unlinked until something re-reads them. Re-reading the whole catalogue to find them would be a model
    call per record for a handful of hits; the register already recorded WHICH records asked, which is why
    `vocab_propose` accumulates `proposedFor` instead of a bare count. So the propagation is exact, and
    cheap enough to be unconditional.

    A candidate from before that field existed names nobody and reaches nobody. That is honest: the
    register does not know who asked, and inventing a list would be worse than an empty one."""
    if not concept:
        return []
    return [(SemanticTools.edge_assert,
             {"subject": iri, "predicate": str(SUBJECT), "object": concept, "rung": EXTRACTED,
              "actor": actor, "method": ADMISSION_METHOD})
            for iri in (candidate.get("proposed_for") or [])]


async def apply(state: dict, actor: str, *, call=None) -> list[tuple[str, dict]]:
    """Apply one decided approval's answer. `call(calls)` is the gateway transport (injected by a test);
    returns the calls made. Raises on a refused write, so the runner records the failure on the approval."""
    go = call or fabric_gateway.call
    made: list[tuple[str, dict]] = []
    parked = ""
    # The candidate's own facts, carried on the approval as `context` — see `approvals_ask`. They were
    # passed as `payload` until 9 Oct 2026, which `approvals_ask` does not accept: every tick of the
    # reconciler logged one line and raised NO steward question for three weeks, while the candidates
    # kept accumulating. A tool that refuses an argument is not a tool that asked for a different one.
    payload = state.get("payload") or {}
    by_candidate = {str(c.get("iri") or ""): c
                    for c in ((payload.get("context") or {}).get("candidates") or [])}
    for tool, args in plan(payload, state.get("answer") or {}, actor):
        if tool == SemanticTools.promote and "subject" not in args:
            # the candidate THIS answer just parked, never the one the asker left lying there: promoting the
            # payload's candidate would admit the model's wording over the steward's
            if not parked:
                raise ValueError("nothing was parked to admit")
            args = {**args, "subject": parked}
        got = (await go([(tool, args)]))[0]
        if tool == SemanticTools.vocab_propose:
            got = json.loads(got) if isinstance(got, str) else (got or {})
            parked = str(got.get("iri") or "")
        made.append((tool, args))
        if tool == SemanticTools.promote:
            # The concept IRI is only known once the promotion has RUN, which is why this is here and not
            # in `plan`: a pure planner cannot name a thing the gate has not yet created.
            got = json.loads(got) if isinstance(got, str) else (got or {})
            candidate = by_candidate.get(str(args.get("subject") or "")) or {}
            for t, a in _propagate(candidate, str(got.get("iri") or ""), actor):
                await go([(t, a)])
                made.append((t, a))
    return made


# The runner asks the registry, not this module: a steward's vocabulary answers are applied before release.
answer_appliers.register(KINDS, apply)

__all__ = ["KINDS", "DECISIONS", "METHOD", "PROMPT", "applies_to", "question", "plan", "apply", "ask_open"]
