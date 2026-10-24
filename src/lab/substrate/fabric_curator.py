"""The curator: a PERSON's answer to a fabric question, applied to the fabric as rung-H assertions.

The intake run ends on a question (`association` / `draft-review`): is this the type, is this the delivery
context. The ANSWER is the only thing that may move an assertion to H (note 005), and the grant that does it
(`SemanticTools.PROMOTE`) reaches no workload — so it is applied HERE, by the continuation runner, on the
`approvals:decisions` stream where "a person answered, through whichever channel" is one fact and the actor
is the channel-authenticated human. The runner acts with the fabric's CURATOR credential, a channel identity.

`plan` is pure: given the record and the answer it says which tool calls to make; `apply` makes them. What
the answer CONFIRMS is promoted (S/X → H, the audit chain kept); what it CORRECTS is asserted at H, the
previous value superseded; `none` for a context marks the record unassociated."""
from __future__ import annotations

from lab.core.semantic.fabric.ontology import (CONTEXT_IRI, DUPLICATE_OF, DELIVERED_UNDER, DOCUMENT_TYPE,
                                               SUBJECT, DocumentTypes, short)
from lab.core.semantic.fabric.catalog import iri_safe
from lab.core.semantic.fabric.service import PERSON
from lab.platform.contracts import ApprovalKind, SemanticTools, answer_value, continuation_of
from lab.platform.contracts.fabric import TERM_ITEM
from lab.substrate import answer_appliers, fabric_gateway

KINDS = (ApprovalKind.ASSOCIATION.value, ApprovalKind.DRAFT_REVIEW.value)
DOC_TYPES = DocumentTypes()           # stateless; the scheme's parse is cached in core
METHOD = "review"
#: The owner card's per-subject items are labelled by CONCEPT IRI, so the prefix is what identifies them.
SUBJECT_ITEM = "subject:"
#: The method recorded when a PERSON supplies the owner the owner-map could not resolve. It is written at
#: rung C, not H, because the rung states the KIND of knowledge and FRS FR-1.1 is explicit that "identity,
#: owner and sensitivity enter at C only" — owner is a fact looked up or supplied, never a judgement
#: inferred from evidence, and `fab:OwnerProvenanceShape` enforces that the triple lives in graph C.
#: The method is what keeps the answer honest: C does not claim a reference store was consulted.
OWNER_METHOD = "review:human-supplied"


def applies_to(kind: str) -> bool:
    return str(kind or "") in KINDS


def artifact_of(payload: dict) -> str:
    """The record a fabric question is about — carried on the continuation the asker declared."""
    cont = continuation_of(payload or {})
    return str((cont.inputs if cont else {}).get("artifact_iri") or "")


def _link(row: dict, predicate: str, obj: str) -> str | None:
    """The rung a link (predicate, object) currently sits on, or None."""
    for l in row.get("links") or []:
        if l.get("predicate") == predicate and str(l.get("object")) == obj:
            return str(l.get("rung") or "")
    return None


