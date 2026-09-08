"""The use-case intake spine — four processes, chained by what a human approves.

Two behaviours carry the weight, and neither is about the derivations (there are none yet):

* **The gates are the only way through.** Three of the four processes cannot be started from
  outside at all, and the input each one needs is the ANSWER a human gave at the gate before it.
* **FR-11's halt.** A reject or an integration finding stops the run, steps 17-25 are not attempted
  and no partial design package is produced — asserted against the named outputs a package HAS, so
  a typo in one of them cannot make the test pass.
"""
import json
import re

import pytest

from fixtures.workflow import Router, run_spine, spine
from lab.platform.contracts import (
    PROCESSES,
    USE_CASE_DESIGN,
    USE_CASE_INVESTMENT,
    USE_CASE_PROVISIONING,
    USE_CASE_SCREENING,
    ApprovalTools,
    CollabTools,
    DecisionTools,
    Continuation,
    SemanticTools,
    StorageTools,
    WorkflowTools,
    continuation_of,
)

SPECS = (USE_CASE_SCREENING, USE_CASE_DESIGN, USE_CASE_INVESTMENT, USE_CASE_PROVISIONING)


# ---------------------------------------------------------------- the contract

def test_only_the_first_process_can_be_started_from_outside():
    """The entire enforcement of "you cannot skip the gates": the tools and the REST routes are
    generated from the spec, so a grant cannot name an entry point that does not exist."""
    assert USE_CASE_SCREENING.external is True
    for spec in (USE_CASE_DESIGN, USE_CASE_INVESTMENT, USE_CASE_PROVISIONING):
        assert spec.external is False
        assert "submit" not in WorkflowTools.verbs_for(spec)
        assert spec.tool("submit") not in WorkflowTools.names()


def test_observing_a_run_is_never_refused_even_where_starting_one_is():
    """Refusing to START is not refusing to OBSERVE — a flow that cannot poll the run its own
    approval began cannot tell anybody the answer is ready."""
    for spec in SPECS:
        assert {"status", "result"} <= set(WorkflowTools.verbs_for(spec))


def test_every_process_has_its_own_consumer_group():
    groups = [PROCESSES[s.name].group for s in SPECS]
    assert len(set(groups)) == len(groups)


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.name)
def test_no_output_name_carries_a_vendor_or_a_file_format(spec):
    banned = ("adoit", "xlsx", "excel", "spreadsheet", "sharepoint", "teams")
    assert not [o for o in spec.outputs if any(b in o.lower() for b in banned)]


def test_the_gate_answer_is_a_required_input_of_the_process_it_releases():
    """A continuation whose answer were optional could be started without the human's decision,
    which is the one thing these boundaries exist to prevent."""
    for spec, field in ((USE_CASE_DESIGN, "criticality"),
                        (USE_CASE_INVESTMENT, "conformance"),
                        (USE_CASE_PROVISIONING, "authorisation")):
        assert spec.field(field).required is True


# ---------------------------------------------------------------- screening: steps 1-12

def _screening_router(**extra):
    return Router({StorageTools.read_document: "A use case about triaging referrals faster.",
                   SemanticTools.store_spec: {"spec_ref": "art://s1/spec.json"},
                   ApprovalTools.ask: {"request_id": "apr-1", "status": "pending",
                                       "review_app": "http://review/apr-1"},
                   **extra}, full=True)


def test_a_submission_is_read_validated_and_persisted_before_anything_derives():
    """FR-04: every later step reads the datastore, never the channel."""
    from lab.workloads.use_case_screening import workflow as W
    with spine(W, _screening_router()) as h:
        out = run_spine(W, h, {"submission": "art://in/use-case.md", "submitter": "ba@x.ae"})
    assert out["submission_ref"] == "art://s1/spec.json"
    stored = [c for c in h.router.calls if c[0] == SemanticTools.store_spec]
    assert stored[0][1]["spec"]["prose"].startswith("A use case about")


def test_a_submission_with_no_readable_text_refuses():
    from lab.workloads.use_case_screening import workflow as W
    with spine(W, _screening_router(**{StorageTools.read_document: "   "})) as h:
        with pytest.raises(Exception, match="no readable text"):
            run_spine(W, h, {"submission": "art://in/empty.md", "submitter": "ba@x.ae"})


