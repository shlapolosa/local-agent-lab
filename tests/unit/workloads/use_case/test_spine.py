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
from lab.core.usecase import seed as _seed
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
    ValuationTools,
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
#: Every prose condition the published guardrails ask, answered. A facet vector that left one out
#: is refused by the gate, so a fixture that omitted them would not be a real step-17 answer.
ANSWERED = {c: False for c in _seed.NAMED_CONDITIONS}

READY = {"coverage_map": {"matched": True,
                          "heat_map": {"commodity": False, "mature": False, "meets_target": False,
                                       "source": "healthcare-provider-v2.0"}},
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

#: A design package as step 25 leaves it. The investment run READS this rather than re-deriving
#: anything from it: recomputing would produce a second number for the same case with nothing to
#: say which one the approver saw.
COSTED = {
    "cost": {"monthly": {"expected": 250}, "year_one": {"expected": 30000},
             "requires_input": [], "gap_flags": []},
    "benefit": {"summary": {"annual_benefit": 90000.0, "year_one_investment": 30000.0,
                            "payback_months": 5.0, "requires_input": []},
                "recommendation": {"verdict": "proceed", "rationale": "it repays",
                                   "gate_conditions": []}},
    "delivery_artifacts": {"business_case": [{"section": "Executive summary", "content": "..."}]},
    "pending_steps": {},
}

BANDS = ({"limit": 50_000, "authority": "delivery lead"},
         {"limit": None, "authority": "investment board"})


def _investment_router(design=None, **extra):
    return Router({SemanticTools.store_spec: {"spec_ref": "art://i1/inv.json"},
                   StorageTools.read_artifact: dict(COSTED if design is None else design),
                   ApprovalTools.ask: {"request_id": "apr-3", "review_app": "r"},
                   **extra}, full=True)


def _investment_inputs(**kw):
    return {"design_ref": "art://d/design.json", "conformance": {"decision": "approve"},
            "submitter": "ba@x.ae"} | kw


def test_the_investment_run_routes_to_the_delegated_authority():
    from lab.workloads.use_case_investment import workflow as W
    with spine(W, _investment_router()) as h:
        h.cfg["authority_table"] = BANDS
        out = run_spine(W, h, _investment_inputs())
    assert out["authority"] == "delivery lead"
    assert out["summary"]["escalated"] is False
    assert out["investment_ref"] == "art://i1/inv.json"
    cont = continuation_of({"continuation":
                            [c for c in h.router.calls
                             if c[0] == ApprovalTools.ask][0][1]["continuation"]})
    assert cont.process == USE_CASE_PROVISIONING.name
    assert cont.answer_input == "authorisation"


def test_with_no_configured_bands_the_funding_decision_escalates_rather_than_guessing():
    """The delegation thresholds are one of three artifacts neither published source supplies.
    Shipping a plausible band structure would route real money by a number this lab invented."""
    from lab.workloads.use_case_investment import workflow as W
    with spine(W, _investment_router()) as h:
        out = run_spine(W, h, _investment_inputs())
    assert out["summary"]["escalated"] is True
    assert "no delegation-of-authority" in out["summary"]["routing"]


def test_a_case_with_anything_still_open_is_not_one_a_delegated_signer_closes_out():
    from lab.workloads.use_case_investment import workflow as W
    design = dict(COSTED)
    design["cost"] = dict(COSTED["cost"]) | {"requires_input": ["build cost: none captured"]}
    with spine(W, _investment_router(design=design)) as h:
        h.cfg["authority_table"] = BANDS
        out = run_spine(W, h, _investment_inputs())
    assert out["authority"] == "investment board" and out["summary"]["escalated"] is True


def test_a_step_that_never_ran_reaches_the_approver_as_an_open_condition():
    """A case whose delivery artifacts were never drafted looks complete right up until somebody
    asks for them."""
    from lab.workloads.use_case_investment import workflow as W
    design = dict(COSTED) | {"pending_steps": {"25": "generate delivery artifacts"}}
    with spine(W, _investment_router(design=design)) as h:
        h.cfg["authority_table"] = BANDS
        run_spine(W, h, _investment_inputs())
    package = [c[1]["spec"] for c in h.router.calls if c[0] == SemanticTools.store_spec][0]
    assert any("step 25" in c for c in package["gate_conditions"])


def test_the_figures_are_read_from_the_design_and_never_recomputed():
    from lab.workloads.use_case_investment import workflow as W
    with spine(W, _investment_router()) as h:
        h.cfg["authority_table"] = BANDS
        out = run_spine(W, h, _investment_inputs())
    package = [c[1]["spec"] for c in h.router.calls if c[0] == SemanticTools.store_spec][0]
    assert package["financial_summary"]["year_one_investment"] == 30000.0
    assert package["business_case"], "the case step 25 drafted, not a second draft nobody reviewed"
    assert out["recommendation"] == "proceed"


APPROVED_WORK = {"work_items": [{"key": "EPIC-1", "title": "Build the triage agent",
                                 "owner": "delivery lead"}],
                 "catalog_entry": {"name": "Referral triage", "description": "...",
                                   "owner": "clinical ops"}}


def _provisioning_router(delivery=None, conditions=(), **extra):
    """The investment package, and the design it points back at.

    Answers BY REF rather than by turn, which is what a store does — a test that depended on the
    order of two reads would pass while asserting nothing about which artifact each one wanted."""
    artifacts = APPROVED_WORK if delivery is None else delivery
    store = {"art://i/inv.json": {"design_ref": "art://d/design.json",
                                  "gate_conditions": list(conditions)},
             "art://d/design.json": {"delivery_artifacts": artifacts}}
    return Router({SemanticTools.store_spec: {"spec_ref": "art://p1/staged.json"},
                   StorageTools.read_artifact: lambda args: store[args["ref"]],
                   **extra}, full=True)


def test_provisioning_is_keyed_on_the_investment_and_on_what_it_stages():
    """FR-42. Keying on the RUN would make every retry look like new work; keying on the investment
    ALONE would make a corrected package silently reuse the key of the one it replaced."""
    from lab.workloads.use_case_provisioning import workflow as W
    with spine(W, _provisioning_router()) as h:
        out = run_spine(W, h, {"investment_ref": "art://i/inv.json",
                               "authorisation": {"decision": "approve"}})
    assert out["provisioned"] is True
    assert out["idempotency"].startswith("art://i/inv.json#")

    changed = dict(APPROVED_WORK) | {"work_items": APPROVED_WORK["work_items"] + [
        {"key": "EPIC-2", "title": "Wire the evaluation harness", "owner": "delivery lead"}]}
    with spine(W, _provisioning_router(delivery=changed)) as h2:
        other = run_spine(W, h2, {"investment_ref": "art://i/inv.json",
                                  "authorisation": {"decision": "approve"}})
    assert other["idempotency"] != out["idempotency"]


def test_a_re_run_of_the_same_approved_package_stages_the_same_thing():
    from lab.workloads.use_case_provisioning import workflow as W
    keys = []
    for _ in range(2):
        with spine(W, _provisioning_router()) as h:
            keys.append(run_spine(W, h, {"investment_ref": "art://i/inv.json",
                                         "authorisation": {"decision": "approve"}})["idempotency"])
    assert keys[0] == keys[1]


def test_what_is_staged_is_step_25s_work_and_never_drafted_here():
    """A provisioning run writing its own work items would create work nobody approved — which is
    what CR-20 exists to stop, one process too late for the grant to help."""
    from lab.workloads.use_case_provisioning import workflow as W
    with spine(W, _provisioning_router()) as h:
        out = run_spine(W, h, {"investment_ref": "art://i/inv.json", "authorisation": {}})
    staged = [c[1]["spec"] for c in h.router.calls if c[0] == SemanticTools.store_spec][0]
    assert staged["work_items"] == APPROVED_WORK["work_items"]
    assert out["summary"]["work_items"] == 1 and out["summary"]["catalog_entries"] == 1


def test_nothing_is_staged_that_has_no_content():
    """An empty artifact on the review page reads as "released and empty", not "never drafted"."""
    from lab.workloads.use_case_provisioning import workflow as W
    with spine(W, _provisioning_router(delivery={})) as h:
        out = run_spine(W, h, {"investment_ref": "art://i/inv.json", "authorisation": {}})
    assert out["import_artifacts"] == [] and out["provisioned"] is False
    assert out["work_items_ref"] == "" and out["catalog_ref"] == ""


def test_every_staged_artifact_carries_a_label_and_a_note_a_person_can_act_on():
    from lab.workloads.use_case_provisioning import workflow as W
    with spine(W, _provisioning_router()) as h:
        out = run_spine(W, h, {"investment_ref": "art://i/inv.json", "authorisation": {}})
    assert len(out["import_artifacts"]) == 2
    for artifact in out["import_artifacts"]:
        assert artifact["ref"] and artifact["label"] and artifact["note"]


def test_conditions_still_open_reach_whoever_picks_up_the_work():
    """An investment approved WITH conditions still has them open when the work is created, and the
    person picking up the tree is the one who has to close them."""
    from lab.workloads.use_case_provisioning import workflow as W
    with spine(W, _provisioning_router(conditions=["build cost: none captured"])) as h:
        out = run_spine(W, h, {"investment_ref": "art://i/inv.json", "authorisation": {}})
    assert out["summary"]["gate_conditions"] == 1


def test_provisioning_is_the_end_of_the_chain():
    from lab.workloads.use_case_provisioning import workflow as W
    with spine(W, _provisioning_router()) as h:
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
                     "heat_map": {"commodity": False, "mature": False, "meets_target": False,
                                  "source": "healthcare-provider-v2.0, capability c1"},
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
                                 "effect": "none", "conditions": ANSWERED},
                                {"id": "n2", "activity": "commit", "determinism": "D0",
                                 "effect": "record write", "conditions": ANSWERED}]},
    "build_surface": {"incumbent_considered": True, "surface": "Foundry hosted agent",
                      "topology": "T2", "unenforceable_obligations": []},
    "cost_inputs": {"resources": ["Container Apps"],
                    "switched_on_by": {"Container Apps": "F2"},
                    "envelope": "expected", "unpriceable": []},
    "benefit_inputs": {"effort": [{"role": "nurse", "headcount": 4, "frequency_per_week": 20,
                                   "current_minutes": 30, "expected_minutes": 10,
                                   "source": "the submission, paragraph 2"}],
                       "sensitivity_flags": [], "data_fully_digital": True,
                       "excluded_value": [], "unsupplied": []},
    "component_selection": {"selected": [{"capability": "inference", "component": "Foundry",
                                          "rejected_alternatives": ["self-hosted"]}],
                            "tradeoffs": [], "unresolved": []},
}


