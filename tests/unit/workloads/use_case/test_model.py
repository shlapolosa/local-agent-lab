"""The use-case model: grows by id, stays legal, round-trips through the engine's spec."""
import pytest

from lab.core.archimate.engine import Model as EngineModel
from lab.workloads import ids
from lab.workloads.usecase.model import LAYER_OF, Model


def _build(spec):
    """Exactly what adoit-mcp's `_build` does with a spec — the shape the renderer must accept."""
    m = EngineModel(spec["name"], mid=spec["id"])
    for e in spec["elements"]:
        m.el(e["id"], e["type"], e["name"], e.get("doc"), folder=e.get("folder"))
    for r in spec["relations"]:
        m.rel(r["type"], r["src"], r["tgt"], rid=r.get("id"), accessType=r.get("accessType"))
    return m


def test_an_element_is_updated_by_id_and_its_props_are_merged():
    m = Model()
    m.el("bf-assess", "BusinessFunction", "assess referral", props={"verb": "assess"})
    m.el("bf-assess", "BusinessFunction", "", props={"tier": "D1"})
    assert len(m.elements) == 1
    e = m.elements["bf-assess"]
    assert e["name"] == "assess referral", "a blank name never erases a known one"
    assert e["props"] == {"verb": "assess", "tier": "D1"}
    assert e["folder"] == LAYER_OF["BusinessFunction"] == "Business"


def test_an_unknown_type_is_a_mapper_bug_not_data():
    with pytest.raises(ValueError):
        Model().el("x", "Widget", "x")


def test_a_relation_is_deduplicated_on_endpoints_and_type_with_the_stable_id():
    m = Model()
    m.el("bf", "BusinessFunction", "f"); m.el("cap", "Capability", "c")
    assert m.rel("Realization", "bf", "cap") and m.rel("Realization", "bf", "cap")
    assert len(m.relations) == 1
    assert next(iter(m.relations.values()))["id"] == ids.rid("bf", "Realization", "cap")


def test_an_illegal_relation_is_dropped_and_counted_never_raised():
    m = Model()
    m.el("node", "Node", "n"); m.el("ac", "ApplicationComponent", "c")
    assert m.rel("Assignment", "node", "ac") is False        # not in the matrix
    assert m.relations == {}
    assert m.dropped[0]["type"] == "Assignment" and "Realization" in m.dropped[0]["allowed"]
    assert m.rel("Realization", "node", "ac") is True


def test_a_relation_to_an_undeclared_endpoint_is_dropped_with_its_reason():
    m = Model()
    m.el("bf", "BusinessFunction", "f")
    assert m.rel("Realization", "bf", "missing") is False
    assert m.dropped[0]["reason"] == "endpoint not declared"


def test_the_spec_round_trips_and_builds_through_the_engine():
    m = Model(name="triage", id="usecase")
    m.el("bf", "BusinessFunction", "assess", props={"verb": "assess"})
    m.el("bo", "BusinessObject", "referral")
    m.rel("Access", "bf", "bo", accessType="Write")
    spec = m.to_spec()
    assert spec["standard_views"] is True and spec["elements"][0]["props"] == {"verb": "assess"}
    again = Model.from_spec(spec)
    assert again.to_spec() == spec, "from_spec(to_spec(m)) is the identity"
    assert again.touched == set(), "loading is not a step"
    built = _build(spec)                                    # the renderer's own reconstruction
    assert built.validate_relations() == []
    assert built.relations[ids.rid("bf", "Access", "bo")][3] == {"accessType": "Write"}


def test_touched_names_what_one_step_added_and_the_delta_carries_the_endpoints():
    m = Model()
    m.el("bf", "BusinessFunction", "assess")
    m.clear_touched()
    m.el("cap", "Capability", "Referral management")
    m.rel("Realization", "bf", "cap")
    delta = m.delta_spec("coverage_map")
    assert {e["id"] for e in delta["elements"]} == {"bf", "cap"}, "the existing endpoint is drawn"
    assert [r["type"] for r in delta["relations"]] == ["Realization"]
    assert delta["views"][0]["elements"] == ["bf", "cap"] and delta["views"][0]["id"] == "delta-coverage-map"
    assert delta["relations"][0]["src"] == "bf"


def test_the_model_id_never_collides_with_the_root_element_the_engine_would_mint_alike():
    from lab.workloads.usecase import mappers
    m = Model()
    mappers.apply("frame", {"problem": "p", "for_whom": "w", "expected_change": "e", "accountable_owner": "o"}, m, {})
    spec = m.to_spec()
    assert spec["id"] != mappers.ROOT and mappers.ROOT in {e["id"] for e in spec["elements"]}
    assert _build(spec).render.__name__ == "render"     # builds; the XSD check runs in the smoke


def test_counts_and_by_type_read_the_model():
    m = Model()
    m.el("a", "ApplicationComponent", "a"); m.el("b", "ApplicationComponent", "b")
    m.el("bf", "BusinessFunction", "f")
    assert [e["id"] for e in m.by_type("ApplicationComponent")] == ["a", "b"]
    # `gaps` is beside `dropped` and means something else: a relation the MATRIX refused versus a
    # join a MAPPER could not make. Counted separately because the two have different owners.
    assert m.counts() == {"elements": 3, "relations": 0, "dropped": 0, "gaps": 0}
    assert m.props_of("nope") == {} and m.has("a")
