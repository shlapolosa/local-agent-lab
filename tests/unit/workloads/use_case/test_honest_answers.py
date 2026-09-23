"""An honest answer must not be scored as an incomplete one.

Audited 23 Sep 2026. `graph_is_explicit: false` was appended to the completeness list — so the
model was told its answer was rejected and given one retry. There were exactly two outcomes and
both lose the finding:

* the model flips to `true` on the retry (overwhelmingly likely: the retry message names the
  problem), and the Board escalation the answer WAS simply vanishes; or
* it holds its answer and `GateFailed` kills the whole design run, so there is no escalation
  record either.

The comment above the rule says the escalation "must be said rather than scored around" — and the
gate was the one thing making it impossible to say. An unexplicit graph is a finding the framework
has a route for (D3 at orchestration level, a Board escalation), not a defect in the answer.
"""
from lab.workloads.usecase import steps as S


def _complete(out, context=None):
    return S.step_for("15").complete(out, context)


GRAPH = {"nodes": [{"id": "n1"}]}
OK = {"steps": [{"id": "n1", "tier": "D0"}], "governance_tier": "D0"}


def test_an_unexplicit_graph_is_not_an_incomplete_answer():
    problems = _complete({**OK, "graph_is_explicit": False}, {"workflow_graph": GRAPH})
    assert not any("explicit" in p for p in problems), problems


def test_an_explicit_graph_is_equally_acceptable():
    assert not _complete({**OK, "graph_is_explicit": True}, {"workflow_graph": GRAPH})


def test_the_answer_still_has_to_be_complete_in_every_other_way():
    """Relaxing one honest answer must not relax the rest: a run with no classified step is still
    incomplete whatever it says about the graph."""
    problems = _complete({"steps": [], "graph_is_explicit": False}, {"workflow_graph": GRAPH})
    assert problems


def test_the_finding_survives_into_the_record_rather_than_being_scored_away():
    """It is data on the answer, so the escalation is carried rather than argued with."""
    out = {**OK, "graph_is_explicit": False}
    assert out["graph_is_explicit"] is False
