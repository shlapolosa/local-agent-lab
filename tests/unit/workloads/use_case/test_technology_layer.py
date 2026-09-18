"""Part 5 — a technology capability is staged at the layer it belongs to.

The two maps answer different questions and ArchiMate already has a place for each. A BUSINESS
capability is a Strategy-layer `Capability`, realized by the BusinessFunctions that deliver it. A
TECHNOLOGY capability is an ability of the SOLUTION — an `ApplicationService` the estate exposes,
realized by the components selected to provide it and serving the business function that needed it.

Putting the second on the Strategy layer would make the EA repository answer "what ability does this
business possess" with a list of Microsoft products, which is the category error the whole two-maps
decision exists to prevent.
"""
from lab.core.archimate import relrepair
from lab.workloads.usecase import mappers
from lab.workloads.usecase.model import Model

ELEMENTS = {"active": [{"name": "Triage nurse", "kind": "role"}],
            "behavioural": [{"name": "assess urgency", "verb": "assess", "object": "Referral"}],
            "passive": [{"name": "Referral"}]}
MATCH = {"matched": [{"function": "assess urgency", "capability_id": "Knowledge · Agentic retrieval",
                      "capability_label": "Agentic retrieval", "confidence": "lookup",
                      "level": 2, "path": ["Knowledge", "Agentic retrieval"]}]}


def built() -> Model:
    model = Model(name="t", id="usecase-model")
    mappers.apply("elements", ELEMENTS, model, {})
    mappers.apply("coverage_map", MATCH, model, {})
    return model


def test_a_matched_technology_capability_becomes_an_application_service():
    model = built()
    services = [e for e in model.elements.values() if e["type"] == "ApplicationService"]
    assert [s["name"] for s in services] == ["Agentic retrieval"]


def test_it_is_never_a_strategy_layer_capability():
    """The assertion that carries the decision. A Capability element here would be a claim that the
    business possesses "Agentic retrieval", which it does not — a vendor does."""
    assert not [e for e in built().elements.values() if e["type"] == "Capability"]


def test_the_service_serves_the_function_that_needed_it():
    """Direction matters. The solution SERVES the business; the business does not realize a product.
    Realization would read as the function delivering the capability to the enterprise."""
    model = built()
    svc = next(e for e in model.elements.values() if e["type"] == "ApplicationService")
    served = [r for r in model.relations.values()
              if r["src"] == svc["id"] and r["type"] == "Serving"]
    assert served and model.elements[served[0]["tgt"]]["type"] == "BusinessFunction"


def test_the_service_carries_the_key_the_rest_of_the_framework_joins_on():
    """So a reader of the repository — or a later run — can get from a drawn box back to the
    guardrails it must satisfy and the components that could provide it."""
    svc = next(e for e in built().elements.values() if e["type"] == "ApplicationService")
    assert svc["props"]["cafe.capability"] == "Knowledge · Agentic retrieval"
    assert svc["props"]["cafe.domain"] == "Knowledge"


def test_a_business_map_match_still_lands_on_the_strategy_layer():
    """Dormant, not deleted. When an enterprise publishes a conformant business map, its matches
    carry synthetic ids and must model as Strategy-layer Capability — reinstating that should be a
    setting, not a rewrite."""
    model = Model(name="t", id="usecase-model")
    mappers.apply("elements", ELEMENTS, model, {})
    mappers.apply("coverage_map", {"matched": [
        {"function": "assess urgency", "capability_id": "cap-7f3a91",
         "capability_label": "Detect Delay", "confidence": "lookup"}]}, model, {})
    assert [e["type"] for e in model.elements.values() if e["id"] == "cap-7f3a91"] == ["Capability"]


def test_every_relation_the_mapper_emits_is_legal_and_none_is_dropped():
    model = built()
    for r in model.relations.values():
        ok, _ = relrepair.check(model.elements[r["src"]]["type"], r["type"],
                                model.elements[r["tgt"]]["type"])
        assert ok, f"{r['src']} -{r['type']}-> {r['tgt']}"
    assert model.dropped == []


