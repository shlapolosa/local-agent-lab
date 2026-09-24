"""Every step's mapper: legal, total, idempotent, and joined on the ids the steps share."""
import pytest

from lab.core.archimate import relrepair
from lab.workloads.usecase import mappers
from lab.workloads.usecase.model import Model
from lab.workloads.usecase.steps import STEPS

# One run's outputs, in the order the steps produce them — each the SHAPE its schema accepts.
OUTPUTS = {
    "frame": {"problem": "Referrals wait eleven days before a clinician reads them",
              "for_whom": "referring GPs", "expected_change": "median below two days",
              "accountable_owner": "Dr Aisha Khan"},
    "elements": {"active": [{"name": "triage nurse", "kind": "role"}],
                 "behavioural": [{"name": "assess referral", "verb": "assess", "object": "referral"}],
                 "passive": [{"name": "referral"}]},
    "coverage_map": {"matched": [{"function": "assess referral", "capability_id": "cap-1",
                                  "capability_label": "Referral management", "level": 3,
                                  "path": ["Care", "Referral management"], "confidence": "lookup"}],
                     "heat_map": {"commodity": False, "mature": True, "meets_target": False, "source": "s"},
                     "functions_without_capability": [], "capabilities_without_function": []},
    "realisation_match": {"matched": [{"element": "assess referral", "realised_by": "Cerner triage module",
                                       "confidence": "survey"}],
                          "unrealised": [], "existing": True},
    "criticality_band": {"band": "business-critical", "provisional": True,
                         "dominant_failure_mode": "a referral is missed"},
    "quality_attributes": {"scenarios": [{"function": "assess referral", "stimulus": "a referral arrives",
                                          "response": "a band is returned", "response_measure": 2,
                                          "unit": "seconds", "percentile": 95, "taken_from": "clause 4"}]},
    "ontology_delta": {"concepts": [{"object": "referral", "status": "defined", "note": "HL7"}], "conflicts": []},
    "workflow_graph": {"nodes": [{"id": "n1", "activity": "read the referral", "performed_by": "triage nurse",
                                  "function": "assess referral"},
                                 {"id": "n2", "activity": "record the band", "performed_by": "triage nurse",
                                  "function": "assess referral"}],
                       "edges": [{"from": "n1", "to": "n2", "data_class": "triage band"}]},
    "source_contracts": {"sources": [{"source": "referral", "sensitivity": "confidential",
                                      "freshness": "dynamic", "permission_scope": "clinical staff",
                                      "citation_policy": "cite the referral id"}]},
    "assertions": {"assertions": [{"statement": "every urgent referral is seen within 24 hours",
                                   "evaluated_against": "PAS", "reads_workflow_output": False}]},
    "determinism": {"steps": [{"id": "n1", "tier": "D2", "necessity": "by necessity"},
                              {"id": "n2", "tier": "D0", "necessity": "by default"}],
                    "governance_tier": "D2", "graph_is_explicit": True},
    "facet_vectors": {"steps": [{"id": "n1", "activity": "interpret", "determinism": "D2", "effect": "none",
                                 "blast_radius": "one record", "conditions": {}},
                                {"id": "n3", "activity": "notify", "determinism": "D0",
                                 "effect": "message", "conditions": {}}]},
    "risk": {"steps": {"n1": {"exposure": 1, "influence": 2}}},
    "obligations": {"guardrails": ["G01", "G02"],
                    "by_step": {"n1": [{"guardrail": "G01", "text": "Log every inference", "source": "ASI01"}]}},
    "build_surface": {"incumbent_considered": True, "incumbent": "Cerner", "surface": "Foundry hosted agent",
                      "topology": "T2", "unenforceable_obligations": []},
    "composition": {"topology": "T2", "families": ["F2", "F4"], "enforcement": {"F2": ["G01"], "F4": []},
                    "unbound": []},
    "component_selection": {"selected": [{"capability": "inference", "component_id": "cmp-model",
                                          "component": "Foundry model catalog",
                                          "rejected_alternatives": ["self-hosted"]}],
                            "building_blocks": [{"what": "the referrals portal", "owner": "portal team"}],
                            "tradeoffs": [], "unresolved": []},
    "cost_inputs": {"build_amount": 250000, "build_provenance": "budget bucket", "notes": []},
    "cost": {"monthly": {"expected": 250}, "year_one": {"expected": 3000}},
    "benefit": {"summary": {"annual_benefit": 90000.0, "payback_months": 0.4},
                "recommendation": {"verdict": "proceed"}},
    "delivery_artifacts": {"service_contracts": [{"name": "Triage referral", "consumers": ["assess referral"],
                                                  "service_level": "p95 < 2 s", "service_level_source": "clause 4",
                                                  "owned_entities": ["referral"]}],
                           "work_items": [{"key": "EPIC-1", "title": "Build the triage agent", "owner": "lead"},
                                          {"key": "EPIC-1.1", "title": "Wire the model", "owner": "lead",
                                           "parent": "EPIC-1"}],
                           "catalog_entry": {"name": "Referral triage", "owner": "lead", "capability": "cap-1"}},
}