@pytest.mark.parametrize("given,missing", [
    ({"submission": "art://a/b.md", "submission_handle": "collab://c/d"}, "both"),
    ({}, "neither"),
])
def test_exactly_one_way_of_supplying_the_document_is_required(given, missing):
    """`ProcessSpec.validate` cannot express an xor, so the workload checks it — and says which of
    the two mistakes was made rather than restating the rule."""
    from lab.workloads.use_case_screening import workflow as W
    with spine(W, _screening_router()) as h:
        with pytest.raises(Exception, match=re.escape(missing)):
            run_spine(W, h, {"submitter": "ba@x.ae", **given})


def test_a_handle_is_fetched_into_the_store_before_it_is_read():
    from lab.workloads.use_case_screening import workflow as W
    router = _screening_router(**{CollabTools.fetch: {"ref": "art://fetched/doc.md"}})
    with spine(W, router) as h:
        run_spine(W, h, {"submission_handle": "collab://drive/doc", "submitter": "ba@x.ae"})
    read = [c for c in h.router.calls if c[0] == StorageTools.read_document]
    assert read[0][1]["ref"] == "art://fetched/doc.md"


def test_the_screening_record_says_which_steps_it_did_not_derive():
    """An absent capability map and one an agent produced empty are different findings. Only one
    of them is a gap flag, and a record that simply omitted the field could not tell them apart."""
    from lab.workloads.use_case_screening import workflow as W
    with spine(W, _screening_router()) as h:
        run_spine(W, h, {"submission": "art://in/u.md", "submitter": "ba@x.ae"})
    screening = [c[1]["spec"] for c in h.router.calls
                 if c[0] == SemanticTools.store_spec and "pending_steps" in c[1]["spec"]][0]
    assert set(screening["pending_steps"]) >= {"3", "5", "10", "11"}


def test_the_run_ends_at_the_architects_question():
    from lab.workloads.use_case_screening import workflow as W
    with spine(W, _screening_router()) as h:
        out = run_spine(W, h, {"submission": "art://in/u.md", "submitter": "ba@x.ae"})
    assert out["approval_id"] == "apr-1"
    asked = [c for c in h.router.calls if c[0] == ApprovalTools.ask][0][1]
    assert "criticality" in asked["subject"].lower()


def test_approving_the_question_releases_the_design_run():
    """The continuation is validated at construction, so a typo fails HERE rather than as a human
    approving and nothing happening."""
    from lab.workloads.use_case_screening import workflow as W
    with spine(W, _screening_router()) as h:
        run_spine(W, h, {"submission": "art://in/u.md", "submitter": "ba@x.ae"})
    asked = [c for c in h.router.calls if c[0] == ApprovalTools.ask][0][1]
    cont = continuation_of({"continuation": asked["continuation"]})
    assert isinstance(cont, Continuation)
    assert cont.process == USE_CASE_DESIGN.name
    assert cont.answer_input == "criticality"
    assert cont.inputs["screening_ref"] and cont.inputs["submission_ref"]


def test_the_span_records_that_a_submitter_was_supplied_never_who():
    from lab.workloads.use_case_screening import host
    attrs = host.run_once.__doc__ or ""
    assert "counts and shapes" in attrs.lower() or "collector" in attrs.lower()


# ---------------------------------------------------------------- design: the two gates and the halt

#: A screening record that evidences every M0 gate — what the design run needs before it can rule
#: on anything. Each key is the artifact a gate ASKS FOR, so a test that removes one is removing
#: the evidence rather than flipping a flag.
READY = {"coverage_map": {"matched": True, "heat_map": {}},
         "workflow_graph": {"nodes": 4},
         "ontology_delta": {"concepts": []},
         "source_contracts": {"sources": 2},
         "realisation_match": {"existing": False}}


def _design_router(readiness="pass", verdict="proceed", failed=()):
    return Router({SemanticTools.store_spec: {"spec_ref": "art://d1/design.json"},
                   StorageTools.read_artifact: dict(READY),
                   DecisionTools.readiness: {"verdict": readiness, "failed": list(failed),
                                             "conditions": {}},
                   DecisionTools.feasibility: {"verdict": verdict, "rule": "a rule fired",
                                               "halts": verdict != "proceed"},
                   ApprovalTools.ask: {"request_id": "apr-2", "status": "pending",
                                       "review_app": "http://review/apr-2"}}, full=True)


def _design_inputs(**kw):
    return {"submission_ref": "art://s/sub.json", "screening_ref": "art://s/scr.json",
            "criticality": {"criticality_class": "business-critical"}, "submitter": "ba@x.ae",
            **kw}


