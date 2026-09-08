"""decision-mcp — the deterministic CAFÉ derivations as tools.

The derivations themselves are tested in `tests/unit/core/usecase`. What is tested here is what the
SERVER adds: a malformed facet vector refusing at the boundary rather than failing to match a
predicate two derivations later, a refusal arriving as a sentence, and — the one that matters most
— every answer saying WHICH rules it used, so an ungoverned derivation can never be mistaken for a
governed one.
"""
import pytest
from fastmcp.exceptions import ToolError

from fixtures.reference import FakeReferenceLibrary, SeededArtifact
from lab.core.reference.model import ArtifactKind
from lab.core.usecase import seed
from lab.platform.contracts import DecisionTools
from lab.substrate.mcp.decision import server as S

ANSWERS = {c: False for c in seed.NAMED_CONDITIONS}

COMMIT = {"id": "s1", "activity": "commit", "determinism": "D0", "effect": "record write"}
INTERPRET = {"id": "s0", "activity": "interpret", "determinism": "D2", "effect": "none",
             "determines": ["s1"]}


def wf(*steps, criticality="routine"):
    return {"steps": list(steps or (COMMIT,)), "criticality": criticality}


# ---------------------------------------------------------------- the contract

def test_the_server_registers_exactly_the_catalogue_it_declares():
    import asyncio
    import inspect
    tools = S.server.mcp.list_tools()
    if inspect.isawaitable(tools):
        tools = asyncio.run(tools)
    registered = {t.name for t in (tools.values() if isinstance(tools, dict) else tools)}
    assert registered == DecisionTools.names()


def test_nothing_here_writes():
    assert not hasattr(DecisionTools, "WRITE")


# ---------------------------------------------------------------- step 14 and 16

def test_readiness_passes_when_all_four_gates_are_evidenced():
    out = S.decision_readiness({"A": True, "B": True, "C": True, "D": True})
    assert out["verdict"] == "pass" and out["failed"] == []


def test_readiness_names_every_gate_that_failed_not_just_the_first():
    out = S.decision_readiness({"A": True, "B": False, "C": False, "D": True})
    assert set(out["failed"]) == {"B", "C"}


def test_a_gate_nobody_assessed_refuses_rather_than_passing():
    with pytest.raises(ToolError) as e:
        S.decision_readiness({"A": True, "B": True, "C": True})
    assert "D" in str(e.value)


def test_feasibility_says_whether_the_run_must_halt():
    reject = S.decision_feasibility(capability_matched=False, existing_realisation=False,
                                    capability_is_commodity=False, capability_is_mature=False,
                                    capability_meets_target=False)
    proceed = S.decision_feasibility(capability_matched=True, existing_realisation=False,
                                     capability_is_commodity=False, capability_is_mature=False,
                                     capability_meets_target=False)
    assert reject["halts"] is True and reject["rule"]
    assert proceed["halts"] is False


def test_an_existing_realisation_returns_the_use_case_as_an_integration():
    out = S.decision_feasibility(capability_matched=True, existing_realisation=True,
                                 capability_is_commodity=False, capability_is_mature=False,
                                 capability_meets_target=False)
    assert out["verdict"] == "integration" and out["halts"] is True


# ---------------------------------------------------------------- step 18

def test_exposure_and_influence_are_derived_per_step():
    out = S.decision_exposure(wf(INTERPRET, COMMIT))
    assert out["steps"]["s1"]["exposure"] == 1
    assert out["steps"]["s0"]["influence"] == 1


def test_an_advisory_step_can_carry_the_highest_influence_in_the_workflow():
    """The case a single score misses entirely, and the reason the pair exists."""
    severe = {"id": "s1", "activity": "commit", "effect": "physical or clinical action"}
    out = S.decision_exposure(wf(INTERPRET, severe))
    assert out["steps"]["s0"]["exposure"] == 0
    assert out["steps"]["s0"]["influence"] == 3
    assert out["max_influence"] == 3


def test_a_malformed_facet_vector_refuses_at_the_boundary():
    """Naming the step and the facet here beats silently failing to match a predicate later."""
    with pytest.raises(ToolError) as e:
        S.decision_exposure(wf({"id": "s1", "activity": "commit", "effect": "mild inconvenience"}))
    assert "mild inconvenience" in str(e.value)


def test_a_workflow_with_no_steps_refuses():
    with pytest.raises(ToolError):
        S.decision_exposure({"steps": []})


