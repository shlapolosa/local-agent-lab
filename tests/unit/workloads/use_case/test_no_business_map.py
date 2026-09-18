"""What a run does when this tenant has published no BUSINESS capability map.

Decided 18 Sep 2026. CAFÉ does not supply the map — "the enterprise owns it" — and the licensed
generic workbook cannot stand in for one: 80% of its matched level names nothing clinical, and a
chat bot that tells the time matched it three to four times on every run with entries whose
definitions were literally true of it. So the map is a SETTING, empty until an enterprise publishes
a conformant one, and step 5 records a declared default in the meantime.

The sharp edge is the feasibility rule. `capability_matched=False` REJECTS — "the use case serves no
capability on the map, so there is nothing for it to improve" — which is a sound rule when a map
exists and a catastrophic one when none does: absence of evidence read as evidence of absence would
auto-reject every use case the lab ever sees, citing a map nobody published.
"""
from lab.core.usecase.gates import Feasibility, feasibility_verdict
from lab.workloads.usecase import fallbacks

POOL = {"elements": {"behavioural": [{"name": "assess urgency"}, {"name": "assign specialty"}],
                     "active": [{"name": "Triage nurse"}], "passive": [{"name": "Referral"}]}}


def test_step_5_has_a_declared_default_like_every_other_uncorpused_step():
    assert "coverage_map" in fallbacks.FALLBACKS
    assert fallbacks.CORPUS_FOR["coverage_map"] == "capabilities"


def test_the_default_matches_nothing_and_says_so_function_by_function():
    """Conservative reading of not knowing: no function is claimed to serve a capability, and every
    one is named as unmatched. Claiming a match would put a capability nobody published into a
    design package."""
    out = fallbacks.fallback("coverage_map", POOL)
    assert out["matched"] == []
    assert out["functions_without_capability"] == ["assess urgency", "assign specialty"]


def test_the_default_names_the_missing_corpus_and_who_owns_it():
    flag = fallbacks.fallback("coverage_map", POOL)["gap_flags"][0]
    assert flag["what"].startswith("DEFAULT")
    assert "capability map" in flag["what"].lower()
    assert flag["owning_body"], "a gap with no owner is a gap nobody closes"


# ---------------------------------------------------------------- the feasibility rule

def verdict(**over):
    return feasibility_verdict(**{"capability_matched": True, "existing_realisation": False,
                                  "capability_is_commodity": False, "capability_is_mature": False,
                                  "capability_meets_target": False} | over)


def test_a_use_case_matching_no_capability_is_still_rejected_when_a_map_exists():
    """Unchanged, and it must stay that way: with a published map, no match IS the reject rule."""
    assert verdict(capability_matched=False).verdict is Feasibility.REJECT


def test_no_published_map_escalates_to_a_human_rather_than_rejecting():
    """`capability_matched` is UNKNOWN, not false. Rejecting would blame a use case for a corpus the
    enterprise has not published, and it would reject every one of them identically."""
    out = verdict(capability_matched=None)
    assert out.verdict is Feasibility.ESCALATE
    assert "no business capability map" in out.rule.lower()


def test_the_escalation_rule_says_what_a_human_is_being_asked_to_decide():
    """An escalation that does not name the question is a stall. It follows the precedent set by
    the investment step, which escalates by name when no delegation-of-authority table is set."""
    assert "capability" in verdict(capability_matched=None).rule.lower()


def test_an_unknown_match_does_not_skip_the_rules_after_it():
    """Escalation replaces only the FIRST rule. An existing realisation is still an integration,
    whatever is known about the capability — the rules after it read other evidence entirely."""
    out = verdict(capability_matched=None, existing_realisation=True)
    assert out.verdict is Feasibility.INTEGRATION


def test_an_escalation_asks_the_person_to_decide_not_to_overturn():
    """The approval a human sees. "Confirm or overturn the finding" frames a decision they must
    MAKE as a machine judgement they may correct — and there is no finding to overturn: nothing was
    rejected and nothing was approved."""
    from lab.workloads.use_case_design.workflow import finding_prompt
    escalated = finding_prompt("escalate")
    assert "Decide it" in escalated and "overturn" not in escalated
    assert "overturn" in finding_prompt("reject"), "a real finding is still overturnable"
