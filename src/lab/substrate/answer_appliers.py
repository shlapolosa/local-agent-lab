"""What a domain does with a person's ANSWER before the run it releases starts — a registry by approval kind.

The continuation runner is generic: it releases what the asker declared. Some kinds carry an answer that
must land somewhere FIRST (the fabric applies a review at rung H with a grant the released workload does
not have). Rather than the runner dispatching on each such domain by name, a domain registers an APPLIER
here for its kinds, and the runner asks the registry. Adding the next domain is one `register` line."""
from __future__ import annotations

from typing import Awaitable, Callable

class AnswerRejected(ValueError):
    """The PERSON's answer was unusable — as distinct from a write or transport that failed.

    The distinction is the whole reason this type exists, and it was learned by stranding a record
    (9 Oct 2026). A refused WRITE is retried on the next start, because the defect is ours and a deploy
    fixes it. A refused ANSWER will be refused identically forever, because the only thing that can
    change it is a person — and by the time the applier runs, the decision is recorded and the card is
    closed, so no channel can re-answer it. So the runner RE-OPENS the approval rather than redriving
    it. An applier raises this when it cannot interpret what the human said; anything else it raises is
    a failure to retry."""


#: kind -> async applier(state, actor) -> what it applied (a list; empty = nothing to apply)
Applier = Callable[[dict, str], Awaitable[list]]
APPLIERS: dict[str, Applier] = {}


def register(kinds: tuple[str, ...], applier: Applier) -> Applier:
    for kind in kinds:
        if kind in APPLIERS and APPLIERS[kind] is not applier:
            raise ValueError(f"an applier is already registered for approval kind {kind!r}")
        APPLIERS[kind] = applier
    return applier


def applier_for(kind: str) -> Applier | None:
    return APPLIERS.get(str(kind or ""))


__all__ = ["APPLIERS", "AnswerRejected", "Applier", "register", "applier_for"]