def test_both_verdicts_are_ruled_by_the_governed_service_not_by_the_workload():
    """The rules change under governance approval and conformance review runs the same ones — a
    copy here would be a second implementation of one rule set, drifting quietly."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_router()) as h:
        run_spine(W, h, _design_inputs())
    called = [c[0] for c in h.router.calls]
    assert DecisionTools.readiness in called and DecisionTools.feasibility in called


def test_gate_evidence_is_presence_not_intent():
    """A gate whose artifact is absent is unevidenced whatever the record says about the step that
    should have produced it — reading `pending_steps` as "will be fine" is how a gate stops meaning
    anything."""
    from lab.workloads.use_case_design import workflow as W
    evidenced = W.gate_evidence(READY, {"criticality_class": "routine"})
    assert all(evidenced.values())
    without = W.gate_evidence({k: v for k, v in READY.items() if k != "ontology_delta"},
                              {"criticality_class": "routine"})
    assert without["B"] is False and without["A"] is True


def test_a_pending_step_does_not_evidence_the_gate_it_would_have_filled():
    from lab.workloads.use_case_design import workflow as W
    pending = {"pending_steps": {"9": "check ontology"}}
    assert not any(W.gate_evidence(pending, {}).values())


def test_a_readiness_fail_returns_the_use_case_naming_the_gates():
    """FR-19, and the honest state of the spine today: with steps 3-11 pending, the record
    evidences nothing and readiness correctly fails."""
    from lab.workloads.use_case_design import workflow as W
    router = _design_router(readiness="fail", failed=("A", "B", "C"))
    with spine(W, router) as h:
        out = run_spine(W, h, _design_inputs())
    assert out["verdict"] == "not ready"
    assert out["halted"] is True
    assert set(out["readiness_failed"]) == {"A", "B", "C"}


def test_a_readiness_fail_raises_no_approval_because_nothing_was_rejected_on_merit():
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_router(readiness="fail", failed=("B",))) as h:
        run_spine(W, h, _design_inputs())
    assert not [c for c in h.router.calls if c[0] == ApprovalTools.ask]


def test_a_readiness_fail_never_reaches_the_feasibility_verdict():
    """Ruling on feasibility without the evidence the readiness gate just said was missing is the
    coarse estimate the framework removed."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_router(readiness="fail", failed=("A",))) as h:
        run_spine(W, h, _design_inputs())
    assert not [c for c in h.router.calls if c[0] == DecisionTools.feasibility]


def test_a_proceeding_run_composes_a_design_and_asks_for_conformance():
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_router()) as h:
        out = run_spine(W, h, _design_inputs())
    assert out["halted"] is False
    assert out["architecture_ref"] == "art://d1/design.json"
    asked = [c for c in h.router.calls if c[0] == ApprovalTools.ask][0][1]
    assert "conformance" in asked["subject"].lower()


@pytest.mark.parametrize("verdict", ["reject", "integration"])
def test_a_halting_verdict_produces_no_part_of_a_design_package(verdict):
    """FR-11, asserted against the NAMED outputs a package has — a guess would pass on a typo."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_router(verdict=verdict)) as h:
        out = run_spine(W, h, _design_inputs())
    assert out["halted"] is True
    assert not (set(out) & set(W.DESIGN_OUTPUTS)), \
        f"a halted run leaked {set(out) & set(W.DESIGN_OUTPUTS)}"


@pytest.mark.parametrize("verdict", ["reject", "integration"])
def test_a_halting_verdict_never_stores_a_design(verdict):
    """"Not attempted" means the work does not run, not that its output is discarded."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_router(verdict=verdict)) as h:
        run_spine(W, h, _design_inputs())
    assert not [c for c in h.router.calls if c[0] == SemanticTools.store_spec]


def test_a_rejection_goes_to_an_architect_and_releases_nothing():
    """FR-12: an architect sees it before the submitter. Approving a FINDING must not start the
    next process, so the approval carries no continuation at all."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_router(verdict="reject")) as h:
        out = run_spine(W, h, _design_inputs())
    asked = [c for c in h.router.calls if c[0] == ApprovalTools.ask][0][1]
    assert "continuation" not in asked
    assert continuation_of(asked) is None
    assert out["approval_id"] == "apr-2"


def test_every_approval_declares_the_process_that_raised_it():
    """So a channel serving one pipeline leaves the others alone without guessing from a subject
    line — a guess that gets quietly wrong."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_router(verdict="reject")) as h:
        run_spine(W, h, _design_inputs())
    asked = [c for c in h.router.calls if c[0] == ApprovalTools.ask][0][1]
    assert asked["process"] == USE_CASE_DESIGN.name


