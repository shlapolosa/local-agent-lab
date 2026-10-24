"""What the live view shows for a row that RELATES two things.

Measured on wfr-886957c31872 (29 Sep 2026): step 5's 42 matches were 42 distinct (function,
capability) pairs, but each row showed only the capability label — so "Custom agent hosting"
appeared four times with nothing to tell the rows apart, and read as duplicated output. Step 6's
shortlist showed bare L3 ids — "COG.02" three times — hiding the route and the product that made
each row different. A row that pairs two things names both.
"""
from lab.workloads.usecase.derivation import outline


def _rows(out, key):
    return outline(out)[key]["items"]


def test_a_match_names_its_function_AND_its_capability_and_status():
    out = {"matched": [{"function": "review packet", "capability_id": "COG.02",
                        "capability_label": "Custom agent hosting", "status": "new"},
                       {"function": "apply criteria", "capability_id": "COG.02",
                        "capability_label": "Custom agent hosting", "status": "new"}]}
    rows = _rows(out, "matched")
    assert rows == ["review packet → Custom agent hosting · new",
                    "apply criteria → Custom agent hosting · new"]
    assert len(set(rows)) == 2, "two different matches never render as the same line"


def test_a_shortlisted_realisation_names_its_capability_route_and_product():
    out = {"shortlist": [{"capability_id": "COG.02", "route": "microsoft",
                          "realisation": "Foundry Agent Service", "preferred": True},
                         {"capability_id": "COG.02", "route": "sovereign",
                          "realisation": "Core42 Compass"}]}
    assert _rows(out, "shortlist") == ["COG.02 · microsoft: Foundry Agent Service (preferred)",
                                       "COG.02 · sovereign: Core42 Compass"]


def test_a_row_naming_ONE_thing_is_unchanged():
    assert _rows({"x": [{"name": "Clinical reviewer"}]}, "x") == ["Clinical reviewer"]


# --------------------------------------------- a LIST inside a value names its members, not one
# Measured on the design run of wfr-20f3fa676a9c (29 Sep 2026): a nested list rendered as
# "N × <first>", which read as N copies and hid every member after the first. Step 22's
# `F1: 2 × G06` was a family bound to two DIFFERENT guardrails, a connector `2 × n1` was the edge
# n1 → n2 with its target lost, and `versions: 11 × ai-capability-map` was eleven different
# artifacts. The "×" is gone: it is a multiplication sign, and nothing here was multiplied.

def test_a_family_bound_to_two_guardrails_names_both():
    out = {"enforcement": {"F1": ["G06", "G12"], "F11": ["G20"]}}
    assert _rows(out, "enforcement") == ["F1: G06, G12", "F11: G20"]


def test_a_connector_names_both_ends():
    assert _rows({"connectors": [{"from": "n1", "to": "n2"}, {"from": "n7", "to": "n12"}]},
                 "connectors") == ["n1 → n2", "n7 → n12"]


def test_pinned_versions_name_every_artifact_and_its_version():
    out = {"rules_source": {"versions": [
        {"artifact_id": "ai-capability-map", "version": "v0.30", "retrieval": "key"},
        {"artifact_id": "guardrails", "version": "v0.30", "retrieval": "whole"}]}}
    [line] = _rows(out, "rules_source")
    assert line == "versions: ai-capability-map v0.30, guardrails v0.30"


def test_a_long_nested_list_shows_a_few_and_counts_the_rest():
    obligations = [{"guardrail": f"G{i:02}", "text": f"control {i}", "source": "baseline"}
                   for i in range(1, 20)]
    [line] = _rows({"by_step": {"n1": obligations}}, "by_step")
    assert line == "n1: G01, G02, G03, G04, G05, G06 +13 more"


# ----------------------------------------------------- a workflow step says what it DOES
# Steps 10, 15 and 17 rendered `n1 ;; n2 ;; … n13`: the ids join the graph, the activity is what a
# person reads. Step 15's tier is the decision that step makes, so it is the one thing to show.

def test_a_workflow_node_names_its_activity():
    out = {"nodes": [{"id": "n1", "activity": "Receive the request", "performed_by": "Intake"}]}
    assert _rows(out, "nodes") == ["n1 · Receive the request"]


def test_a_determinism_decision_names_its_tier_and_why():
    out = {"steps": [{"id": "n1", "tier": "D1", "criteria": [1, 3], "necessity": "by necessity"}]}
    assert _rows(out, "steps") == ["n1 · D1 (by necessity)"]


def test_a_number_or_flag_keeps_its_name():
    """Step 18 rendered `n1: 2 · 2` — two numbers and no way to tell which is exposure."""
    out = {"steps": {"n1": {"exposure": 2, "influence": 0}}}
    assert _rows(out, "steps") == ["n1: exposure 2 · influence 0"]


def test_an_edge_keeps_the_data_class_that_drives_its_obligations():
    out = {"edges": [{"from": "n1", "to": "n2", "data_class": "PHI"}]}
    assert _rows(out, "edges") == ["n1 → n2 · PHI"]


def test_a_facet_override_keeps_the_facet_it_overrides():
    out = {"overrides": [{"facet": "effect", "from": "low", "to": "high", "justification": "…"}]}
    assert _rows(out, "overrides") == ["effect: low → high"]