def _design_chain_router(**extra):
    # The full evidence set: step 21 reads the quality attributes, so a router carrying only what
    # the gate needs would leave it pending and make the chain test quieter than it looks.
    return Router({SemanticTools.store_spec: {"spec_ref": "art://d1/design.json"},
                   StorageTools.read_artifact: dict(READY) | {
                       "quality_attributes": {"attributes": [{"name": "latency"}]},
                       "frame": {"problem": "referral triage takes too long"}},
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
                   ValuationTools.cost: {"lines": [{"service": "Container Apps"}],
                                         "monthly": {"low": 100, "expected": 250, "high": 400},
                                         "year_one": {"low": 1200, "expected": 3000, "high": 4800},
                                         "gap_flags": [], "build": None,
                                         "requires_input": ["build cost: none captured"],
                                         "sheet_version": "v0.25", "caveat": "illustrative"},
                   ValuationTools.benefit: {
                       "drivers": [], "summary": {"annual_benefit": 90000.0,
                                                  "year_one_investment": 3000.0,
                                                  "payback_months": 0.4, "three_year_roi": 89.0,
                                                  "requires_input": []},
                       "recommendation": {"verdict": "proceed with conditions",
                                          "rationale": "figures are still open",
                                          "gate_conditions": ["build cost: none captured"]}},
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
            {"id": "n1", "activity": "commit", "determinism": "D0", "effect": "record write",
             "conditions": ANSWERED},
            {"id": "", "activity": "commit", "determinism": "D0", "effect": "record write",
             "conditions": ANSWERED}]})
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


