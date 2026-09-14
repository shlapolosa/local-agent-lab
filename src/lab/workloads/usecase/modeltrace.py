"""THROWAWAY test aid: what every step ADDED to the model, as its own rendered artifact.

Asked for on 14 Sep 2026 "for the sake of proving the outputs of each step": a summary that reads
well is not evidence that a step did what it should, and a picture of exactly what it added is.
One module, one call (`modelling.grow`), one toggle (`config.USECASE_MODEL_TRACE`, default off) —
so switching it off is an env change and deleting it is one file and one line.

Per mapped step, when on: the delta spec (`Model.delta_spec`) is stored through `semantic_store_spec`
and rendered through `archimate_render`, and the refs land on the record under `model_trace` —
which no step's `CONTEXT_FOR` names, so it never reaches a prompt. Every call is best-effort: a
render that fails records its error for that step and the run goes on. The approvals show the
trace SVGs as one tab per step, in run order, beside the final views.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from lab.platform import config
from lab.platform.contracts import EATools, SemanticTools
from lab.workloads import gateway
from lab.workloads.usecase.derivation import Derivation
from lab.workloads.usecase.model import Model
from lab.workloads.usecase.steps import DERIVED_STEP_NUMBERS, STEPS

__all__ = ["TRACE", "tabs", "trace"]

log = logging.getLogger("lab.workloads.usecase.modeltrace")
TRACE = "model_trace"

#: Step number by key, agent steps and derived steps alike — so a tab carries the number a person
#: recognises. Both halves come from `steps`; nothing is numbered here.
NUMBER_OF = {s.key: s.number for s in STEPS} | DERIVED_STEP_NUMBERS


def _order(key: str) -> tuple[int, str]:
    """Run order by step number, tolerant of a suffix ("26a") — a bookkeeping aid must not be able
    to fail the approval it decorates."""
    digits = "".join(c for c in NUMBER_OF.get(key, "") if c.isdigit())
    return (int(digits) if digits else 99, key)


def enabled() -> bool:
    return bool(config.USECASE_MODEL_TRACE)


async def trace(cfg: Mapping[str, Any], d: Derivation, step_key: str, model: Model) -> None:
    """Store and render the delta the step just added; record the refs (or the failure)."""
    if not enabled():
        return
    entry: dict[str, Any] = {**model.counts(), "added": len(model.touched)}
    if model.touched:
        try:
            stored = await gateway.call(cfg, SemanticTools.store_spec, {
                "spec": model.delta_spec(step_key), "name": f"model.{step_key}.json"})
            entry["spec_ref"] = gateway.ref_from(stored)
            rendered = await gateway.call(cfg, EATools.render, {
                "spec_ref": entry["spec_ref"], "basename": f"model.{step_key}", "strict": False})
            rendered = rendered if isinstance(rendered, dict) else json.loads(rendered or "{}")
            entry["svg_refs"] = dict(rendered.get("svg_refs") or {})
            entry["violations"] = len(rendered.get("violations") or ())
        except Exception as exc:                   # noqa: BLE001 — a picture, never the run
            entry["error"] = f"{exc!r}"[:200]
            log.warning("model trace for %s not rendered: %s", step_key, exc)
    traces = dict(d.derived.get(TRACE) or {})
    traces[step_key] = entry
    d.record(TRACE, traces)


def tabs(record: Mapping[str, Any]) -> dict[str, str]:
    """`{"<number> <step_key>": svg_ref}` in run order, from a record carrying `model_trace` —
    what an approval attaches as `svg_refs` so the review app shows one tab per step."""
    out: dict[str, str] = {}
    traces = record.get(TRACE) or {}
    for key in sorted(traces, key=_order):
        for label, ref in (traces[key].get("svg_refs") or {}).items():
            out[f"{NUMBER_OF.get(key, '?')} {key}" + (f" · {label}" if len(traces[key]["svg_refs"]) > 1 else "")] = ref
    return out
