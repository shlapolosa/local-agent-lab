"""Move 5 — every obligation bound to a component this design actually selected.

The four moves before it were already implemented; this one was described in `composition.py`'s
docstring and never written. `Composition.unbound` names an obligation no present FAMILY carries,
which is move 3 under move 5's name — a family is a shape, not a thing anyone can point at in a
deployment. M4 states the real test: "selection is not complete until every obligation resolves to
a named enforcement point on a selected component or on a declared boundary interface … or is
explicitly labelled advisory."
"""
import pytest

from lab.core.usecase import enforcement

GUARDRAILS = [
    {"id": "G02", "cap": "Cognitive · Tool surface / MCP registry", "rule": "tools are registered"},
    {"id": "G09", "cap": "Application · Approval action", "rule": "a human confirms"},
    {"id": "G24", "cap": "Technology · Rate limiting", "rule": "blast radius is bounded"},
    {"id": "G99", "cap": "Nowhere · Missing", "rule": "cannot be bound by this corpus"},
]
MAP = [
    {"domain": "Cognitive", "capability": "Tool surface / MCP registry", "components": ["cmp-reg"]},
    {"domain": "Application", "capability": "Approval action", "components": ["cmp-appr", "cmp-pa"]},
    {"domain": "Technology", "capability": "Rate limiting", "components": ["cmp-apim"]},
]


def bind(obligations, selected, **kw):
    return enforcement.bind(obligations, candidates=enforcement.candidates(GUARDRAILS, MAP),
                            selected=selected, **kw)


def test_candidates_follows_the_two_published_hops_to_the_components():
    assert enforcement.candidates(GUARDRAILS, MAP) == {
        "G02": ("cmp-reg",), "G09": ("cmp-appr", "cmp-pa"), "G24": ("cmp-apim",), "G99": ()}


def test_an_obligation_binds_to_the_selected_component_that_enforces_it():
    out = bind(["G02"], ["cmp-reg", "cmp-unrelated"])
    assert out.bound == {"G02": ("cmp-reg",)}
    assert out.unbound == () and out.unenforceable == ()


def test_only_the_components_this_design_selected_can_bind_it():
    """The capability names two components; the design took one. Binding to the other would claim
    an enforcement point that will not exist in the deployment."""
    assert bind(["G09"], ["cmp-pa"]).bound == {"G09": ("cmp-pa",)}


def test_an_obligation_whose_enforcing_component_was_not_selected_is_unbound():
    out = bind(["G24"], ["cmp-reg"])
    assert out.unbound == ("G24",) and out.bound == {}


def test_a_corpus_that_cannot_bind_it_at_all_is_reported_separately_from_a_design_that_did_not():
    """The two have different owners and different fixes. `unbound` is the designer's — select the
    component. `unenforceable` is the corpus's — the guardrail names a capability the map does not
    carry, or one that reaches no component, and no selection can repair that. Failing a design for
    the second would charge an architect for a gap in the framework."""
    out = bind(["G99", "G24"], ["cmp-reg"])
    assert out.unenforceable == ("G99",), "a corpus gap is not the design's fault"
    assert out.unbound == ("G24",), "and must not hide one that is"


def test_an_obligation_named_advisory_is_neither_bound_nor_a_failure():
    """M4 allows it explicitly, and the word is 'explicitly' — it must be named by the caller, never
    inferred from the fact that nothing bound it."""
    out = bind(["G24"], ["cmp-reg"], advisory=["G24"])
    assert out.advisory == ("G24",) and out.unbound == ()


def test_advisory_cannot_launder_an_obligation_the_corpus_cannot_bind():
    """Calling a corpus gap advisory would hide the defect in the artifact that must be fixed."""
    out = bind(["G99"], [], advisory=["G99"])
    assert out.unenforceable == ("G99",) and out.advisory == ()


def test_one_component_may_carry_several_obligations_and_one_obligation_several_components():
    out = bind(["G02", "G09"], ["cmp-reg", "cmp-appr", "cmp-pa"])
    assert out.bound == {"G02": ("cmp-reg",), "G09": ("cmp-appr", "cmp-pa")}


def test_an_obligation_no_guardrail_declares_is_unenforceable_not_silently_dropped():
    """The mapping states some obligations in prose with no guardrail id. They cannot be bound, and
    a dropped one is an obligation nobody is told went unmet."""
    assert bind(["corroborated grounding"], ["cmp-reg"]).unenforceable == ("corroborated grounding",)


def test_the_result_is_ordered_so_two_runs_of_one_design_read_identically():
    a = bind(["G09", "G02"], ["cmp-pa", "cmp-appr", "cmp-reg"])
    b = bind(["G02", "G09"], ["cmp-reg", "cmp-pa", "cmp-appr"])
    assert a == b


def test_no_obligations_is_a_complete_binding_not_an_empty_one():
    out = bind([], ["cmp-reg"])
    assert out.complete and out.bound == {} and out.unbound == ()


def test_complete_is_false_while_anything_is_unbound_or_unenforceable():
    assert not bind(["G24"], []).complete
    assert not bind(["G99"], []).complete
    assert bind(["G24"], [], advisory=["G24"]).complete


@pytest.mark.parametrize("missing", ["guardrails", "capability_map"])
def test_a_missing_corpus_refuses_rather_than_offering_no_candidates(missing):
    """No candidates looks exactly like a design that selected nothing, and the corpora are read
    under a pin — an absent one is a plumbing failure, not evidence about the design."""
    kwargs = {"guardrails": GUARDRAILS, "capability_map": MAP} | {missing: None}
    with pytest.raises(enforcement.EnforcementError):
        enforcement.candidates(**kwargs)


def test_binding_against_no_candidate_map_refuses_for_the_same_reason():
    with pytest.raises(enforcement.EnforcementError):
        enforcement.bind(["G02"], candidates=None, selected=["cmp-reg"])