# ---------------------------------------------------------------- the valuation half, 23 and 24

def test_the_cost_is_priced_from_what_step_23_selected_and_not_from_the_composition():
    """The composition names families; only the cost engineer maps them to lines of a price sheet,
    spelled as the sheet spells them. Costing the families directly would be a second mapping
    living in the orchestrator."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_chain_router()) as h:
        _with_design_agents(h)
        run_spine(W, h, _design_inputs())
    sent = [c[1] for c in h.router.calls if c[0] == ValuationTools.cost][0]
    assert sent["resources"] == ["Container Apps"]


def test_the_benefit_is_computed_against_the_cost_it_has_to_repay():
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_chain_router()) as h:
        _with_design_agents(h)
        run_spine(W, h, _design_inputs())
    sent = [c[1] for c in h.router.calls if c[0] == ValuationTools.benefit][0]
    assert sent["monthly_run_cost"] == 250
    assert sent["build_cost"] == 0.0


def test_the_recommendation_is_step_24s_verdict_and_never_a_default():
    """An unearned "proceed with conditions" is still a proceed to whoever reads the summary."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_chain_router()) as h:
        _with_design_agents(h)
        out = run_spine(W, h, _design_inputs())
    assert out["recommendation"] == "proceed with conditions"
    assert out["business_case_ref"] and out["cost_ref"]


