"""The spec derives ITSELF — the strongest acceptance test available.

§11 names "the framework's published worked examples" as the acceptance test that matters most, but
they are not in the specification: they are listed only as an artifact of the retrieval index, and
we do not have them. The document supplies a better one anyway. TABLE 0 says it was "derived from a
full CAFÉ run over this use case" and publishes the answer:

    Governance tier D2 · exposure E1 · influence I3 · criticality business-critical · topology T2
    Families F1 hybrid, F2, F3, F4, F5, F6, F7, F8, F9, F10, F11, F13   (F12 and F14 absent)

So the Intake Agent is its own golden case, and every one of those is the output of a DETERMINISTIC
service. This is a regression test, not a sampling exercise.

**How the fixture was built, because that decides whether the test means anything.** The activity of
each step comes from the document's own step table (§2.1); every other facet is the PUBLISHED
default for that activity (Annexure E.4's defaults table), and a facet is overridden only where the
document states something explicitly about that step — §1.2's "exposure class E1: record writes and
internal notification only", §1.3's "advisory throughout", Annexure A's "the agents hold no write
credentials; every commit is performed by a deterministic service behind architect review".

Tuning facets until the published answer appeared would make this circular and worthless. Where the
derivation and the document disagree, the disagreement is recorded as a finding — see the tests at
the end, which assert what is NOT derivable rather than pretending it is.
"""
import pytest

from lab.core.usecase import composition, seed
from lab.core.usecase.exposure import derive as derive_risk
from lab.core.usecase.model import Step, Workflow
from lab.core.usecase.obligations import derive as derive_obligations

# ---------------------------------------------------------------------------------------------
# The Intake Agent's own 24 facet-carrying steps. `activity` is the document's; everything else is
# the published default for that activity unless a comment names the sentence that overrode it.
# ---------------------------------------------------------------------------------------------

#: §1.2 — "Exposure class E1 — record writes and internal notification only." Every step that
#: commits does so to the lab's own design-pack repository: a record write, reversible, one record.
_COMMIT = dict(activity="commit", effect="record write", reversibility="reversible",
               blast_radius="single record", audience="internal group",
               authorisation="policy-bounded")

#: The agent steps. §1.3: "Advisory throughout" — they produce records for a human, never effects.
def _agent(step_id, determinism, **kw):
    return Step(id=step_id, activity=kw.pop("activity", "interpret"), determinism=determinism,
                effect="none", audience="internal individual", authorisation="autonomous", **kw)


def _service(step_id, **kw):
    """A deterministic service step. D0 by definition — that is what makes it a service."""
    return Step(id=step_id, determinism="D0", **{**_COMMIT, **kw})


def intake_agent_workflow() -> Workflow:
    """The 24 steps §9 says the guardrail predicates were evaluated against."""
    steps = [
        # Phase 1 — setup. Step 2 persists the validated submission: the first record write.
        _service("1", activity="retrieve", effect="none", authorisation="autonomous"),
        _service("2", activity="transform"),
        # Phase 2 — feasibility. Interpretive work over a submission the enterprise did not author.
        _agent("3", "D1"), _agent("4", "D2"), _agent("5", "D1"), _agent("6", "D1"),
        _agent("7", "D1"), _agent("8", "D2"), _agent("9", "D1"), _agent("10", "D2"),
        _agent("11", "D1"),
        # Step 12's output determines the rigour of a system built later — the class is the reason
        # §1.2 gives for influence I3, and that effect is outside this workflow.
        _agent("12", "D1", determines_externally=3),
        _agent("13", "D1"),
        _service("14", activity="decide", effect="none", authorisation="autonomous"),
        _agent("15", "D1", determines_externally=3),      # the governance tier, likewise
        _service("16", activity="decide", effect="none", authorisation="autonomous"),
        # Phase 3 — risk. 17 assigns the vectors; 18 and 19 derive from them, and what 19 emits IS
        # the control set a downstream system will carry.
        _agent("17", "D1", determines_externally=3),
        _service("18", activity="transform", effect="none", authorisation="autonomous"),
        _service("19", activity="transform", effect="none", authorisation="autonomous",
                 determines_externally=3),
        # Phase 4 — architecture.
        _agent("20", "D1"), _agent("21", "D1"),
        _service("22", activity="transform"),
        # Phase 5 — value. Both are sub-workflows; both write records.
        _agent("23", "D1"), _agent("24", "D2"),
        # Phase 6 — delivery. 25 drafts; 26 routes to Teams (INTERNAL notification, per §1.2); 27
        # provisions only after approval, and Annexure A says every commit sits behind that review.
        _service("25", activity="transform"),
        _service("26", activity="notify", audience="internal group"),
        _service("27", authorisation="per-action human"),
    ]
    return Workflow(steps=tuple(steps), criticality="business-critical")