POOL = {"component_catalogue": [{"id": "cmp-model", "zone": "mod", "name": "Foundry model catalog",
                                 "families": ["F2"]},
                                {"id": "cmp-vault", "zone": "ident", "name": "Key Vault"}],
        "topology_archetypes": [{"id": "T1", "value": "A1; A7"}, {"id": "T2", "value": "A2; A3; A5"}],
        "composition": OUTPUTS["composition"]}


def run_all(outputs=OUTPUTS, pool=POOL) -> Model:
    m = Model()
    for key, out in outputs.items():
        assert mappers.apply(key, out, m, pool), key
    return m


def test_every_agent_step_has_a_mapper_and_every_mapper_is_exercised_here():
    keyed = {s.key for s in STEPS} - mappers.UNMAPPED
    assert keyed <= set(mappers.MAPPERS), "an agent step whose output never reaches the model"
    assert not (mappers.UNMAPPED & set(mappers.MAPPERS)), "unmapped and mapped at once"
    assert set(mappers.MAPPERS) == set(OUTPUTS), "a mapper this test does not feed"


def test_a_full_run_leaves_the_model_legal_with_nothing_dropped():
    m = run_all()
    assert m.dropped == [], m.dropped
    for r in m.relations.values():
        ok, _ = relrepair.check(m.elements[r["src"]]["type"], r["type"], m.elements[r["tgt"]]["type"])
        assert ok, r
    assert m.counts()["relations"] > 20


def test_applying_the_same_outputs_twice_changes_nothing():
    m = run_all()
    once = m.to_spec()
    for key, out in OUTPUTS.items():
        mappers.apply(key, out, m, POOL)
    assert m.to_spec() == once


def test_the_steps_join_on_the_workflow_node_id():
    """Steps 10, 15, 17, 18 and 19 all speak of `n1`: one BusinessProcess carries every facet."""
    m = run_all()
    bp = m.elements["bp-n1"]
    assert bp["name"] == "read the referral"
    p = bp["props"]
    assert p["tier"] == "D2" and p["effect"] == "none" and p["exposure"] == 1 and p["blast_radius"] == "one record"
    assert ("con-g01", "bp-n1", "Association") in m.relations
    assert m.elements["bp-n3"]["name"] == "notify", "a facet id the graph did not name still lands"
    assert ("bp-n1", "bp-n2", "Triggering") in m.relations
    assert m.relations[("bp-n1", "bo-triage-band", "Access")]["accessType"] == "Write"


def test_the_business_layer_joins_on_the_function_name():
    m = run_all()
    assert ("bf-assess-referral", "cap-1", "Realization") in m.relations
    assert ("bf-assess-referral", "bo-referral", "Access") in m.relations
    assert ("ac-cerner-triage-module", "bf-assess-referral", "Serving") in m.relations
    assert ("bf-assess-referral", "req-assess-referral-1", "Realization") in m.relations
    assert ("bf-assess-referral", "bp-n1", "Aggregation") in m.relations
    assert ("ba-triage-nurse", "bp-n1", "Assignment") in m.relations
    assert m.elements["bo-referral"]["props"]["sensitivity"] == "confidential"
    assert m.elements["bo-referral"]["props"]["ontology.status"] == "defined"