# ---------------------------------------------------------------- step 19

def test_obligations_returns_a_control_set_and_the_commit_invariant():
    out = S.decision_obligations(wf(COMMIT), conditions=ANSWERS)
    assert out["guardrails"]
    assert out["commit_invariant_holds"] is True
    assert out["by_step"]["s1"]


def test_a_commit_invariant_breach_is_reported_rather_than_raised():
    """A breach is a finding the architect must see. A run that crashed would destroy the evidence
    that shows why."""
    loose = {"id": "s1", "activity": "commit", "effect": "external communication",
             "authorisation": "autonomous"}
    out = S.decision_obligations(wf(INTERPRET, loose), conditions=ANSWERS)
    assert out["commit_invariant_holds"] is False
    assert out["violations"][0]["step"] == "s1"


def test_an_unanswered_condition_refuses_rather_than_producing_a_short_set():
    """The failure this exists for: a control set that is quietly one guardrail short looks exactly
    like a correct one at review."""
    with pytest.raises(ToolError) as e:
        S.decision_obligations(wf(COMMIT), conditions={})
    assert "condition" in str(e.value).lower()


# ---------------------------------------------------------------- step 22

def test_composition_derives_the_families_the_steps_call_for():
    out = S.decision_composition(wf(COMMIT), topology="T2", conditions=ANSWERS)
    assert "F4" in out["families"]          # an effect of record write or above
    assert out["enforcement"]["F4"]


def test_a_family_no_step_calls_for_is_absent():
    """"A composition carrying a family no step calls for is over-built" — absence is a result."""
    out = S.decision_composition(wf(COMMIT), topology="T2", conditions=ANSWERS)
    assert "F14" not in out["families"]     # delegation is T4 only
    assert "F12" not in out["families"]     # nothing egresses and nothing sensitive is read


def test_an_obligation_with_nowhere_to_land_is_named():
    out = S.decision_composition(wf(COMMIT), topology="T2", conditions=ANSWERS,
                                 obligations_required=["G02", "G99"])
    assert out["unbound"] == ["G99"]


def test_an_unpublished_topology_refuses():
    with pytest.raises(ToolError):
        S.decision_composition(wf(COMMIT), topology="T9", conditions=ANSWERS)


# ---------------------------------------------------------------- where the rules came from

def test_every_derivation_says_which_rules_it_used():
    """The one thing that must never be silent. An ungoverned answer and a governed one are
    otherwise indistinguishable in a design package."""
    for out in (S.decision_obligations(wf(COMMIT), conditions=ANSWERS),
                S.decision_composition(wf(COMMIT), topology="T2", conditions=ANSWERS)):
        assert out["rules_source"]["kind"] == "local seed"
        assert "pin_id" in out["rules_source"]["note"]


def governed_mapping():
    """A governed copy of the class mapping, as the corpus returns it: records keyed by the
    master's own headers, not the positional rows the local seed holds."""
    return SeededArtifact(
        artifact_id="guardrail-mapping", kind=ArtifactKind.RECORD, record_type="risk-class",
        records=[{"record_id": "r0", "Class": "Baseline every step",
                  "Mandatory": "G01 prompt integrity · G03 agent identity"},
                 {"record_id": "r1", "Class": "E1 — contained",
                  "Mandatory": "G02 tool scoping · G08 budgets"},
                 {"record_id": "r2", "Class": "I1 — contained",
                  "Mandatory": "An evaluation harness with a stated accuracy target"}])


def test_a_pin_makes_the_derivation_read_the_governed_corpus():
    library = FakeReferenceLibrary([governed_mapping()])
    with S.server.container.reference.override(library):
        pin = library.pin()
        out = S.decision_obligations(wf(COMMIT), conditions=ANSWERS, pin_id=pin.pin_id,
                                     run_id="wfr-1", process="use_case_design",
                                     field="obligations")
    assert out["rules_source"]["kind"] == "governed corpus"
    assert out["rules_source"]["pin_id"] == pin.pin_id
    assert out["rules_source"]["versions"]


def test_a_derivation_under_a_pin_is_recorded_against_the_derived_field():
    """FR-44: the rules a run obeyed are part of how the field was derived."""
    library = FakeReferenceLibrary([governed_mapping()])
    with S.server.container.reference.override(library):
        pin = library.pin()
        S.decision_obligations(wf(COMMIT), conditions=ANSWERS, pin_id=pin.pin_id,
                               run_id="wfr-9", process="use_case_design", field="obligations")
    consumed = library.consumers(artifact_id="guardrail-mapping",
                                 version=pin.version_of("guardrail-mapping").version)
    assert consumed and consumed[0].field == "obligations"


