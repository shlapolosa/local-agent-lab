"""Steward B's gate: a PERSON's answer about how concepts RELATE, applied as curation.

The sibling of `fabric_vocabulary`, which applies a person's answer about what the vocabulary CONTAINS —
same stream, same runner, same registry, so a second domain is an applier and one `register` line rather
than a branch in the runner.

WHY A SECOND STEWARD GATE. A vocabulary is a taxonomy plus the statements about how its concepts relate,
and only the first half had a queue. `broader` was settable once, at proposal time, and a typed relation
had no verb at all — so the half the DERIVED rung actually reasons over was the half no one could grow.
"A is about X, X relates to Y, B is about Y" is only answerable if somebody stood behind the middle step.

Neither producer may settle one. A diagram's arrow says two concepts connect and not how; a corpus
co-occurrence says they turn up together and not why. Both are evidence, and a relation entered on
evidence alone would be an edge no author drew — which the derivation would then reason over as if
somebody had.

`plan` is pure: given the card's questions and the person's answer it says which tool calls to make;
`apply` makes them. Four answers: **relate** it as proposed, **relate:<predicate>** when the question
carries none (an unlabelled arrow), make one concept **broader** than the other, or **decline** it so
both producers stop proposing it.
"""
from __future__ import annotations

import json

from lab.platform import config
from lab.platform.contracts import ApprovalKind, ApprovalTools, SemanticTools, answer_value
from lab.substrate import answer_appliers, fabric_gateway

KINDS = (ApprovalKind.CONCEPT_RELATION.value,)
#: what a steward may answer about one proposed relation
DECISIONS = ("relate", "broader", "decline")
METHOD = "steward-review"


def applies_to(kind: str) -> bool:
    return str(kind or "") in KINDS


def questions(payload: dict) -> list[dict]:
    """The relation questions one card carries. From `context`, where the asker put them — the same place
    the term card puts its candidates, and for the same reason: a triage brief cannot be read back."""
    facts = payload.get("context") or payload
    return list(facts.get("questions") or [])


def batch_question(rows: list[dict]) -> list[dict]:
    """ONE item per proposed relation, ONE word per item — the shape the term card proved.

    Keyed on the QUESTION's iri, not on the triple: `check_answer` keys the answer on the item label and
    requires each exactly once, and a triple rendered into a label would collide on case alone. What a
    person reads is in the samples, with the evidence they triage on; what they may answer is in
    `choices`, because a sample is an explanation and must never be selectable as an answer."""
    out = []
    for q in rows:
        pred = str(q.get("predicate") or "")
        reads = f"{q.get('subject')} --{pred or '?'}--> {q.get('object')}"
        verb = "relate" if pred else "relate:<predicate>"
        out.append({"label": str(q.get("iri") or ""),
                    "choices": [verb, "broader", "decline"],
                    "samples": [f"{reads} — {q.get('evidence') or 'proposed'}",
                                f"{verb} — state it · broader — {q.get('object')} sits UNDER "
                                f"{q.get('subject')} · decline — they are not connected that way"]})
    return out


def _verdict(question: dict, entry: dict) -> tuple[str, str]:
    """(head, target) for one answer, or a ValueError naming the relation it could not read.

    Every error sentence names the concepts, because a steward answered ten of them and an error that
    does not say which one is an error they cannot act on."""
    reads = f"{question.get('subject')} -> {question.get('object')}"
    value = answer_value(entry).strip()
    head, _, target = value.partition(":")
    head = head.strip().lower()
    if head not in DECISIONS:
        raise ValueError(f"{reads}: answer one of {', '.join(DECISIONS)}, not {value!r}")
    if head == "relate" and not (target.strip() or question.get("predicate")):
        raise ValueError(f"{reads}: this was drawn without a predicate — name the relation, "
                         f"as 'relate:realisedBy'")
    return head, target.strip()


def batch_problems(rows: list[dict], answer: dict) -> list[str]:
    """The sentences for verdicts that could not be read. Separate from `plan` so `apply` can do both:
    apply what is readable, then re-open the card for the rest. One unreadable verdict must not discard
    nine good ones — the measured lesson from the term card, where one empty box threw away four answers."""
    by_iri = {str(q.get("iri") or ""): q for q in rows}
    problems = []
    for label, entry in (answer or {}).items():
        q = by_iri.get(label)
        if q is None:
            problems.append(f"{label} is not one of the relations on this card")
            continue
        try:
            _verdict(q, entry)
        except ValueError as e:
            problems.append(str(e))
    return problems


