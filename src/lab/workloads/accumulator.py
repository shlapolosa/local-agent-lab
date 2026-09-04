"""Accumulator base — the shared skeleton behind the agents' "accumulator tools".

An agent (the BA, the Architect) BUILDS its structured output through many SMALL, validated,
deterministic tool calls instead of emitting one giant document: each call adds a handful of
items, gets a precise per-item accept/reject report, corrects only what failed, and the document
is assembled deterministically here — valid by construction. This module holds what every
accumulator shares (Template Method); a concrete accumulator supplies only its vocabulary,
its per-item validation, and its assembly/gate specifics:

  * `coerce_items` / `MAX_BATCH` / `_batch()` — tolerate the ways a model hands over a list, then
    enforce the batch cap with ONE message and the empty `{added, <middle>, rejected, total_*}`
    envelope the caller would otherwise have returned;
  * `finish()` — assemble via `result()`, judge via `_gate(doc)`, NEVER raise into the model,
    stash the report on `last_finish` for the coordinator;
  * `reset()` / `last_finish` — the state every accumulator carries.

Pure and deterministic: no Redis, no LLM, no network, no I/O. The domain core imports nothing
outside the standard library.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

__all__ = ["MAX_BATCH", "Accumulator", "coerce_items", "fmt", "nonempty_str"]

MAX_BATCH = 12   # items per add_* call: small batches are what keeps tool calls reliable


def fmt(vals) -> str:
    """Render a vocabulary for an error message / tool docstring: 'A, B, C'."""
    return ", ".join(vals)


def coerce_items(items: Any) -> list | str:
    """Tolerate the ways a model may hand over a list: a JSON string, a single dict, a list.
    Returns the list, or an error message (str) when it cannot be one."""
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except ValueError:
            return "items must be a JSON array of objects (got an unparsable string)"
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return f"items must be a list (got {type(items).__name__})"
    return items


def nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


class Accumulator(ABC):
    """Deterministic state an agent fills through its tools. Subclasses extend `reset()` with
    their own collections and implement `result()`, `counts()` and `_gate()`."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.last_finish: dict | None = None

    # ---- batch skeleton -----------------------------------------------------------------------
    @staticmethod
    def _batch(items: Any, total_key: str, total: int, middle: str = "updated") -> tuple[list, None] | tuple[None, dict]:
        """Coerce `items` and enforce MAX_BATCH. Returns (list, None), or (None, report) where
        report is the empty `{error, added, <middle>, rejected, <total_key>}` envelope to return
        as-is — nothing was added."""
        empty = {"added": [], middle: [], "rejected": [], total_key: total}
        lst = coerce_items(items)
        if isinstance(lst, str):
            return None, {"error": lst, **empty}
        if len(lst) > MAX_BATCH:
            return None, {"error": f"batch too large: {len(lst)} items > {MAX_BATCH}. Nothing was added — "
                                   f"split into calls of at most {MAX_BATCH} items and resend.", **empty}
        return lst, None

    # ---- assembly hooks -----------------------------------------------------------------------
    @abstractmethod
    def result(self) -> dict:
        """The assembled document (a deep copy — the caller may mutate it freely)."""

    @abstractmethod
    def counts(self) -> dict:
        """The tallies reported by `finish()`."""

    @abstractmethod
    def _gate(self, doc: dict) -> tuple[list[str], str | None]:
        """Judge the assembled document. Returns (errors, hint): empty errors = complete and valid;
        hint (optional) is advice that does not block, e.g. elements with no relation."""

    def finish(self) -> dict:
        """Assemble + gate. Returns {ok, counts, errors?, hint?}; never raises into the model."""
        try:
            errors, hint = self._gate(self.result())
            report: dict = {"ok": not errors, "counts": self.counts()}
            if errors:
                report["errors"] = errors
            if hint:
                report["hint"] = hint
        except Exception as e:  # contract: never raise into the model
            report = {"ok": False, "counts": self.counts(), "errors": [f"internal: {type(e).__name__}: {e}"]}
        self.last_finish = report
        return report
