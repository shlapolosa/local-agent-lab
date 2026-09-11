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

from lab.core.semantic.fabric.ontology import CONTEXT_IRI, DELIVERED_UNDER, DOCUMENT_TYPE, short
from lab.platform.contracts import ApprovalKind, SemanticTools, answer_value, continuation_of
from lab.substrate import answer_appliers, fabric_gateway

KINDS = (ApprovalKind.ASSOCIATION.value, ApprovalKind.DRAFT_REVIEW.value)
METHOD = "review"


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
            if _link(row, short(DOCUMENT_TYPE), value) in ("S", "X"):
                calls.append((SemanticTools.promote, {"subject": iri, "predicate": DOCUMENT_TYPE,
                                                      "object": value, "actor": actor, "method": METHOD}))
            else:
                calls.append((SemanticTools.catalog_assert, {"iri": iri, "field": "document_type", "value": value,
                                                             "rung": "H", "method": METHOD, "actor": actor}))
        elif label == "context":
            if value.strip().lower() == "none":
                calls.append((SemanticTools.catalog_state, {"iri": iri, "state": "pending", "unassociated": True}))
                continue
            ctx = value if value.startswith(CONTEXT_IRI) else CONTEXT_IRI + value.strip()
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
    calls = plan(row, state.get("answer") or {}, actor)
    if calls:
        await go(calls)
    return calls


# The runner asks the registry, not this module: the fabric's kinds are applied by `apply` before release.
answer_appliers.register(KINDS, apply)

__all__ = ["KINDS", "METHOD", "applies_to", "artifact_of", "plan", "apply"]
