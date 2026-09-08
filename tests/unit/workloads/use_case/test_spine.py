"""The use-case intake spine — four processes, chained by what a human approves.

Two behaviours carry the weight, and neither is about the derivations (there are none yet):

* **The gates are the only way through.** Three of the four processes cannot be started from
  outside at all, and the input each one needs is the ANSWER a human gave at the gate before it.
* **FR-11's halt.** A reject or an integration finding stops the run, steps 17-25 are not attempted
  and no partial design package is produced — asserted against the named outputs a package HAS, so
  a typo in one of them cannot make the test pass.
"""
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


# ---------------------------------------------------------------- design: the FR-11 halt

def _design_router():
    return Router({SemanticTools.store_spec: {"spec_ref": "art://d1/design.json"},
                   ApprovalTools.ask: {"request_id": "apr-2", "status": "pending",
                                       "review_app": "http://review/apr-2"}}, full=True)


def _design_inputs(**kw):
    return {"submission_ref": "art://s/sub.json", "screening_ref": "art://s/scr.json",
            "criticality": {"criticality_class": "business-critical"}, "submitter": "ba@x.ae",
            **kw}


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
    with spine(W, _design_router()) as h:
        out = run_spine(W, h, _design_inputs(verdict=verdict))
    assert out["halted"] is True
    assert not (set(out) & set(W.DESIGN_OUTPUTS)), f"a halted run leaked {set(out) & set(W.DESIGN_OUTPUTS)}"


@pytest.mark.parametrize("verdict", ["reject", "integration"])
def test_a_halting_verdict_never_stores_a_design(verdict):
    """"Not attempted" means the work does not run, not that its output is discarded."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_router()) as h:
        run_spine(W, h, _design_inputs(verdict=verdict))
    assert not [c for c in h.router.calls if c[0] == SemanticTools.store_spec]


def test_a_rejection_goes_to_an_architect_and_releases_nothing():
    """FR-12: an architect sees it before the submitter. Approving a FINDING must not start the
    next process, so the approval carries no continuation at all."""
    from lab.workloads.use_case_design import workflow as W
    with spine(W, _design_router()) as h:
        out = run_spine(W, h, _design_inputs(verdict="reject"))
    asked = [c for c in h.router.calls if c[0] == ApprovalTools.ask][0][1]
    assert "continuation" not in asked
    assert continuation_of(asked) is None
    assert out["approval_id"] == "apr-2"


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
