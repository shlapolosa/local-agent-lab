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

import functools

from dataclasses import dataclass, field
from typing import Any, Mapping

from lab.workloads import gateway
from lab.workloads.usecase import agents as A
from lab.workloads.usecase import fallbacks
from lab.workloads.usecase.gates import GateFailed, gate, run_gated
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
    defaulted: dict[str, str] = field(default_factory=dict)   # step number -> what stood in, and why
    #: What a multi-stage step SHOWED its agent, for measurement rather than for the record. A
    #: chooser cannot return what retrieval never put in front of it, so the candidate set is the
    #: ceiling on every number downstream of it — and a pipeline scored only end-to-end cannot say
    #: which stage lost the answer.
    candidates: list = field(default_factory=list)
    #: Called with the record SO FAR each time a step records an answer — the Observer seam that
    #: lets a run be watched while it runs. The record used to be stored once, at the end, and its
    #: ref reached the board only through the workflow's final output: for the whole window in
    #: which anybody actually watches a run, no step could show what it had produced, and a run
    #: that died showed nothing ever (`wfr-c53cdaa27bdb`, 18 Sep 2026 — four steps of real output,
    #: visible on no surface). `None` keeps every existing caller unchanged.
    publish: Any = None

    def record(self, key: str, out: Any, number: str = "") -> None:
        """A derived output, immediately readable by the steps after it. The invariant, in one
        place — this is the line that used to be two lines at every call site and a manual
        `available |= derived` re-sync between halves."""
        self.derived[key] = self.available[key] = out
        if number:
            self.pending.pop(number, None)

    def snapshot(self) -> dict:
        """The record SO FAR — what a person watching the run can be shown now.

        `pending` and `defaulted` travel with it: a partial record without them reads as a run that
        simply has fewer steps, rather than one whose steps did not run and said why.
        """
        return {**self.derived,
                **({"pending_steps": dict(self.pending)} if self.pending else {}),
                **({"defaulted_steps": dict(self.defaulted)} if self.defaulted else {})}

    async def announce(self) -> None:
        """Publish the record so far. BEST EFFORT, always: the record is the run's product and
        showing it early is a convenience, so a store that is down must never turn a completed step
        into a failed run.

        Awaited from `run_step` rather than called from `record`, because publishing goes through
        the GATEWAY — a workload holds no store credential — and that is a coroutine. `record`
        stays the synchronous invariant it has always been.
        """
        if not self.publish:
            return
        try:
            await self.publish(self.snapshot())
        except Exception as e:                 # noqa: BLE001 — see the docstring
            print(f"live record not published: {e}", flush=True)

    def defer(self, number: str, why: str) -> None:
        """A step that did not run, named with its reason. Never silently skipped: a record simply
        lacking a field is indistinguishable from one whose step found nothing."""
        self.pending[number] = why

    def missing(self, step: Step) -> list[str]:
        """What this step needs and does not have."""
        return sorted(set(A.CONTEXT_FOR.get(step.key, ())) - set(self.available))

    async def run_step(self, cfg: Mapping[str, Any], step: Step, *, label: str = "",
                       context: Mapping[str, Any] | None = None) -> bool:
        """Run one exercise if its agent and its whole context are both there; report whether it ran.

        An exercise whose corpus is absent is NOT run. Asked anyway it would answer from nothing,
        and that answer is indistinguishable from a grounded one — which is the failure this whole
        assessment cannot recover from.

        `context` overrides the working set for THIS call only. It exists for the capability drill,
        which runs one step three times over three different candidate sets: writing those onto
        `available` instead would leave the last level's handful of leaves sitting there under the
        name of the published map, and the only thing preventing a later step from reading them
        would be that nobody had yet added `capabilities` to another entry in `CONTEXT_FOR` — a
        one-line change in a different file, made by somebody with no reason to read this one.
        """
        agent = (cfg.get("agents") or {}).get(step.key)
        if agent is None:
            return False                       # not wired yet; whatever deferred it still stands
        pool = {**self.available, **(context or {})}
        needs = sorted(set(A.CONTEXT_FOR.get(step.key, ())) - set(pool))
        if needs:
            # A step whose ONLY missing input is a corpus this tenant has not published records
            # its declared default instead of deferring — validated and gated exactly like an
            # answer, listed as DEFAULTED so a reader can see what rests on it (13 Sep 2026: the
            # design half was never reached while three tenant corpora stayed unpublished).
            corpus = fallbacks.CORPUS_FOR.get(step.key)
            if corpus and needs == [corpus]:
                out = fallbacks.fallback(step.key, pool)
                problems = gate(out, validator=step.validator(), normalise=step.normalise,
                                complete=functools.partial(step.complete, context=pool))
                if problems:                   # a default that fails its own gate is a bug here
                    raise GateFailed(step.number, [f"the declared default failed its gate: {p}"
                                                   for p in problems])
                self.record(step.key, out, step.number)
                self.defaulted[step.number] = (f"{label or step.key} — {corpus} is not published; "
                                               f"the declared default was recorded instead")
                await self.announce()
                return True
            self.defer(step.number, f"{label or step.key} — needs {needs}")
            return False
        context_seen = A.context_for(step.key, pool)
        # Every completeness rule takes the CONTEXT the agent was shown (step 21 checks a component
        # id against the catalogue it was given) — exactly that, and nothing more.
        with gateway.node_span(cfg, f"step_{step.number}"):
            out = await run_gated(agent, A.message(step, context_seen),
                                  step=step.number, validator=step.validator(),
                                  normalise=step.normalise,
                                  complete=functools.partial(step.complete, context=context_seen),
                                  soft=(functools.partial(step.soft, context=context_seen)
                                        if step.soft else None),
                                  soft_key=step.soft_key, soft_remedy=step.soft_remedy)
        self.record(step.key, out, step.number)
        await self.announce()
        return True

    def package(self, **base: Any) -> dict:
        """The record this half produced: what was asked of it, what it derived, and what it did
        not. `pending_steps` is first because it is what a reader must not miss."""
        return {"pending_steps": dict(self.pending), "defaulted_steps": dict(self.defaulted),
                **base, **self.derived}