#: What the whole solution can be told about itself. Step 19's own control set names the terms.
CONDITIONS = {
    "step invokes any registered tool": True,
    "step reads any grounding source": True,
    "step reads any grounding source, tool output or agent response — any content the enterprise "
    "did not author": True,
    "the step reasons over or emits a named concept": True,
    "the step can conclude that nothing is wrong": True,
    "step executes generated or supplied code": False,
    "the step delegates to another agent": False,
    "step invokes a downstream service": True,
    "the step runs without an interactive user at trigger time": True,
}


@pytest.fixture(scope="module")
def workflow():
    return intake_agent_workflow()


@pytest.fixture(scope="module")
def risk(workflow):
    return derive_risk(workflow)


# ---------------------------------------------------------------- the published classification

def test_the_governance_tier_is_the_highest_step_tier(workflow):
    """Q1.5: governance tier = max(step tiers). The document publishes D2."""
    assert max(s.determinism for s in workflow) == "D2"


def test_the_criticality_class_is_business_critical(workflow):
    assert workflow.criticality == "business-critical"


def test_exposure_is_class_one_across_the_whole_solution(risk):
    """§1.2: "Exposure class E1 — record writes and internal notification only." Nothing this
    solution does is irreversible, reaches a cohort, or leaves the organisation."""
    assert max(d["exposure"] for d in risk.values()) == 1


def test_influence_is_class_three(risk):
    """§1.2: "Influence class I3 — its outputs determine the controls a downstream system will
    carry." The asymmetry the whole design turns on: it can barely do harm, and it decides what a
    system built next quarter must do."""
    assert max(d["influence"] for d in risk.values()) == 3


def test_the_asymmetry_is_visible_step_by_step(risk):
    """Not just at the maximum: the steps that DECIDE carry the influence, and none of them has any
    exposure at all. A single score would have called them safe."""
    for step_id in ("12", "15", "17", "19"):
        assert risk[step_id]["influence"] == 3
        assert risk[step_id]["exposure"] <= 1


# ---------------------------------------------------------------- the control set

def test_the_control_set_is_drawn_from_the_published_guardrails(workflow):
    out = derive_obligations(workflow, conditions=CONDITIONS)
    published = {g["id"] for g in seed.live_guardrails()}
    assert out.guardrails() <= published
    assert len(out.guardrails()) >= 12, sorted(out.guardrails())


def test_no_retired_guardrail_ever_enters_the_control_set(workflow):
    out = derive_obligations(workflow, conditions=CONDITIONS)
    assert not (out.guardrails() & {"G11", "G12"})


def test_the_influence_three_guardrails_are_all_present(workflow):
    """I3 mandates them, and they are what §4 calls out as the controls the two most influential
    services need: an evaluation harness, a recall target, and an independently monitored outcome
    assertion."""
    out = derive_obligations(workflow, conditions=CONDITIONS)
    assert {"G18", "G19"} <= out.guardrails()


def test_the_human_confirmation_guardrail_does_not_apply_at_this_exposure_class(workflow):
    """G09 is the one the spec's Annexure C omits while its own Annexure E.6 mandates it — and it
    correctly does NOT fire here, which is worth pinning because it is easy to read the omission as
    harmless on that basis.

    G09 triggers on `step.effect ∈ {external communication, financial or contractual commitment,
    physical or clinical action} ∧ authorisation ≠ per-action human`, and E.6 mandates it from E2
    upward. This solution is E1 — record writes and internal notification only — so no step
    qualifies on either route. The Annexure C omission is still a real defect: it is a dangling
    reference for every E2 or E3 use case this system will assess, which is most of the ones worth
    building.
    """
    out = derive_obligations(workflow, conditions=CONDITIONS)
    assert "G09" not in out.guardrails()
    assert all(s.effect in ("none", "record write") for s in workflow), \
        "the reason G09 stays out is the effect classes, so assert them rather than the outcome"