def plan(payload: dict, answer: dict, actor: str) -> list[tuple[str, dict]]:
    """The calls that make the vocabulary say what the person said. Pure."""
    if not actor:
        raise ValueError("a steward's decision names the person: actor is required")
    by_iri = {str(q.get("iri") or ""): q for q in questions(payload)}
    calls: list[tuple[str, dict]] = []
    for label, entry in (answer or {}).items():
        q = by_iri.get(label)
        if q is None:
            continue                                   # not on this card; `batch_problems` reports it
        try:
            head, target = _verdict(q, entry)
        except ValueError:
            continue            # unreadable HERE; `batch_problems` re-opens the card for exactly these

        note = str(q.get("evidence") or "")
        if head == "decline":
            calls.append((SemanticTools.relation_decline,
                          {"question": label, "actor": actor, "reason": target}))
        elif head == "broader":
            # The arrow was a hierarchy, not a relation — which a person reading the diagram can tell
            # and neither producer can. The OBJECT sits under the SUBJECT, the way the arrow points.
            calls.append((SemanticTools.vocab_place,
                          {"concept_id": str(q.get("object") or ""), "scheme": str(q.get("scheme") or ""),
                           "parent": str(q.get("subject") or ""), "actor": actor, "reason": note}))
        else:
            calls.append((SemanticTools.vocab_relate,
                          {"scheme": str(q.get("scheme") or ""), "subject": str(q.get("subject") or ""),
                           "predicate": target or str(q.get("predicate") or ""),
                           "object": str(q.get("object") or ""), "actor": actor, "note": note}))
    return calls


async def apply(state: dict, actor: str, *, call=None) -> list:
    """Make the calls `plan` names, then re-open the card for anything unreadable."""
    go = call or fabric_gateway.call
    payload = state.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    answer = state.get("answer") or {}
    try:
        calls = plan(payload, answer, actor)
    except ValueError as e:
        raise answer_appliers.AnswerRejected(str(e)) from e
    for tool, args in calls:
        try:
            await go([(tool, args)])
        except Exception as e:                   # noqa: BLE001 — see below; anything else still raises
            # ALREADY DONE IS DONE. `vocab_relate` refuses a duplicate and `vocab_place` a no-op move, so
            # a card half-applied before a failure could never be redriven: the runner's own recovery hit
            # the first completed write and failed identically for ever, and the steward's other answers
            # never landed. The sibling can say "the verbs are idempotent so re-answering costs nothing";
            # for these verbs that is false, so the APPLIER makes it true.
            if "already" not in str(e).lower():
                raise
            print(f"[fabric] {tool}: already done — {e}", flush=True)
    problems = batch_problems(questions(payload), answer)
    if problems:
        raise answer_appliers.AnswerRejected("; ".join(problems))
    return calls


PROMPT = ("The vocabulary says nothing about how these concepts relate, and the corpus or a diagram "
          "says they have something to do with each other. For each: state the relation, make one "
          "broader than the other, or decline it. A relation is what the fabric's derived rung reasons "
          "over, so an answer here is a statement somebody stands behind.")


async def ask_open(*, call=None, min_records: int = 0, limit: int = 10) -> list[dict]:
    """Propose what the corpus connects, then ask a steward about everything open — ONE card.

    The sibling of `fabric_vocabulary.ask_open`, on the same reconciler tick. Both producers feed the
    same queue: a diagram proposes from its arrows when a diagram is ingested, and this proposes from
    co-occurrence, which works on the corpus a tenant already has.

    ONE card for every open question at once, because a card per relation is how 101 approvals came to
    bury ~37 others. The REGISTER remembers it was asked — a set in this process forgets on restart,
    and the question would come back on the next tick for ever."""
    go = call or fabric_gateway.call
    want = config.FABRIC_RELATION_MIN_RECORDS if not min_records else min_records
    pairs = _read((await go([(SemanticTools.concept_pairs, {"min_records": want, "limit": limit})]))[0])
    for pair in pairs:
        # Idempotent on the triple, so proposing what is already parked costs nothing and the two
        # producers cannot raise the same question twice.
        await go([(SemanticTools.relation_propose,
                   {"scheme": pair.get("scheme", ""), "subject": pair.get("subject", ""),
                    "predicate": "", "object": pair.get("object", ""),
                    "evidence": pair.get("evidence", "")})])
    rows = [q for q in _read((await go([(SemanticTools.relation_open, {})]))[0])
            if not q.get("asked")][:limit]
    if not rows:
        return []
    got = (await go([(ApprovalTools.ask, {
        "kind": ApprovalKind.CONCEPT_RELATION.value,
        "subject": f"{len(rows)} pairs of concepts the vocabulary does not connect",
        "prompt": PROMPT, "items": batch_question(rows), "fields": ["value"],
        # The questions ride the card, so the applier can read back what was asked without the
        # register — the same reason the term card carries its candidates.
        "context": {"questions": rows},
        "process": "documentation-fabric"})]))[0]
    got = json.loads(got) if isinstance(got, str) else (got or {})
    request_id = str(got.get("request_id") or "")
    for q in rows:
        try:
            await go([(SemanticTools.vocab_asked, {"candidate": str(q.get("iri") or ""),
                                                   "request_id": request_id})])
        except Exception as e:                  # noqa: BLE001 — the card EXISTS; failing to mark it is a
            # degradation, not a failure: raising would abandon the OTHER nine markers after a steward had
            # already been asked. Swallowing is not free either — an unmarked question is asked again next
            # tick and gets a SECOND card, because `relation_propose` is idempotent and `ask` is not. So
            # the line below is the thing to watch: one that keeps printing is a question nobody can mark.
            print(f"[fabric] asked {q.get('iri')} in {request_id} but could not mark it: "
                  f"{type(e).__name__}: {e}", flush=True)
    return [{**q, "request_id": request_id} for q in rows]


def _read(x):
    return (json.loads(x) if isinstance(x, str) else x) or []


answer_appliers.register(KINDS, apply)
