"""Each screening step reads what the CAFÉ workbook places at it — the workbook is the source of truth
for which artifact a step consumes (user decision, 28 Sep 2026).

| step | reads (workbook) |
|---|---|
| 3 frame | business capability map |
| 4 / 9 | ontology |
| 5 match | technology capability map + the business context step 3 chose |
| 6 realise | the realisation view (for what step 5 matched) + the AI and traditional as-is |
| 7 criticality | criticality taxonomy (+ its CRMF and continuity-tier alignment) |
| 8 quality | quality-attribute patterns + the as-is service levels |
"""
import pytest

from lab.workloads.use_case_screening import workflow as W


def test_every_workbook_placed_corpus_is_pinned_and_read():
    wanted = {"business-capability-l3", "ontology-concepts", "ai-as-is-architecture",
              "traditional-as-is-architecture", "criticality-taxonomy", "quality-attributes",
              "ai-capability-map"}
    pinned = set(W.REFERENCE_ARTIFACTS)
    assert wanted <= pinned, sorted(wanted - pinned)
    read = {a for artifacts in W.CORPUS.values() for a, _ in artifacts}
    assert wanted - {"ai-capability-map"} <= read      # the realisation view is joined, not shown


def test_the_step_context_names_the_workbook_inputs():
    from lab.workloads.usecase.agents import CONTEXT_FOR
    assert "business_capabilities" in CONTEXT_FOR["frame"]
    assert "ontology" in CONTEXT_FOR["elements"]
    assert "business_context" in CONTEXT_FOR["coverage_map"]
    assert {"realisations", "landscape"} <= set(CONTEXT_FOR["realisation_match"])
    assert "criticality_taxonomy" in CONTEXT_FOR["criticality_band"]
    assert {"quality_patterns", "service_levels"} <= set(CONTEXT_FOR["quality_attributes"])


# ------------------------------------------------ the two joins the run derives between steps

BUSINESS = [{"id": "B1.1.2", "name": "Policy drafting & consultation",
             "served_by_technology_l3": "COG.24; KNW.01", "ai_candidacy": "high"},
            {"id": "B3.2.1", "name": "Referral triage", "served_by_technology_l3": "",
             "ai_candidacy": "to assess"}]


def test_business_context_is_what_step_3_chose_WITH_the_technology_the_corpus_says_serves_it():
    frame = {"business_capabilities": [{"id": "B1.1.2", "why": "drafts policy"}]}
    got = W.business_context(frame, BUSINESS)
    assert got == [{"id": "B1.1.2", "name": "Policy drafting & consultation",
                    "served_by_technology_l3": ["COG.24", "KNW.01"], "ai_candidacy": "high"}]


def test_no_business_capability_chosen_is_no_business_context_rather_than_the_whole_map():
    assert W.business_context({"business_capabilities": []}, BUSINESS) == []
    assert W.business_context({}, BUSINESS) == []


REALISATIONS = [{"l3_id": "KNW.01", "capability": "Agentic retrieval", "primary": "Foundry IQ",
                 "alternative": "AI Search", "sovereign": "Core42", "uae_north_status": "GA",
                 "constraint": "", "components": "cmp-1", "rationale": "long text " * 40},
                {"l3_id": "COG.02", "capability": "Custom agent hosting", "primary": "ACA",
                 "alternative": "", "sovereign": "", "uae_north_status": "GA", "constraint": "",
                 "components": "cmp-2", "rationale": ""}]


def test_realisations_are_the_rows_for_what_step_5_MATCHED_and_nothing_else():
    coverage = {"matched": [{"function": "f", "capability_id": "KNW.01"}]}
    got = W.realisations_for(coverage, REALISATIONS)
    assert [r["l3_id"] for r in got] == ["KNW.01"]
    assert got[0]["primary"] == "Foundry IQ" and "rationale" not in got[0], "projected, not dumped"


def test_nothing_matched_is_no_realisations():
    assert W.realisations_for({"matched": []}, REALISATIONS) == []


# ------------------------------------------------ step 3's gate: only a business L3 it was shown

def test_step_3_refuses_a_business_capability_it_was_not_shown():
    from lab.workloads.usecase.steps import step_for
    out = {"problem": "Referrals wait days to be triaged by hand.", "for_whom": "triage nurses",
           "expected_change": "urgent referrals seen within a day", "accountable_owner": "Jane Doe",
           "business_capabilities": [{"id": "B9.9.9", "why": "invented"}]}
    problems = step_for("3").complete(out, {"business_capabilities": {"business-capability-l3": BUSINESS}})
    assert any("B9.9.9" in p for p in problems), problems


def test_step_3_accepts_one_it_was_shown():
    from lab.workloads.usecase.steps import step_for
    out = {"problem": "Referrals wait days to be triaged by hand.", "for_whom": "triage nurses",
           "expected_change": "urgent referrals seen within a day", "accountable_owner": "Jane Doe",
           "business_capabilities": [{"id": "B3.2.1", "why": "it is triage"}]}
    assert not step_for("3").complete(out, {"business_capabilities": {"business-capability-l3": BUSINESS}})


# ------------------------------------------------ enrichment never gates the backbone

