"""The control requirement set derives against the PUBLISHED guardrails — every one the workbook
added included.

Measured 28 Sep 2026: the CAFÉ workbook added G27-G32, and G28's predicate is "a person or received
agent can reach an AI service, or a managed device can reach an AI provider (interactive trigger;
estate-level)". The derivation evaluated EVERY live predicate per step and refused the step on the
first it could not answer — so step 19 would have refused every step of every run the moment v0.30
was published. Every test that could have seen it read the HTML-era seed JSON, which has no G28.

Two rules, both the mapping's own:
- a guardrail the mapping's ESTATE row names is evaluated at registration and as a standing estate
  check, "not from facet vectors" — never per step;
- a guardrail the step's classes already MANDATE needs no predicate: evaluating it can add nothing,
  and refusing a step over a control it was going to carry anyway is refusing for nothing (G29 is
  in the baseline, and its prose is not a facet expression).
"""
from pathlib import Path

from lab.core.reference import master
from lab.core.usecase import obligations as O, predicates
from lab.core.usecase.model import Step, Workflow
from lab.core.usecase.predicates import parse

MASTERS = Path(__file__).resolve().parents[4] / "src/lab/core/usecase/seed/masters"


def _rows(stem):
    parsed = master.parse((MASTERS / f"{stem}.md").read_text())
    return [dict(zip(parsed.headers, row)) for row in parsed.rows]


GUARDRAILS, MAPPING = _rows("guardrails"), _rows("guardrail_mapping")
ANSWERS = {c: False for c in predicates.NAMED_CONDITIONS}


def _step(step_id="s1", **kw):
    base = dict(activity="commit", determinism="D0", effect="record write",
                reversibility="reversible", blast_radius="single record",
                audience="internal group", authorisation="policy-bounded", domain="general")
    return Step(id=step_id, **(base | kw))


def test_the_published_set_derives_for_an_ordinary_step():
    out = O.derive(Workflow(steps=(_step(),)), conditions=ANSWERS, guardrails=GUARDRAILS,
                   mapping_rows=MAPPING)
    assert out.by_step["s1"], "a control set was derived"


def test_an_estate_guardrail_is_never_a_step_obligation_unless_the_classes_mandate_it():
    estate = O.estate_guardrails(MAPPING)
    assert {"G27", "G30", "G31", "G32"} <= estate
    wf = Workflow(steps=(_step(activity="interpret", determinism="D2", domain="clinical"),))
    got = {o.guardrail for o in O.derive(wf, conditions=ANSWERS, guardrails=GUARDRAILS,
                                          mapping_rows=MAPPING).by_step["s1"]}
    baseline = {o.guardrail for o in O.mandatory_for(0, 0, mapping_rows=MAPPING)}
    assert not (estate - baseline) & got, sorted((estate - baseline) & got)


def test_every_condition_a_step_can_be_asked_is_one_a_step_can_answer():
    """The invariant `NAMED_CONDITIONS` exists for, read from what is PUBLISHED: every condition of
    a guardrail that is evaluated per step — live, not estate-level, not mandated by the baseline —
    must be one step 17 is asked. A condition nobody can answer is a guardrail that can never fire,
    or, since it refuses, a step that can never derive."""
    skipped = O.estate_guardrails(MAPPING) | {o.guardrail for o in
                                              O.mandatory_for(0, 0, mapping_rows=MAPPING)}
    needed = {c for g in O.seed.live_only(GUARDRAILS) if g["id"] not in skipped
              for c in parse(g["pred"]).conditions()}
    assert needed <= predicates.NAMED_CONDITIONS, sorted(needed - predicates.NAMED_CONDITIONS)


def test_a_mandated_guardrail_whose_predicate_cannot_be_answered_does_not_refuse_the_step():
    guardrails = GUARDRAILS + [{"id": "G77", "pred": "a condition no step can answer",
                                "rule": "r", "cap": ""}]
    mapping = [
        dict(r) if not str(list(r.values())[0]).lower().startswith("baseline")
        else {k: (f"{v} · G77 something" if i == 1 else v) for i, (k, v) in enumerate(r.items())}
        for r in MAPPING]
    out = O.derive(Workflow(steps=(_step(),)), conditions=ANSWERS, guardrails=guardrails,
                   mapping_rows=mapping)
    assert "G77" in {o.guardrail for o in out.by_step["s1"]}


def test_an_UNMANDATED_guardrail_whose_predicate_cannot_be_answered_still_refuses():
    """The refusal is kept everywhere it can matter: a guardrail that might or might not fire."""
    import pytest
    guardrails = GUARDRAILS + [{"id": "G77", "pred": "a condition no step can answer",
                                "rule": "r", "cap": ""}]
    with pytest.raises(O.ObligationError, match="G77"):
        O.derive(Workflow(steps=(_step(),)), conditions=ANSWERS, guardrails=guardrails,
                 mapping_rows=MAPPING)