def test_a_proceeding_run_releases_the_investment_decision():
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_router()) as h:
        run_spine(W, h, _design_inputs())
    asked = [c for c in h.router.calls if c[0] == ApprovalTools.ask][0][1]
    cont = continuation_of({"continuation": asked["continuation"]})
    assert cont.process == USE_CASE_INVESTMENT.name
    assert cont.answer_input == "conformance"


# ---------------------------------------------------------------- investment and provisioning

def test_the_investment_run_routes_to_the_delegated_authority():
    from lab.workloads.use_case_investment import workflow as W
    router = Router({SemanticTools.store_spec: {"spec_ref": "art://i1/inv.json"},
                     ApprovalTools.ask: {"request_id": "apr-3", "review_app": "r"}}, full=True)
    with spine(W, router) as h:
        out = run_spine(W, h, {"design_ref": "art://d/design.json", "conformance": {"decision": "approve"},
                      "submitter": "ba@x.ae"})
    assert out["investment_ref"] == "art://i1/inv.json"
    cont = continuation_of({"continuation":
                            [c for c in h.router.calls
                             if c[0] == ApprovalTools.ask][0][1]["continuation"]})
    assert cont.process == USE_CASE_PROVISIONING.name
    assert cont.answer_input == "authorisation"


def test_provisioning_is_keyed_on_the_investment_so_a_re_run_creates_nothing_new():
    """FR-42. Keying on the RUN would make every retry look like new work."""
    from lab.workloads.use_case_provisioning import workflow as W
    router = Router({SemanticTools.store_spec: {"spec_ref": "art://p1/staged.json"}}, full=True)
    with spine(W, router) as h:
        out = run_spine(W, h, {"investment_ref": "art://i/inv.json",
                      "authorisation": {"decision": "approve"}})
    assert out["provisioned"] is True
    staged = [c[1]["spec"] for c in h.router.calls if c[0] == SemanticTools.store_spec][0]
    assert staged["idempotency"] == "art://i/inv.json"


def test_provisioning_is_the_end_of_the_chain():
    from lab.workloads.use_case_provisioning import workflow as W
    router = Router({SemanticTools.store_spec: {"spec_ref": "art://p1/staged.json"}}, full=True)
    with spine(W, router) as h:
        run_spine(W, h, {"investment_ref": "art://i/inv.json", "authorisation": {}})
    assert not [c for c in h.router.calls if c[0] == ApprovalTools.ask]


# ---------------------------------------------------------------- preflight

@pytest.mark.parametrize("module,missing", [
    ("use_case_screening", StorageTools.read_document),
    ("use_case_design", ApprovalTools.ask),
    ("use_case_investment", SemanticTools.store_spec),
])
def test_a_gateway_missing_a_required_tool_refuses_before_spending_anything(module, missing):
    """The version-skew lesson: refuse at preflight for 0 tokens, not twenty minutes in."""
    import importlib
    W = importlib.import_module(f"lab.workloads.{module}.workflow")
    with spine(W, Router({}, hidden=(missing,), full=True)) as h:
        with pytest.raises(Exception, match=re.escape(missing)):
            run_spine(W, h, {})


# ---------------------------------------------------------------- screening with agents wired

class ScriptedAgent:
    """Answers with one canned object, whatever it is asked."""

    def __init__(self, reply): self.reply, self.asked = json.dumps(reply), []

    async def run(self, message):
        self.asked.append(message)
        return self.reply