def test_an_expired_pin_refuses_as_a_sentence():
    library = FakeReferenceLibrary([SeededArtifact("guardrail-mapping", ArtifactKind.RECORD,
                                                   record_type="risk-class")])
    with S.server.container.reference.override(library):
        with pytest.raises(ToolError) as e:
            S.decision_obligations(wf(COMMIT), conditions=ANSWERS, pin_id="pin-nope",
                                   run_id="r", process="p", field="f")
    assert "Remedy:" in str(e.value)


def test_a_pin_without_attribution_refuses():
    """A read under a pin must name the field it was for, or the consumption trail is useless."""
    library = FakeReferenceLibrary([SeededArtifact("guardrail-mapping", ArtifactKind.RECORD,
                                                   record_type="risk-class")])
    with S.server.container.reference.override(library):
        pin = library.pin()
        with pytest.raises(ToolError):
            S.decision_obligations(wf(COMMIT), conditions=ANSWERS, pin_id=pin.pin_id)


# ---------------------------------------------------------------- spans carry no content

def test_no_span_attribute_carries_a_rule_or_a_step_s_words(monkeypatch):
    recorded: dict = {}

    class Span:
        def set_attribute(self, key, value): recorded[key] = value
        def set_attributes(self, values): recorded.update(values)

    monkeypatch.setattr(S, "span", lambda: Span())
    S.decision_exposure(wf(INTERPRET, COMMIT))
    S.decision_obligations(wf(COMMIT), conditions=ANSWERS)
    S.decision_composition(wf(COMMIT), topology="T2", conditions=ANSWERS)
    S.decision_readiness({"A": True, "B": True, "C": True, "D": True})

    assert recorded, "the tools record nothing, so this would pass vacuously"
    for key, value in recorded.items():
        assert isinstance(value, (int, float, bool)), f"{key} is not a count/shape: {value!r}"


# ------------------------------------------------- the mapper, and what a live corpus read found

class _Rec:
    def __init__(self, body): self.body = body


def test_the_mapper_gives_the_domain_the_shape_it_reads():
    """A master is a table, so everything in it is text. The domain reads lists. This is the
    adapter's mapper, and every one of these three conversions was a live failure first."""
    rows = S.from_corpus([_Rec({"record_id": "r1", "id": "F14", "name": "Delegation",
                                "predicate": "", "topology": "T4; T3",
                                "guardrails": "G07"})])
    assert rows == [{"id": "F14", "name": "Delegation",
                     "topology": ["T4", "T3"], "guardrails": ["G07"]}]


def test_an_empty_cell_is_dropped_rather_than_kept_as_an_empty_string():
    """The subtle one. Every family gets a `topology` column because ONE family has a topology, and
    `families_for` asks whether that key is None. Kept as "", the other thirteen would look
    topology-restricted and vanish from every composition — silently, and only under a pin."""
    rows = S.from_corpus([_Rec({"record_id": "r1", "id": "F2", "topology": "",
                                "predicate": "step.determinism ≥ D1"})])
    assert "topology" not in rows[0]
    assert rows[0]["predicate"] == "step.determinism ≥ D1"


def test_the_store_s_own_id_is_not_part_of_the_row():
    assert "record_id" not in S.from_corpus([_Rec({"record_id": "r1", "id": "G01"})])[0]


def test_a_retired_guardrail_from_the_corpus_never_enters_a_control_set():
    """The corpus publishes all 26 guardrails, because a retired identifier must stay resolvable
    for citations already written down. The seed path filtered them and the corpus path did not, so
    a governed run evaluated G11 and refused on a condition no live guardrail asks."""
    from lab.core.usecase import obligations, seed
    from lab.core.usecase.model import Step, Workflow
    published = seed.artifact("guardrails")["guardrails"]
    assert {"G11", "G12"} <= {g["id"] for g in published}

    workflow = Workflow(steps=(Step(**INTERPRET), Step(**COMMIT)), criticality="routine")
    with_corpus = obligations.derive(workflow, conditions=ANSWERS, guardrails=published)
    with_seed = obligations.derive(workflow, conditions=ANSWERS)
    assert not ({"G11", "G12"} & with_corpus.guardrails())
    assert with_corpus.guardrails() == with_seed.guardrails()
