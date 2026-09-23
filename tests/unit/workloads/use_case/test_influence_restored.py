"""Influence was structurally always zero, and with it five guardrails.

Audited 23 Sep 2026 and confirmed against a live cloud run (`max_influence: 0`). The domain `Step`
carries `determines`, `determines_externally` and the three input facets; `_STEP_FIELDS` lists
them; only `facet_vectors.schema.json` — `additionalProperties: false` — forbade them. So every
omitted facet defaulted to its lowest-risk value and `influence_of` returned 0 for every step of
every run.

What that cost, traced to the published tables: G18 (influence >= 2), G19 (any step influence >= 3)
and half of G13 could never fire, so the I-class obligations — an evaluation harness with a stated
accuracy target, a recall target on the branch a step can suppress, an independently monitored
outcome assertion — were never mandated by any run. G17 and G21 could never fire either, because
the input facets they read were unaskable. And because components exist to satisfy obligations,
every design was under-costed in the direction that looks safe.

`determines` is DERIVED from step 10's edges rather than asked of step 17. The data-flow graph is
already gated (every edge endpoint is a declared node) and asking a second agent to restate it is
how the two answers drift — which is the same defect as step 15 vs step 17 on determinism.
"""
import json
from pathlib import Path

from lab.core.usecase import exposure
from lab.core.usecase.model import Step, Workflow
from lab.workloads.use_case_design import workflow as design

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((ROOT / "src/lab/workloads/usecase/schemas/facet_vectors.schema.json").read_text())
ITEM = SCHEMA["properties"]["steps"]["items"]


def test_the_schema_admits_every_facet_the_domain_reads():
    """The rule this restores: a facet the domain reads and the schema forbids defaults silently to
    its lowest-risk value, and a control set that is quietly short looks exactly like a full one."""
    declared = set(ITEM["properties"])
    domain = {"sensitivity", "trust", "freshness", "determines_externally"}
    assert domain <= declared, f"the domain reads {sorted(domain - declared)} and cannot be told"


def test_determines_is_derived_from_the_graph_not_asked_of_the_agent():
    """Step 10 already produced the edges and they are already gated. A second agent restating them
    is how two answers drift apart — exactly as step 15 and step 17 drifted on determinism."""
    assert "determines" not in ITEM["properties"], "asking for it invites a second opinion"
    graph = {"nodes": [{"id": "n1"}, {"id": "n2"}, {"id": "n3"}],
             "edges": [{"from": "n1", "to": "n2", "data_class": "internal"},
                       {"from": "n1", "to": "n3", "data_class": "internal"}]}
    assert design.determines_from(graph) == {"n1": ("n2", "n3")}


def test_an_edge_to_an_undeclared_node_is_not_a_determination():
    graph = {"nodes": [{"id": "n1"}], "edges": [{"from": "n1", "to": "ghost"}]}
    assert design.determines_from(graph) == {}


def test_a_payload_carries_the_derived_determines_onto_every_vector():
    state = {"screening": {"workflow_graph": {
        "nodes": [{"id": "n1"}, {"id": "n2"}],
        "edges": [{"from": "n1", "to": "n2", "data_class": "internal"}]},
        },
        "criticality": {"criticality_class": {"value": "business-critical"}}}
    derived = {"facet_vectors": {"steps": [{"id": "n1", "effect": "advisory"},
                                           {"id": "n2", "effect": "record write"}]}}
    payload = design._workflow_payload(state, derived)
    by_id = {s["id"]: s for s in payload["steps"]}
    assert by_id["n1"]["determines"] == ("n2",)
    assert not by_id["n2"].get("determines")


def test_influence_is_no_longer_structurally_zero():
    """The canonical case from the framework's own documentation: an interpretive step whose own
    effect is nothing, but whose output selects the branch that commits. Exposure 0, influence 3 —
    the case that could not be produced at all."""
    wf = Workflow(steps=(
        Step(id="n1", activity="interpret", effect="none", determines=("n2",)),
        Step(id="n2", activity="commit",
             effect="financial or contractual commitment", blast_radius="population")),
        criticality="business-critical")
    assert exposure.influence_of(wf, "n1") >= 2, "an interpretive step still has influence"
    assert exposure.exposure_of(wf["n1"]) == 0, "and its own effect is still nothing"


def test_an_override_naming_an_unknown_facet_is_refused_rather_than_dropped():
    """It was dropped in silence, and the justification stayed in the record — so the package read
    as the opposite of what was derived. A natural spelling ("effect class") is the likely case."""
    assert "enum" in ITEM["properties"]["overrides"]["items"]["properties"]["facet"], \
        "an unconstrained facet name is one the workflow will discard without a word"


def test_a_count_shaped_graph_derives_nothing_rather_than_raising():
    """The screening record sometimes carries the graph as SHAPE — `nodes: 6` — not as a list.
    That is the evidence form, and a derivation that raises on it would kill a design run over a
    summary. Nothing is derived from a count, which is correct: a count names no edges."""
    assert design.determines_from({"nodes": 6, "edges": 5}) == {}
    assert design.determines_from({}) == {}
    assert design.determines_from({"nodes": [{"id": "n1"}], "edges": "none"}) == {}