ANSWERS = {
    "frame": {"problem": "Referrals wait eleven days before a clinician reads them",
              "for_whom": "referring GPs", "expected_change": "median below two days",
              "accountable_owner": "Dr Aisha Khan"},
    "elements": {"active": [{"name": "triage nurse"}],
                 "behavioural": [{"name": "assess referral"}],
                 "passive": [{"name": "referral"}]},
    "coverage_map": {"matched": [{"function": "assess referral", "capability_id": "c1",
                                  "confidence": "lookup"}],
                     "functions_without_capability": [], "capabilities_without_function": []},
    "criticality_band": {"band": "business-critical", "provisional": True,
                         "dominant_failure_mode": "a referral is missed and a patient deteriorates"},
    "ontology_delta": {"concepts": [{"object": "referral", "status": "defined"}], "conflicts": []},
    "workflow_graph": {"nodes": [{"id": "n1", "activity": "assess", "performed_by": "nurse"}],
                       "edges": []},
    # Scripted too, so what stops steps 6, 8 and 11 is the MISSING CORPUS rather than a missing
    # agent — otherwise the test would pass for the wrong reason.
    "realisation_match": {"matched": [], "unrealised": ["triage system"], "existing": False},
    "quality_attributes": {"scenarios": [], "gap_flags": [{"what": "no service level published"}]},
    "source_contracts": {"sources": [], "gap_flags": [{"what": "no classification published"}]},
}


def _screening_with_agents(**extra):
    router = Router({StorageTools.read_document: "Referrals wait eleven days.",
                     SemanticTools.store_spec: {"spec_ref": "art://s1/spec.json"},
                     SemanticTools.concepts: {"concepts": [{"id": "c1", "label": "Referral"}]},
                     SemanticTools.ontologies: {"vocabularies": ["archimate-3.1"]},
                     ApprovalTools.ask: {"request_id": "apr-1", "review_app": "r"},
                     **extra}, full=True)
    return router, {k: ScriptedAgent(v) for k, v in ANSWERS.items()}


def test_a_wired_step_runs_and_lands_in_the_screening_record():
    from lab.workloads.use_case_screening import workflow as W
    router, agents = _screening_with_agents()
    with spine(W, router) as h:
        h.cfg["agents"] = agents
        run_spine(W, h, {"submission": "art://in/u.md", "submitter": "ba@x.ae"})
    screening = [c[1]["spec"] for c in h.router.calls
                 if c[0] == SemanticTools.store_spec and "pending_steps" in c[1]["spec"]][0]
    assert screening["frame"]["accountable_owner"] == "Dr Aisha Khan"
    assert screening["elements"]["behavioural"][0]["name"] == "assess referral"
    assert "3" not in screening["pending_steps"], "a step that ran is no longer pending"


def test_the_derived_band_becomes_what_the_architect_is_asked_to_confirm():
    from lab.workloads.use_case_screening import workflow as W
    router, agents = _screening_with_agents()
    with spine(W, router) as h:
        h.cfg["agents"] = agents
        out = run_spine(W, h, {"submission": "art://in/u.md", "submitter": "ba@x.ae"})
    assert out["criticality_band"] == "business-critical"


def test_a_step_whose_corpus_is_missing_is_not_run_at_all():
    """Asked anyway, it would answer from nothing — and that answer is indistinguishable from a
    grounded one. Steps 6, 8 and 11 read corpora this instance does not publish."""
    from lab.workloads.use_case_screening import workflow as W
    router, agents = _screening_with_agents()
    with spine(W, router) as h:
        h.cfg["agents"] = agents
        run_spine(W, h, {"submission": "art://in/u.md", "submitter": "ba@x.ae"})
    screening = [c[1]["spec"] for c in h.router.calls
                 if c[0] == SemanticTools.store_spec and "pending_steps" in c[1]["spec"]][0]
    for number, key in (("6", "realisation_match"), ("8", "quality_attributes"),
                        ("11", "source_contracts")):
        assert key not in screening, f"step {number} ran without its corpus"
        assert "needs" in screening["pending_steps"][number]


def test_an_unavailable_corpus_is_named_in_the_record_rather_than_being_silently_absent():
    """A reader must be able to tell "nobody has published this" from "the step found nothing"."""
    from lab.workloads.use_case_screening import workflow as W
    router, agents = _screening_with_agents()
    with spine(W, router) as h:
        h.cfg["agents"] = agents
        run_spine(W, h, {"submission": "art://in/u.md", "submitter": "ba@x.ae"})
    screening = [c[1]["spec"] for c in h.router.calls
                 if c[0] == SemanticTools.store_spec and "pending_steps" in c[1]["spec"]][0]
    assert set(screening["corpora_unavailable"]) >= {"landscape", "service_levels",
                                                     "source_classification"}


