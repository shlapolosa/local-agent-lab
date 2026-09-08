"""The working set of a CAFÉ run: what is available, what has been derived, what is still pending.

It exists to hold ONE invariant that was previously nobody's job: **a derived output is immediately
available as context to the steps after it.** Before this, `available`, `derived` and `pending` were
three mutable dicts threaded by reference through a workflow's executors and helpers, re-synced by
hand with `available |= derived` at two places. A re-sync that is easy to forget and whose omission
silently starves a later step of context is not an invariant, it is a habit.

It also gives the two use-case workloads ONE step runner. They had two, and they had already
drifted in the message a deferred step records — the kind of divergence that is invisible until
somebody compares two screening records and cannot tell why one explains itself better.

`lab.workloads.usecase` rather than `lab.platform`: it is shared by the two use-case workloads and
by nothing else, and a helper used by one tier lives in that tier.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from lab.workloads import gateway
from lab.workloads.usecase import agents as A
from lab.workloads.usecase.gates import run_gated
from lab.workloads.usecase.steps import Step

__all__ = ["Derivation"]


@dataclass
class Derivation:
    """What a run knows, what it has worked out, and what it has not.

    `available` starts as the corpora and prior evidence a run was given; `derived` is what THIS
    half produced; `pending` names every step that did not run, and why. The three are reported
    separately because they answer different questions: a package is assembled from `derived`, a
    reader's confidence comes from `pending`, and only `available` decides what a step may read.
    """

    available: dict[str, Any] = field(default_factory=dict)
    derived: dict[str, Any] = field(default_factory=dict)
    pending: dict[str, str] = field(default_factory=dict)

    def record(self, key: str, out: Any, number: str = "") -> None:
        """A derived output, immediately readable by the steps after it. The invariant, in one
        place — this is the line that used to be two lines at every call site and a manual
        `available |= derived` re-sync between halves."""
        self.derived[key] = self.available[key] = out
        if number:
            self.pending.pop(number, None)

    def defer(self, number: str, why: str) -> None:
        """A step that did not run, named with its reason. Never silently skipped: a record simply
        lacking a field is indistinguishable from one whose step found nothing."""
        self.pending[number] = why

    def missing(self, step: Step) -> list[str]:
        """What this step needs and does not have."""
        return sorted(set(A.CONTEXT_FOR.get(step.key, ())) - set(self.available))

    async def run_step(self, cfg: Mapping[str, Any], step: Step, *, label: str = "") -> bool:
        """Run one exercise if its agent and its whole context are both there; report whether it ran.

        An exercise whose corpus is absent is NOT run. Asked anyway it would answer from nothing,
        and that answer is indistinguishable from a grounded one — which is the failure this whole
        assessment cannot recover from.
        """
        agent = (cfg.get("agents") or {}).get(step.key)
        if agent is None:
            return False                       # not wired yet; whatever deferred it still stands
        needs = self.missing(step)
        if needs:
            self.defer(step.number, f"{label or step.key} — needs {needs}")
            return False
        with gateway.node_span(cfg, f"step_{step.number}"):
            out = await run_gated(agent, A.message(step, A.context_for(step.key, self.available)),
                                  step=step.number, validator=step.validator(),
                                  normalise=step.normalise, complete=step.complete)
        self.record(step.key, out, step.number)
        return True

    def package(self, **base: Any) -> dict:
        """The record this half produced: what was asked of it, what it derived, and what it did
        not. `pending_steps` is first because it is what a reader must not miss."""
        return {"pending_steps": dict(self.pending), **base, **self.derived}