def test_the_commit_invariant_holds_for_this_solution(workflow):
    """Annexure A: "the agents hold no write credentials; every commit is performed by a
    deterministic service, and every one of them sits behind architect review". That is exactly
    what the invariant tests, so it must hold — if it did not, the solution would be describing a
    design it does not have."""
    out = derive_obligations(workflow, conditions=CONDITIONS)
    assert out.commit_invariant_holds, [v.reason for v in out.violations]


# ---------------------------------------------------------------- the composition

@pytest.fixture(scope="module")
def composed(workflow):
    return composition.compose(workflow, topology="T2", conditions=CONDITIONS,
                               grounding_sources=4)


def test_the_topology_is_agent_orchestrated(composed):
    """Figure 2: "Topology T2, agent-orchestrated." """
    assert composed.topology == "T2"


def test_grounding_is_the_federated_variant(composed):
    """Figure 2 says "F1 hybrid": the retrieval is federated because the sources exceed one —
    a structured store, a retrieval index and two graphs."""
    assert composed.variants.get("F1") == "federated"


@pytest.mark.parametrize("family", ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10",
                                    "F11"])
def test_every_family_the_document_publishes_is_present(family, composed):
    assert family in composed.families


def test_delegation_is_absent_because_the_topology_is_not_delegated(composed):
    """F14 is T4-only, and this is T2. Absence is a result: "a composition carrying a family no
    step calls for is over-built"."""
    assert "F14" not in composed.families


def test_egress_control_is_absent_because_nothing_leaves_the_organisation(composed):
    """F12 is the one the document omits from an otherwise complete list, and it follows from E1:
    record writes and internal notification only. Nothing here emits externally."""
    assert "F12" not in composed.families


def test_every_family_present_binds_the_guardrails_it_enforces(composed):
    assert set(composed.enforcement) == set(composed.families)
    assert all(composed.enforcement[f] for f in ("F1", "F2", "F4"))


# ---------------------------------------------------------------- what is NOT derivable, said so

def test_release_control_is_not_derivable_from_the_facets_the_document_states(composed, workflow):
    """A RECORDED DIVERGENCE, asserted rather than skipped so it cannot be quietly forgotten.

    Figure 2 lists F13 (release and rate control) among the families. F13 fires on
    `blast_radius ∈ {cohort, population}`, and no step in §2.1 is described as acting on more than
    one submission at a time — the whole process assesses ONE use case per run. So the published
    family list assumes a blast radius the specification never states.

    Two readings, and the difference matters. Either F13 belongs because a change to a SHARED
    artifact reaches every open business case at once — which is CR-18's staged-release rule, and
    would make F13 a property of the artifact publication path rather than of any step — or F13 is
    over-built in Figure 2. The first is more likely and would mean the facet schema has no way to
    express "this step reads something whose change is systemic", which the blast-radius facet's
    own "read twice" note gestures at without resolving.

    Either way it is a question for the spec owner, not something to make green by inventing a
    cohort-scoped step."""
    assert "F13" not in composed.families
    assert all(s.blast_radius in ("single record", "single subject") for s in workflow)


def test_influence_needs_an_effect_outside_this_workflow_to_be_derivable(workflow):
    """The honest limitation. I3 comes from "its outputs determine the controls a DOWNSTREAM system
    will carry", and that system is not a step here — so influence is only derivable because the
    fixture declares `determines_externally` on the four steps whose output leaves the process. An
    in-graph-only walk would score this solution influence 0, which is the wrong answer in the
    direction that drops controls."""
    external = [s.id for s in workflow if s.determines_externally]
    assert external, "without these the published I3 is not derivable at all"
    assert set(external) == {"12", "15", "17", "19"}