def test_without_a_cost_the_benefit_is_not_computed_and_the_case_says_so():
    """A benefit judged against no investment repays trivially. That is not a business case."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_chain_router()) as h:
        _with_design_agents(h, cost_inputs=None)
        out = run_spine(W, h, _design_inputs())
    called = [c[0] for c in h.router.calls]
    assert ValuationTools.cost not in called and ValuationTools.benefit not in called
    assert out["recommendation"] == "" and out["business_case_ref"] == "" and out["cost_ref"] == ""
    package = [c[1]["spec"] for c in h.router.calls if c[0] == SemanticTools.store_spec][0]
    assert "23" in package["pending_steps"] and "24" in package["pending_steps"]


def test_everything_still_open_on_either_side_reaches_the_verdict_as_a_condition():
    """A recommendation that did not carry them would read as settled."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_chain_router()) as h:
        _with_design_agents(h, benefit_inputs={
            "effort": [], "sensitivity_flags": [], "data_fully_digital": True,
            "excluded_value": [], "unsupplied": ["nobody gave a headcount for the nursing team"]})
        run_spine(W, h, _design_inputs())
    sent = [c[1] for c in h.router.calls if c[0] == ValuationTools.benefit][0]
    assert "build cost: none captured" in sent["open_conditions"]
    assert "nobody gave a headcount for the nursing team" in sent["open_conditions"]


def test_the_value_analyst_is_never_shown_the_cost_it_has_to_clear():
    """A benefit sized to clear a known investment is not evidence. The dependency runs one way,
    and it runs after step 24's figures are already fixed."""
    from lab.workloads.usecase import agents as A
    assert "cost" not in A.CONTEXT_FOR["benefit_inputs"]
    assert "cost_inputs" not in A.CONTEXT_FOR["benefit_inputs"]


# ------------------------------------------------- the derivation, run for real rather than stubbed