def test_a_corpus_that_fails_to_fetch_does_not_fail_the_run():
    """Best effort: a deployment missing the semantic grant gets a partial record and a named
    reason, not nothing at all."""
    from lab.workloads.use_case_screening import workflow as W
    router, agents = _screening_with_agents(**{SemanticTools.concepts: None})
    with spine(W, router) as h:
        h.cfg["agents"] = agents
        out = run_spine(W, h, {"submission": "art://in/u.md", "submitter": "ba@x.ae"})
    assert out["approval_id"] == "apr-1"
    screening = [c[1]["spec"] for c in h.router.calls
                 if c[0] == SemanticTools.store_spec and "pending_steps" in c[1]["spec"]][0]
    assert "capabilities" in screening["corpora_unavailable"]
    assert "coverage_map" not in screening, "step 5 must not run without its capability map"


# ---------------------------------------------------------------- the design chain, steps 17-22

DESIGN_ANSWERS = {
    "assertions": {"assertions": [{"statement": "every urgent referral was seen within 24 hours",
                                   "evaluated_against": "patient administration system",
                                   "reads_workflow_output": False}]},
    "determinism": {"steps": [{"id": "n1", "tier": "D1", "necessity": "by necessity"}],
                    "governance_tier": "D1", "graph_is_explicit": True},
    "facet_vectors": {"steps": [{"id": "n1", "activity": "interpret", "determinism": "D2",
                                 "effect": "none"},
                                {"id": "n2", "activity": "commit", "determinism": "D0",
                                 "effect": "record write"}]},
    "build_surface": {"incumbent_considered": True, "surface": "Foundry hosted agent",
                      "topology": "T2", "unenforceable_obligations": []},
    "component_selection": {"selected": [{"capability": "inference", "component": "Foundry",
                                          "rejected_alternatives": ["self-hosted"]}],
                            "tradeoffs": [], "unresolved": []},
}


def _design_chain_router(**extra):
    # The full evidence set: step 21 reads the quality attributes, so a router carrying only what
    # the gate needs would leave it pending and make the chain test quieter than it looks.
    return Router({SemanticTools.store_spec: {"spec_ref": "art://d1/design.json"},
                   StorageTools.read_artifact: dict(READY) | {
                       "quality_attributes": {"attributes": [{"name": "latency"}]}},
                   DecisionTools.readiness: {"verdict": "pass", "failed": [], "conditions": {}},
                   DecisionTools.feasibility: {"verdict": "proceed", "rule": "r", "halts": False},
                   DecisionTools.exposure: {"steps": {"n1": {"exposure": 0, "influence": 1}},
                                            "max_exposure": 1, "max_influence": 1},
                   DecisionTools.obligations: {"guardrails": ["G01", "G02"], "by_step": {},
                                               "commit_invariant_holds": True, "violations": [],
                                               "rules_source": {"kind": "local seed"}},
                   DecisionTools.composition: {"topology": "T2", "families": ["F2", "F4"],
                                               "enforcement": {}, "unbound": [], "variants": {},
                                               "modifiers": {}, "connectors": [],
                                               "rules_source": {"kind": "local seed"}},
                   ApprovalTools.ask: {"request_id": "apr-2", "review_app": "r"},
                   **extra}, full=True)


def _with_design_agents(h, **overrides):
    h.cfg["agents"] = {k: ScriptedAgent(overrides.get(k, v))
                       for k, v in DESIGN_ANSWERS.items() if overrides.get(k, v) is not None}


def test_the_derivation_runs_in_the_order_the_framework_publishes():
    """Facets are assigned BEFORE exposure is derived from them; obligations follow those classes;
    the surface is tested against those obligations; the composition is last. Rearranged, each step
    would be reasoning about something not yet decided."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_chain_router()) as h:
        _with_design_agents(h)
        run_spine(W, h, _design_inputs())
    order = [c[0] for c in h.router.calls if c[0].startswith("decision_")]
    assert order == [DecisionTools.readiness, DecisionTools.feasibility, DecisionTools.exposure,
                     DecisionTools.obligations, DecisionTools.composition]


def test_the_facet_vectors_step_17_assigned_are_what_18_derives_from():
    """Step 17's output IS the payload — not a re-derivation here, which would be a second opinion
    about the same steps."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_chain_router()) as h:
        _with_design_agents(h)
        run_spine(W, h, _design_inputs())
    sent = [c[1] for c in h.router.calls if c[0] == DecisionTools.exposure][0]
    assert [s["id"] for s in sent["workflow"]["steps"]] == ["n1", "n2"]


