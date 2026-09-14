"""The ONE hook that grows the model: after a step is recorded, its mapper runs and the model is
re-recorded — so it is context to every later step (`Derivation.record`'s invariant), it rides the
process record through `package()`, and the design half re-records it into its own package.

Kept apart from `Derivation` because the Derivation is about what a run knows; this is about one
artifact the run maintains. The model is read from `derived` first: the design half seeds
`available` from the screening record, and `feasibility` builds `available` without `derived`, so
`available["model"]` can be the screening's while `derived["model"]` is this half's.
"""
from __future__ import annotations

from typing import Any, Mapping

from lab.workloads.usecase import mappers, modeltrace
from lab.workloads.usecase.derivation import Derivation
from lab.workloads.usecase.model import Model

__all__ = ["MODEL", "SUMMARY", "apply_mapper", "current", "ensure", "grow"]

MODEL = "model"
SUMMARY = "model_summary"


def current(d: Derivation, name: str = "") -> Model:
    spec = d.derived.get(MODEL) or d.available.get(MODEL)
    return Model.from_spec(spec) if isinstance(spec, Mapping) else Model(name=name or "use case")


def apply_mapper(d: Derivation, step_key: str, *, name: str = "") -> Model | None:
    """Grow the model with the step just recorded. Returns the model (its `touched` set names
    what this step added) or None when the step has no mapper or did not run."""
    if step_key not in mappers.MAPPERS or step_key not in d.derived:
        return None
    model = current(d, name)
    model.clear_touched()
    mappers.apply(step_key, d.derived[step_key], model, d.available)
    d.record(MODEL, model.to_spec())
    d.record(SUMMARY, mappers.summary(model, d.available))
    return model


def ensure(d: Derivation, name: str = "") -> None:
    """The model and its summary are in the working set before any step that READS them runs —
    the screening's, carried in, or an empty one. A step that lists `model_summary` in its context
    would otherwise be deferred on a run whose earlier steps had nothing to map."""
    if SUMMARY not in d.available or MODEL not in d.derived:
        model = current(d, name)
        d.record(MODEL, model.to_spec())
        d.record(SUMMARY, mappers.summary(model, d.available))


async def grow(cfg, d: Derivation, step_key: str, *, name: str = "") -> None:
    """The ONE call a workflow makes after a step is recorded: map it onto the model, and (while the
    throwaway trace is on) render what it added."""
    model = apply_mapper(d, step_key, name=name)
    if model is not None:
        await modeltrace.trace(cfg, d, step_key, model)
