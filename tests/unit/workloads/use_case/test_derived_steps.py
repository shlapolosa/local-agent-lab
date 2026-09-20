"""A step the framework DERIVES is still a step, and must be visible as one.

Audited against Intake_Agent_Requirements_v2_7 §2 (20 Sep 2026). All 27 steps are implemented,
but `stamp_shape` fires only from `run_step` — the path an AGENT step takes — while the design
workflow records its deterministic derivations with `d.record(...)` directly. So steps 18
(exposure and influence), 19 (obligations) and 22 (compose architecture) produced real, gated
outputs and appeared on no surface at all: a reader watching a design run saw the agent steps
either side of them and nothing in between, which is also why the run never looks like 27 steps.

They are marked `derived` rather than rendered as ordinary steps, because "no model formed this
answer" is a thing a reviewer is entitled to see. It is a property of the NODE, not a list of step
numbers the page knows — the live view still knows only the schema.
"""
import asyncio

import pytest

from lab.platform import runlog
from lab.workloads.usecase import derivation as D
from lab.workloads.usecase import steps as S


def test_the_three_derived_steps_the_audit_found_are_declared():
    assert {d.number for d in S.DERIVED} == {"18", "19", "22"}
    for step in S.DERIVED:
        assert step.key and step.title and len(step.title.split()) <= 5


def test_a_derived_step_is_not_also_an_agent_step():
    """If a number appeared in both, two nodes would claim it and the last writer would win."""
    assert {d.number for d in S.DERIVED} & {s.number for s in S.STEPS} == set()


def test_derived_step_numbers_and_keys_are_each_unique():
    assert len({d.number for d in S.DERIVED}) == len(S.DERIVED)
    assert len({d.key for d in S.DERIVED}) == len(S.DERIVED)


def test_deriving_records_the_output_and_puts_it_on_the_board(monkeypatch):
    seen = []
    monkeypatch.setattr(runlog, "node",
                        lambda rid, name, status, **kw: seen.append((name, status, kw)))
    d = D.Derivation()
    asyncio.run(d.derive({"run_id": "r1"}, S.derived_for("18"), {"classes": [{"name": "step one"}]}))
    assert d.derived["risk"] == {"classes": [{"name": "step one"}]}
    name, status, attrs = seen[0]
    assert name == "step_18" and status == "done"
    assert attrs["title"] == "derive exposure and influence" and attrs["key"] == "risk"
    assert attrs["derived"] is True, "a reviewer must see that no model formed this answer"
    assert attrs["produced"]["classes"]["items"] == ["step one"]


def test_deriving_clears_the_step_from_pending_like_any_other():
    d = D.Derivation()
    d.defer("18", "needs a facet vector per step")
    asyncio.run(d.derive({}, S.derived_for("18"), {"classes": []}))
    assert "18" not in d.pending


def test_deriving_announces_so_a_watcher_sees_it_arrive(monkeypatch):
    published = []
    d = D.Derivation(publish=lambda record: published.append(record))
    asyncio.run(d.derive({}, S.derived_for("22"), {"zones": []}))
    assert published and "composition" in published[-1]


def test_an_unknown_derived_number_refuses_rather_than_stamping_a_nameless_node():
    with pytest.raises(KeyError):
        S.derived_for("99")
