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


def plan(payload: dict, answer: dict, actor: str) -> list[tuple[str, dict]]:
    """The calls that make the vocabulary say what the steward said. Pure."""
    if not actor:
        raise ValueError("a curation decision names the person: actor is required")
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


async def ask_open(*, call=None, seen: set[str] | None = None, limit: int = 10) -> list[dict]:
    """Ask a steward about what the vocabulary cannot answer: terms it has no concept for, and words it gives
    two meanings. Returns the approvals raised.

    Nothing else raises this question, so this is what makes the gate reachable. `seen` is the set already
    asked about — asking the same conflict every sweep would bury the approvals that need somebody, exactly as
    an undecided backlog does to a channel, and a conflict stays open until a person answers it."""
    go = call or fabric_gateway.call
    seen = set() if seen is None else seen
    conflicts, candidates = [_read(x) for x in await go([(SemanticTools.vocab_conflicts, {}),
                                                        (SemanticTools.vocab_candidates, {})])]
    # filter THEN slice: slicing first means that once the first `limit` conflicts have been asked about,
    # the next one is never reached again for the life of the process
    fresh = _fresh(conflicts, seen, limit)
    raised = []
    for c in _fresh(candidates, seen, limit):
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
    for tool, args in plan(payload.get("context") or payload, state.get("answer") or {}, actor):
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
    return made


# The runner asks the registry, not this module: a steward's vocabulary answers are applied before release.
answer_appliers.register(KINDS, apply)

__all__ = ["KINDS", "DECISIONS", "METHOD", "PROMPT", "applies_to", "question", "plan", "apply", "ask_open"]