def test_a_corpus_that_ENRICHES_a_step_is_optional_and_one_it_cannot_work_without_is_not():
    """Step 4 ran without the ontology for weeks; it is the backbone every later step reads. Making
    a PRIVATE master (the ontology is published by reference) a hard input would let one upload
    nobody made stall every run at step 4. What only enriches a step is declared optional: handed
    over when present, named in `corpora_unavailable` when absent, never a reason to defer."""
    from lab.workloads.usecase.agents import CONTEXT_FOR, OPTIONAL_CONTEXT
    assert "ontology" in OPTIONAL_CONTEXT["elements"]
    assert "business_capabilities" in OPTIONAL_CONTEXT["frame"]
    assert "capabilities" not in OPTIONAL_CONTEXT.get("coverage_map", ()), \
        "step 5 cannot match against no map — that stays hard (and defaults)"
    for key, optional in OPTIONAL_CONTEXT.items():
        assert set(optional) <= set(CONTEXT_FOR[key]), f"{key}: optional names an input it lacks"


def test_run_step_runs_a_step_whose_only_absent_inputs_are_optional():
    import asyncio
    from lab.workloads.usecase.derivation import Derivation
    from lab.workloads.usecase.steps import step_for
    ran = {}

    class Agent:                                     # the gated call is stubbed below
        pass

    import lab.workloads.usecase.derivation as D

    async def fake_run_gated(agent, message, **kw):
        ran["message"] = message
        return {"problem": "Referrals wait days to be triaged by hand.",
                "for_whom": "triage nurses", "expected_change": "urgent referrals seen same day",
                "accountable_owner": "Jane Doe", "open_questions": []}
    d = Derivation(available={"submission": "A use case."}, pending={}, publish=None)
    orig = D.run_gated
    D.run_gated = fake_run_gated
    try:
        ok = asyncio.run(d.run_step({"agents": {"frame": Agent()}}, step_for("3")))
    finally:
        D.run_gated = orig
    assert ok and "frame" in d.derived, "no business map is no reason not to frame the use case"


# ------------------------------------------------ step 6: a shortlist, of what it was shown

def _six(shortlist):
    return {"matched": [{"element": "triage nurse", "realised_by": "Sahatna", "confidence": "lookup"}],
            "unrealised": [], "existing": False, "shortlist": shortlist}


def test_step_6_refuses_a_shortlist_for_a_capability_it_was_not_shown():
    from lab.workloads.usecase.steps import step_for
    out = _six([{"capability_id": "ZZZ.99", "route": "microsoft", "realisation": "Something"}])
    problems = step_for("6").complete(out, {"realisations": REALISATIONS})
    assert any("ZZZ.99" in p for p in problems), problems


def test_step_6_accepts_a_shortlist_of_rows_it_was_shown_and_needs_none_at_all():
    from lab.workloads.usecase.steps import step_for
    ok = _six([{"capability_id": "KNW.01", "route": "sovereign", "realisation": "Core42"}])
    assert not step_for("6").complete(ok, {"realisations": REALISATIONS})
    assert not step_for("6").complete(_six([]), {"realisations": REALISATIONS})


# ------------------------------------------------ a step told what it was NOT shown (review F3)

def test_a_step_given_a_PARTLY_read_corpus_says_so_in_its_own_gap_flags():
    """Step 6 handed only the AI half of the landscape answered `estate_touched: []` — read as
    "touches nothing" when the truth was "could not be checked". The gap is stated on the step's
    own output, deterministically, rather than hoped for from a prompt."""
    out = {"matched": [], "unrealised": [], "existing": False, "gap_flags": []}
    missing = {"landscape (partly)": "traditional-as-is-architecture: not published on this ring"}
    W.note_corpus_gaps("realisation_match", out, missing)
    assert any("landscape" in g["what"] and "traditional-as-is" in g["what"]
               for g in out["gap_flags"]), out["gap_flags"]


def test_an_absent_OPTIONAL_input_is_noted_too_but_a_hard_one_never_reaches_here():
    out = {"gap_flags": []}
    W.note_corpus_gaps("quality_attributes", out, {"quality_patterns": "not published"})
    assert any("quality_patterns" in g["what"] for g in out["gap_flags"])


def test_a_step_whose_schema_has_no_gap_flags_is_left_alone():
    out = {"active": []}
    W.note_corpus_gaps("elements", out, {"ontology": "not published"})
    assert out == {"active": []}


def test_nothing_missing_adds_nothing():
    out = {"gap_flags": []}
    W.note_corpus_gaps("realisation_match", out, {"source_classification": "unpublished"})
    assert out["gap_flags"] == []


def test_no_optional_input_can_mask_a_declared_default():
    """Review F8: a step defaults exactly when its corpus is its ONLY missing input
    (`needs == [corpus]`). Were that corpus declared optional it would never be missing, and the
    default — the honest "we do not know" — would silently stop being recorded."""
    from lab.workloads.usecase import fallbacks
    from lab.workloads.usecase.agents import OPTIONAL_CONTEXT
    for step, corpus in fallbacks.CORPUS_FOR.items():
        assert corpus not in OPTIONAL_CONTEXT.get(step, ()), (step, corpus)


def test_matched_capabilities_with_no_realisation_row_are_named():
    coverage = {"matched": [{"capability_id": "KNW.01"}, {"capability_id": "ZZZ.99"}]}
    assert W.unrealised_matches(coverage, REALISATIONS) == ["ZZZ.99"]
