"""Declared defaults for a step whose corpus this tenant has not published.

Three exercises read a corpus the tenant does not have — the as-is application landscape (step 6),
the business service levels (step 8) and the source classification (step 11) — and a run used to
stop at readiness gate C because of it, with the whole design half never exercised. The decision
(13 Sep 2026) is to reach the end and SAY what was assumed: a defaulted step records a simple value
that validates against the step's own schema and passes its own gate, carries a gap flag naming the
missing corpus and the assumption, and is listed on the record as DEFAULTED, never as derived and
never as pending. A reader of the design package can see exactly which findings rest on a default.

Each default is the most conservative reading of "we do not know": nothing is realised (everything
must be built), no service level is committed (the envelope comes from the criticality class alone),
and every data source is contracted at the tightest classification a policy could demand. A tenant
that publishes the corpus gets the agent's grounded answer instead, with no change here.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

__all__ = ["CORPUS_FOR", "FALLBACKS", "fallback"]

#: The corpus each defaultable step reads — the one whose absence the default stands in for.
CORPUS_FOR: dict[str, str] = {
    "realisation_match": "landscape",
    "quality_attributes": "service_levels",
    "source_contracts": "source_classification",
}


def _names(pool: Mapping[str, Any], group: str) -> list[str]:
    elements = pool.get("elements") or {}
    return [str(e.get("name")) for e in (elements.get(group) or [])
            if isinstance(e, Mapping) and str(e.get("name") or "").strip()]


def _flag(what: str, body: str) -> dict:
    return {"what": what, "owning_body": body}


def _realisation_match(pool: Mapping[str, Any]) -> dict:
    """No landscape: nothing is known to exist, so every element is unrealised and must be built."""
    unrealised = _names(pool, "active") + _names(pool, "behavioural") + _names(pool, "passive")
    return {"matched": [], "unrealised": unrealised or ["every element of this use case"],
            "existing": False,
            "gap_flags": [_flag("DEFAULT — no as-is application landscape is published for this "
                                "business area, so no element could be matched to an existing "
                                "realisation; every element is treated as new build until the "
                                "landscape is published and step 6 is re-run", "Enterprise Architecture")]}


def _quality_attributes(pool: Mapping[str, Any]) -> dict:
    """No service levels: no scenario can be taken from a commitment, so none is written and the
    quality envelope rests on the criticality class alone."""
    return {"scenarios": [],
            "gap_flags": [_flag("DEFAULT — no business service levels are published, so no quality "
                                "scenario could be taken from a commitment; the envelope is decided "
                                "by the confirmed criticality class alone until service levels are "
                                "published and step 8 is re-run", "Service Management")]}


def _source_contracts(pool: Mapping[str, Any]) -> dict:
    """No source classification: every data source is contracted at the tightest reading — restricted
    sensitivity, time-critical freshness, cite-everything — so nothing downstream under-protects it."""
    sources = [{"source": name, "sensitivity": "restricted", "freshness": "time-critical",
                "permission_scope": "not classified — treated as most restrictive",
                "propagation": "no onward propagation until classified",
                "provenance": "not classified", "citation_policy": "cite the source record on every use"}
               for name in _names(pool, "passive")]
    return {"sources": sources,
            "gap_flags": [_flag("DEFAULT — no grounding source classification is published, so every "
                                "data source is contracted at the most restrictive reading (restricted, "
                                "time-critical, cite on every use) until the classification is "
                                "published and step 11 is re-run", "Information Governance")]}


FALLBACKS: dict[str, Callable[[Mapping[str, Any]], dict]] = {
    "realisation_match": _realisation_match,
    "quality_attributes": _quality_attributes,
    "source_contracts": _source_contracts,
}


def fallback(step_key: str, pool: Mapping[str, Any]) -> dict | None:
    """The declared default for this step over what the run has, or None when the step has none."""
    fn = FALLBACKS.get(step_key)
    return fn(pool) if fn else None