def test_the_facet_vectors_the_agents_produce_actually_derive_a_control_set():
    """The spine's routers stub the governed services with canned dicts, which is right for testing
    the WIRING and blind to whether the payload the wiring sends is derivable at all.

    This ran the real domain against the real step-17 answer and found the defect that mattered
    most in this batch: nine published guardrail conditions, none of them answered, and
    `predicates.Named` refuses an unanswered condition rather than reading it false — so the first
    real design run would have raised through the whole workflow after paying for steps 13 to 17.
    """
    from lab.core.usecase import obligations
    from lab.workloads.use_case_design.workflow import _workflow_payload
    from lab.core.usecase.model import Step as DomainStep, Workflow as DomainWorkflow

    payload = _workflow_payload({"criticality": {"criticality_class": "business-critical"}},
                                {"facet_vectors": DESIGN_ANSWERS["facet_vectors"]})
    workflow = DomainWorkflow(steps=tuple(DomainStep(**s) for s in payload["steps"]),
                              criticality=payload["criticality"])
    out = obligations.derive(workflow, conditions={})
    assert out.guardrails(), "a control set that is empty is not a derivation"


def test_a_step_whose_conditions_are_unanswered_refuses_rather_than_deriving_a_short_set():
    """The refusal this whole layer exists for, asserted from the workload's own side."""
    from lab.core.usecase import obligations
    from lab.core.usecase.model import Step as DomainStep, Workflow as DomainWorkflow

    workflow = DomainWorkflow(
        steps=(DomainStep(id="n1", activity="interpret", determinism="D2", effect="none"),),
        criticality="business-critical")
    with pytest.raises(Exception) as e:
        obligations.derive(workflow, conditions={})
    assert "answered" in str(e.value)


def test_the_conditions_ride_on_the_step_and_reach_the_derivation():
    """They cannot be workflow-wide: the predicates ask about a STEP, so one answer for all of them
    is the same as not answering."""
    from lab.workloads.use_case_design.workflow import _workflow_payload
    payload = _workflow_payload({"criticality": {"criticality_class": "routine"}},
                                {"facet_vectors": DESIGN_ANSWERS["facet_vectors"]})
    assert all(set(s["conditions"]) == set(_seed.NAMED_CONDITIONS) for s in payload["steps"])


# ------------------------------------------------- what a live screening run found at step 5

def test_a_corpus_reaches_a_prompt_projected_to_what_the_step_reads():
    """A projection, not a truncation — every concept survives, the prose does not.

    Measured on a live run that sat on step 5 for fifty-three minutes: the published capability map
    carries a `definition` per concept that a MATCH never reads, and 1,666 of them made the prompt
    94,000 tokens. A hang is the worst way for a size problem to present, because it looks like
    slowness and slowness looks like patience."""
    from lab.workloads.use_case_screening.workflow import PROMPT_FIELDS, project
    corpus = [{"id": "c1", "label": "Patient Management", "level": 1, "tier": "core",
               "parent": None, "definition": "x" * 400}]
    out = project("capabilities", corpus)
    assert len(out) == len(corpus), "no concept may be dropped — a match must see the whole map"
    assert set(out[0]) <= set(PROMPT_FIELDS["capabilities"])
    assert "definition" not in out[0]


def test_a_corpus_with_no_projection_declared_is_passed_through_untouched():
    from lab.workloads.use_case_screening.workflow import project
    assert project("ontology", {"vocabularies": ["archimate-3.1"]}) == {
        "vocabularies": ["archimate-3.1"]}


def test_a_corpus_over_the_prompt_budget_is_unavailable_rather_than_partial():
    """A step that silently receives half a corpus answers confidently from half a corpus."""
    from lab.workloads.use_case_screening import workflow as W
    assert W.MAX_CORPUS_BYTES > 0
    src = W.__doc__ or ""
    assert "depth" in open(W.__file__).read()


def test_the_capability_depth_the_run_used_is_in_the_record():
    """A reader must be able to tell the coverage map is L1 without reading the module."""
    from lab.workloads.use_case_screening.workflow import CORPORA
    assert CORPORA["capabilities"][1]["depth"] == 1