def test_applying_the_mapper_twice_changes_nothing():
    once = built()
    twice = built()
    mappers.apply("coverage_map", MATCH, twice, {})
    assert set(once.elements) == set(twice.elements)
    assert set(once.relations) == set(twice.relations)


SELECTION = {"selected": [{"capability": "Knowledge · Agentic retrieval",
                           "component_id": "cmp-foundryiq", "component": "Foundry IQ"}],
             "tradeoffs": [], "unresolved": []}


def test_a_selected_component_realises_the_service_the_match_asked_for():
    """The join that makes the two halves one architecture. Step 5 says which technology capability
    the use case needs; step 21 says which component provides it; they name it with the SAME key,
    so the repository shows a component realising a service serving a business function rather than
    two disconnected clouds of boxes."""
    model = built()
    mappers.apply("component_selection", SELECTION, model, {})
    svc = next(e for e in model.elements.values() if e["type"] == "ApplicationService")
    ac = next(e for e in model.elements.values() if e["type"] == "ApplicationComponent")
    assert any(r["src"] == ac["id"] and r["tgt"] == svc["id"] and r["type"] == "Realization"
               for r in model.relations.values())


def test_a_selection_naming_a_capability_no_match_asked_for_is_still_modelled():
    """Not every selected component answers a matched capability — a run may select infrastructure
    no function named. Dropping it would make the drawing quieter than the design."""
    model = built()
    mappers.apply("component_selection", {"selected": [
        {"capability": "Technology · Observability", "component_id": "cmp-obs",
         "component": "App Insights"}], "tradeoffs": [], "unresolved": []}, model, {})
    assert any(e["name"] == "App Insights" for e in model.elements.values())


def test_the_whole_chain_stays_legal():
    model = built()
    mappers.apply("component_selection", SELECTION, model, {})
    for r in model.relations.values():
        ok, _ = relrepair.check(model.elements[r["src"]]["type"], r["type"],
                                model.elements[r["tgt"]]["type"])
        assert ok, f"{r['src']} -{r['type']}-> {r['tgt']}"
    assert model.dropped == []


def test_a_capability_is_drawn_once_not_as_a_service_and_a_function_of_the_same_name():
    """The service IS the capability. An ApplicationFunction beside it — one box holding the label,
    one the raw key — is the same thing twice, and a reviewer reading the drawing has to work out
    that they are not two parts of the design."""
    model = built()
    mappers.apply("component_selection", SELECTION, model, {})
    assert not [e for e in model.elements.values()
                if e["type"] == "ApplicationFunction"
                and "Agentic retrieval" in e["name"]]


def test_a_free_text_capability_still_gets_an_application_function():
    """The other case, kept: a selection whose `capability` is not a map key had no service made
    for it, and dropping it would lose what the component was selected to do."""
    model = built()
    mappers.apply("component_selection", {"selected": [
        {"capability": "bespoke scoring", "component_id": "cmp-z", "component": "A function app"}],
        "tradeoffs": [], "unresolved": []}, model, {})
    assert [e["name"] for e in model.elements.values()
            if e["type"] == "ApplicationFunction"] == ["bespoke scoring"]


def test_a_selection_naming_a_capability_no_match_offered_is_recorded_not_silently_reshaped():
    """The join's failure is otherwise invisible: the component falls through to an
    ApplicationFunction, attaches to nothing the business asked for, and the package holds two
    disconnected clouds of boxes with no warning anywhere."""
    model = built()
    mappers.apply("component_selection", {"selected": [
        {"capability": "Cognitive · Never matched", "component_id": "cmp-q", "component": "A thing"}],
        "tradeoffs": [], "unresolved": []}, model, {})
    assert any(d.get("capability") == "Cognitive · Never matched" for d in model.dropped)
