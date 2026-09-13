"""A step whose corpus the tenant has not published records a DECLARED default — validated and
gated like an answer, listed as defaulted, never silently skipped and never left pending."""
import asyncio
import functools

import pytest

from lab.workloads.usecase import fallbacks
from lab.workloads.usecase.derivation import Derivation
from lab.workloads.usecase.gates import gate
from lab.workloads.usecase.steps import STEPS

ELEMENTS = {"active": [{"name": "nurse", "kind": "role", "provenance": "for_whom"}],
            "behavioural": [{"name": "triage referral", "verb": "triage", "object": "referral",
                             "provenance": "problem"}],
            "passive": [{"name": "referral letter", "provenance": "problem"},
                        {"name": "appointment book", "provenance": "expected_change"}]}
POOL = {"elements": ELEMENTS, "workflow_graph": {"nodes": [], "edges": []}, "coverage_map": {}}


def _step(key):
    return next(s for s in STEPS if s.key == key)


@pytest.mark.parametrize("key", sorted(fallbacks.FALLBACKS))
def test_every_default_validates_against_its_schema_and_passes_its_own_gate(key):
    """The default is an ANSWER in every respect but one: the run says it was defaulted. If it
    could not pass the step's gate, the gate would refuse it at run time and the run would stop at
    exactly the point this exists to get past."""
    step = _step(key)
    out = fallbacks.fallback(key, POOL)
    assert gate(out, validator=step.validator(), normalise=step.normalise,
                complete=functools.partial(step.complete, context=POOL)) == []
    flags = out.get("gap_flags") or []
    assert flags and flags[0]["what"].startswith("DEFAULT") and fallbacks.CORPUS_FOR[key].replace("_", " ") in flags[0]["what"].replace("_", " ")


def test_the_defaults_are_the_conservative_reading_of_not_knowing():
    r = fallbacks.fallback("realisation_match", POOL)
    assert r["existing"] is False and r["matched"] == [] and "nurse" in r["unrealised"]
    q = fallbacks.fallback("quality_attributes", POOL)
    assert q["scenarios"] == [], "no commitment exists, so no scenario is invented"
    c = fallbacks.fallback("source_contracts", POOL)
    assert {s["source"] for s in c["sources"]} == {"referral letter", "appointment book"}
    assert all(s["sensitivity"] == "restricted" and s["freshness"] == "time-critical" for s in c["sources"])
    assert fallbacks.fallback("frame", POOL) is None


class _Agent:
    async def run(self, message): raise AssertionError("an absent corpus must not reach the agent")


def test_a_step_missing_only_its_unpublished_corpus_records_the_default_and_is_listed_as_defaulted():
    d = Derivation(available=dict(POOL))
    cfg = {"agents": {"source_contracts": _Agent(), "realisation_match": _Agent()}}
    assert asyncio.run(d.run_step(cfg, _step("source_contracts"), label="contract sources")) is True
    assert "source_contracts" in d.derived and d.available["source_contracts"] is d.derived["source_contracts"]
    assert "11" in d.defaulted and "source_classification" in d.defaulted["11"] and "11" not in d.pending
    pkg = d.package()
    assert pkg["defaulted_steps"] == d.defaulted and "11" not in pkg["pending_steps"]


def test_a_step_missing_anything_else_still_defers():
    """The default stands in for the CORPUS only. A step whose prior evidence is missing (the
    elements, the graph) has nothing to default from and is deferred as before."""
    d = Derivation(available={"landscape": []})            # corpus present, elements absent
    cfg = {"agents": {"realisation_match": _Agent(), "frame": _Agent()}}
    assert asyncio.run(d.run_step(cfg, _step("realisation_match"))) is False
    assert "6" in d.pending and "elements" in d.pending["6"] and not d.defaulted
    d2 = Derivation(available={})                          # a step with no default at all
    assert asyncio.run(d2.run_step(cfg, _step("frame"))) is False and "3" in d2.pending