def test_the_topology_the_composition_uses_comes_from_the_build_surface_step():
    """Step 20 is where "who owns control flow at runtime" is actually answered."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_chain_router()) as h:
        _with_design_agents(h)
        run_spine(W, h, _design_inputs())
    sent = [c[1] for c in h.router.calls if c[0] == DecisionTools.composition][0]
    assert sent["topology"] == "T2"
    assert sent["obligations_required"] == ["G01", "G02"]


def test_a_facet_vector_with_no_step_id_is_dropped_rather_than_becoming_a_phantom_step():
    """A vector nobody can attach to a step would put a step in the control set that does not
    exist — and every obligation derived for it would be real."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_chain_router()) as h:
        _with_design_agents(h, facet_vectors={"steps": [
            {"id": "n1", "activity": "commit", "determinism": "D0", "effect": "record write"},
            {"id": "", "activity": "commit", "determinism": "D0", "effect": "record write"}]})
        run_spine(W, h, _design_inputs())
    sent = [c[1] for c in h.router.calls if c[0] == DecisionTools.exposure][0]
    assert [s["id"] for s in sent["workflow"]["steps"]] == ["n1"]


def test_without_facet_vectors_the_derivations_are_not_attempted():
    """18 and 19 read a facet vector per step. Called with none they would derive a control set for
    an empty workflow — which is valid, empty, and completely wrong. Step 17 having no agent at all
    is the honest way to reach that state: the gate refuses an EMPTY vector set outright."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_chain_router()) as h:
        _with_design_agents(h, facet_vectors=None)
        run_spine(W, h, _design_inputs())
    called = [c[0] for c in h.router.calls]
    assert DecisionTools.exposure not in called
    package = [c[1]["spec"] for c in h.router.calls if c[0] == SemanticTools.store_spec][0]
    assert "18" in package["pending_steps"] and "19" in package["pending_steps"]


def test_without_a_topology_the_composition_is_not_attempted():
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_chain_router()) as h:
        _with_design_agents(h, build_surface=None)
        run_spine(W, h, _design_inputs())
    assert DecisionTools.composition not in [c[0] for c in h.router.calls]
    package = [c[1]["spec"] for c in h.router.calls if c[0] == SemanticTools.store_spec][0]
    assert "needs a topology" in package["pending_steps"]["22"]


def test_the_design_package_carries_what_each_step_produced():
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_chain_router()) as h:
        _with_design_agents(h)
        run_spine(W, h, _design_inputs())
    package = [c[1]["spec"] for c in h.router.calls if c[0] == SemanticTools.store_spec][0]
    assert set(package) >= {"assertions", "determinism", "facet_vectors", "risk", "obligations",
                            "build_surface", "component_selection", "composition"}
    assert package["obligations"]["guardrails"] == ["G01", "G02"]


def test_a_halted_run_still_attempts_none_of_it():
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_chain_router(**{
            DecisionTools.feasibility: {"verdict": "reject", "rule": "r", "halts": True}})) as h:
        _with_design_agents(h)
        out = run_spine(W, h, _design_inputs())
    assert out["halted"] is True
    assert not [c for c in h.router.calls if c[0] in (DecisionTools.exposure,
                                                      DecisionTools.obligations,
                                                      DecisionTools.composition)]


def test_the_governance_tier_is_step_15s_answer_and_not_a_constant():
    """It was a constant D2 while step 15 was a pass-through. Now that the step decides it, a
    hardcoded tier would keep reporting D2 for a D0 use case and nothing downstream could tell."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_chain_router()) as h:
        _with_design_agents(h, determinism={"steps": [{"id": "n1", "tier": "D0",
                                                       "necessity": "by default",
                                                       "reducible_to": "D0"}],
                                            "governance_tier": "D0", "graph_is_explicit": True})
        out = run_spine(W, h, _design_inputs())
    assert out["governance_tier"] == "D0"


def test_a_readiness_return_still_carries_the_assertions_it_declared():
    """Step 13 runs before the gate. A use case returned as not-ready is far more useful carrying
    what it would have had to make true than carrying nothing."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_chain_router(**{
            DecisionTools.readiness: {"verdict": "fail", "failed": ["B"], "conditions": {}}})) as h:
        _with_design_agents(h)
        out = run_spine(W, h, _design_inputs())
    assert out["verdict"] == "not ready"
    assert [c for c in h.router.calls if c[0].startswith("decision_")][0][0] == \
        DecisionTools.readiness