def test_cafe_tags_come_from_the_catalogue_the_step_was_shown():
    m = run_all()
    ac = m.elements["ac-cmp-model"]
    assert ac["props"]["cafe.zone"] == "mod" and ac["props"]["cafe.component_id"] == "cmp-model"
    assert ac["props"]["cafe.families"] == "F2"
    assert ("zone-mod", "ac-cmp-model", "Aggregation") in m.relations
    assert ("fam-f2", "ac-cmp-model", "Aggregation") in m.relations
    assert ("ac-cmp-model", "con-g01", "Realization") in m.relations, "the family's enforcement point"
    assert not any(r["src"].startswith("node-") and r["tgt"].startswith("ac-") for r in m.relations.values()), \
        "step 21 never said which surface hosts which component — nothing is invented"
    assert ("ac-cmp-model", "af-inference", "Assignment") in m.relations
    root = m.elements["usecase"]["props"]
    assert root["cafe.archetype"] == "A2" and root["cafe.topology"] == "T2"
    assert root["cafe.archetypes"] == "A2; A3; A5", "the whole admitted list rides beside the choice"
    assert root["criticality.band"] == "business-critical" and root["cost.monthly_expected"] == 250
    assert root["cost.build_amount"] == 250000
    assert m.elements["bb-the-referrals-portal"]["props"]["kind"] == "building-block"


def test_delivery_maps_services_and_work_onto_the_selected_components():
    m = run_all()
    assert ("usecase", "svc-triage-referral", "Aggregation") in m.relations
    assert not any(r["tgt"] == "svc-triage-referral" and r["type"] == "Realization" for r in m.relations.values()), \
        "which component realises a service is not something step 25 says"
    assert ("svc-triage-referral", "bf-assess-referral", "Serving") in m.relations
    assert ("wp-epic-1", "wp-epic-1-1", "Aggregation") in m.relations
    assert ("wp-epic-1", "dlv-referral-triage", "Realization") in m.relations
    assert ("usecase", "out-1", "Aggregation") in m.relations
    assert not any(r["tgt"] == "out-1" and r["src"].startswith("cap-") for r in m.relations.values()), \
        "an outcome is not realised by every capability — only anchored on what it is evaluated against"


def test_a_topology_archetype_row_may_already_be_decoded_as_a_list():
    m = Model()
    pool = dict(POOL) | {"topology_archetypes": [{"id": "T2", "value": ["A3", "A5"]}]}
    mappers.apply("composition", OUTPUTS["composition"], m, pool)
    assert m.elements["usecase"]["props"]["cafe.archetype"] == "A3"


def test_an_assertion_is_anchored_on_what_it_is_evaluated_against_when_the_model_has_it():
    m = run_all()
    out = dict(OUTPUTS["assertions"]) | {"assertions": [{"statement": "the referral is complete",
                                                        "evaluated_against": "referral"}]}
    mappers.apply("assertions", out, m, POOL)
    assert ("bo-referral", "out-1", "Association") in m.relations
    assert m.dropped == []


def test_a_mapper_that_raises_is_recorded_and_leaves_the_model_as_it_was(monkeypatch):
    m = Model()
    mappers.apply("frame", OUTPUTS["frame"], m, POOL)
    before = m.to_spec()

    def boom(out, model, pool):
        model.el("x", "Node", "x")
        raise RuntimeError("mapper bug")

    monkeypatch.setitem(mappers.MAPPERS, "elements", boom)
    assert mappers.apply("elements", OUTPUTS["elements"], m, POOL) is False
    assert "x" not in m.elements and m.to_spec()["elements"] == before["elements"]
    assert m.dropped[-1]["mapper"] == "elements" and "mapper bug" in m.dropped[-1]["error"]


def test_an_output_without_a_mapper_or_of_the_wrong_shape_is_a_no_op():
    m = Model()
    assert mappers.apply("nothing", {"a": 1}, m, POOL) is False
    assert mappers.apply("frame", "not a mapping", m, POOL) is False
    assert m.elements == {}


def test_the_summary_is_names_by_type_and_the_families_still_owed():
    m = run_all()
    s = mappers.summary(m, POOL)
    assert {"id": "ac-cmp-model", "name": "Foundry model catalog"} in s["elements"]["ApplicationComponent"]
    assert s["required_families"] == ["F2", "F4"]
    assert s["realised_families"] == {"F2": ["ac-cmp-model"], "F4": []}
    assert "props" not in str(s) and s["counts"]["dropped"] == 0