def plan(row: dict, answer: dict, actor: str) -> list[tuple[str, dict]]:
    """The calls that make the fabric say what the person said. Pure."""
    if not actor:
        raise ValueError("a curator's decision names the person: actor is required")
    iri = row["iri"]
    calls: list[tuple[str, dict]] = []
    for label, entry in (answer or {}).items():
        value = answer_value(entry)
        if label == "document_type":
            value = DOC_TYPES.resolve(value)
            if _link(row, short(DOCUMENT_TYPE), value) in ("S", "X"):
                calls.append((SemanticTools.promote, {"subject": iri, "predicate": DOCUMENT_TYPE,
                                                      "object": value, "actor": actor, "method": METHOD}))
            else:
                calls.append((SemanticTools.catalog_assert, {"iri": iri, "field": "document_type", "value": value,
                                                             "rung": "H", "method": METHOD, "actor": actor}))
        elif label.startswith(SUBJECT_ITEM):
            # The owner confirming what their document is ABOUT. PROMOTE rather than assert, because that is
            # the act the ladder exists to record: `G.promote` MOVES the triple to H and invalidates the old
            # assertion, keeping the chain that says how the fabric first came to believe it. (It does NOT
            # leave an X copy behind — a comment here and in `vocab_link` both used to claim it did.)
            # What makes a confirmed subject survive the next sweep is that `vocab_link`'s `stale` scan
            # looks only at rung X, and an H-only triple is not in it. One left at X does not survive, which
            # is the whole point of asking.
            concept = label[len(SUBJECT_ITEM):]
            verdict = value.strip().lower()
            if verdict == "keep":
                if _link(row, short(SUBJECT), concept) in ("S", "X"):
                    calls.append((SemanticTools.promote, {"subject": iri, "predicate": SUBJECT,
                                                          "object": concept, "actor": actor, "method": METHOD}))
                continue                            # already at H (or above): answered twice, applied once
            if verdict != "drop":
                raise ValueError(f"a subject answer is 'keep' or 'drop', not {value!r} "
                                 f"(for {concept.rsplit('#', 1)[-1]})")
            # Retracted, not left alone: the owner is the one person who knows the document is not about
            # this, and a subject left standing keeps driving what else the corpus says relates to it.
            # `not_about`, not a bare retraction: a retraction leaves no trace, so the next classification
            # matched the same label and put the subject back — and asked this person again. It retracts
            # AND records the NO, so `keep` and `drop` both last.
            calls.append((SemanticTools.not_about, {"iri": iri, "concept": concept, "actor": actor,
                                                    "reason": "the owner said this document is not about it"}))
        elif label.startswith(TERM_ITEM):
            # The AUTHOR's word on a term read out of their document (FR-10): confirm sends it to a
            # steward, rename corrects it first, remove withdraws it as the author's NO — not a steward's.
            candidate = label[len(TERM_ITEM):]
            head, _, word = value.strip().partition(":")
            head = head.strip().lower()
            if head not in ("confirm", "rename", "remove") or (head == "rename" and not word.strip()):
                raise ValueError(f"a term answer is confirm, rename:<word> or remove, not {value!r} "
                                 f"(for {candidate})")
            args = {"candidate": candidate, "decision": head, "actor": actor}
            if head == "rename":
                args["label"] = word.strip()
            calls.append((SemanticTools.author_confirm, args))
        elif label == "overlap":
            if value.strip().lower() == "keep":
                continue
            if not value.startswith("duplicate-of:"):
                raise ValueError("an overlap answer is 'keep' or 'duplicate-of:<record iri>'")
            calls.append((SemanticTools.edge_assert, {"subject": iri, "predicate": DUPLICATE_OF,
                                                      "object": value.split(":", 1)[1].strip(), "rung": "H",
                                                      "method": METHOD, "actor": actor}))
            calls.append((SemanticTools.catalog_state, {"iri": iri, "state": "withdrawn"}))
        elif label == "owner":
            # Rung C, not H — see OWNER_METHOD. Writing it at H made the fabric refuse the very answer it
            # had asked for, on the first approval a person ever gave (measured 8 Oct 2026).
            person = value if value.startswith(PERSON) else PERSON + value.strip()
            if iri_safe(person) != person:
                raise ValueError(f"an owner is an email or a person IRI, not {value!r}")
            calls.append((SemanticTools.catalog_assert, {"iri": iri, "field": "owner", "value": person,
                                                         "rung": "C", "method": OWNER_METHOD, "actor": actor}))
        elif label == "context":
            if value.strip().lower() == "none":
                calls.append((SemanticTools.catalog_state, {"iri": iri, "state": "pending", "unassociated": True}))
                continue
            ctx = value if value.startswith(CONTEXT_IRI) else CONTEXT_IRI + value.strip()
            # The object of a triple is the ONE end nothing downstream checks: `graph_assert` validates a
            # subject and a predicate, never an object, and `term()` quietly stores a non-IRI as a Literal.
            # So "project:alpha (0.92)" — which the review app offered as a pick, score and all — was
            # written at rung H, marking a record associated under a context that does not exist, with a
            # person's name on it. Refused here, where the answer is interpreted.
            if iri_safe(ctx) != ctx:
                raise ValueError(f"a context is a key like 'project:alpha', not {value!r} — "
                                 "a score or a description is not one")
            if _link(row, short(DELIVERED_UNDER), ctx) in ("S", "X"):
                calls.append((SemanticTools.promote, {"subject": iri, "predicate": DELIVERED_UNDER,
                                                      "object": ctx, "actor": actor, "method": METHOD}))
            else:
                calls.append((SemanticTools.edge_assert, {"subject": iri, "predicate": DELIVERED_UNDER,
                                                          "object": ctx, "rung": "H", "method": METHOD,
                                                          "actor": actor, "supersede": True}))
            calls.append((SemanticTools.catalog_state, {"iri": iri, "state": "pending", "unassociated": False}))
    return calls


async def apply(state: dict, actor: str, *, call=None) -> list[tuple[str, dict]]:
    """Apply one decided approval's answer. `call(calls)` is the gateway transport (injected by a test);
    returns the calls made. Raises on a refused write, so the runner records the failure on the approval."""
    payload = state.get("payload") or {}
    iri = artifact_of(payload)
    if not iri:
        raise ValueError("the approval names no artifact (no continuation with artifact_iri)")
    go = call or fabric_gateway.call
    row = (await go([(SemanticTools.catalog_get, {"iri": iri})]))[0]
    if not row:
        raise LookupError(f"no catalog record {iri}")
    # `plan` is pure and its ONLY job is interpreting what the person said, so every ValueError out of
    # it is the ANSWER being unusable — never a write that failed. Typing it here is what lets the runner
    # re-open the card instead of redriving a decision only a person can change.
    try:
        calls = plan(row, state.get("answer") or {}, actor)
    except ValueError as e:
        raise answer_appliers.AnswerRejected(str(e)) from e
    if calls:
        await go(calls)
    return calls


# The runner asks the registry, not this module: the fabric's kinds are applied by `apply` before release.
answer_appliers.register(KINDS, apply)

__all__ = ["KINDS", "METHOD", "applies_to", "artifact_of", "plan", "apply"]
