"""Well-formed answers for the design-side steps — the shape a gate ACCEPTS.

Shared because two suites need them and they are large enough that a second copy would drift: the
spine tests script an agent with them, the gate tests take one field away at a time. Each is the
smallest answer that satisfies its rule, so removing any one field is a meaningful rejection rather
than a shape error.
"""
from lab.core.usecase import seed

__all__ = ["ANSWERED", "ASSERTIONS", "BENEFIT_INPUTS", "BUILD_SURFACE", "COMPONENTS",
           "COST_INPUTS", "DELIVERY", "DETERMINISM", "FACETS", "without"]

#: Every prose condition the published guardrails ask, answered. A facet vector that leaves one out
#: is refused, so an answer without them is not a step-17 answer at all.
ANSWERED = {c: False for c in seed.NAMED_CONDITIONS}


def without(row: dict, field: str) -> dict:
    """The same answer with one field blanked — how a gate test asks "and if this were missing?"."""
    return {k: ("" if k == field else v) for k, v in row.items()}


ASSERTIONS = {"assertions": [{"statement": "every urgent referral was seen within 24 hours",
                              "evaluated_against": "the patient administration system",
                              "reads_workflow_output": False}]}

DETERMINISM = {"steps": [{"id": "n1", "tier": "D1", "necessity": "by necessity"}],
               "governance_tier": "D1", "graph_is_explicit": True}

FACETS = {"steps": [{"id": "n1", "activity": "interpret", "determinism": "D2", "effect": "none",
                     "conditions": ANSWERED}]}

BUILD_SURFACE = {"incumbent_considered": True, "surface": "a hosted agent runtime",
                 "topology": "T2", "unenforceable_obligations": []}

COMPONENTS = {"selected": [{"capability": "inference", "component": "the hosted model service",
                            "rejected_alternatives": ["a self-hosted model"]}],
              "tradeoffs": [], "unresolved": []}

COST_INPUTS = {"resources": ["Container Apps"], "switched_on_by": {"Container Apps": "family F2"},
               "envelope": "expected", "unpriceable": []}

BENEFIT_INPUTS = {"effort": [{"role": "nurse", "headcount": 4, "frequency_per_week": 20,
                              "current_minutes": 30, "expected_minutes": 10,
                              "source": "the submission, paragraph 2"}],
                  "sensitivity_flags": [], "data_fully_digital": True,
                  "excluded_value": [], "unsupplied": []}

DELIVERY = {
    "business_case": [
        {"section": "Executive summary", "content": "Referral triage is too slow to be safe."},
        {"section": "Current state", "content": "Manual triage by a nurse, 30 minutes a referral."},
        {"section": "Proposed solution", "content": "The composed architecture, families F2-F11."},
        {"section": "Value drivers", "content": "Efficiency and quality; nothing else is claimed."},
        {"section": "Financial summary", "content": "Year-1 30,000; payback in five months."},
        {"section": "Roadmap", "content": "Two phases, anchored on the Q3 date given at intake."},
        {"section": "Risks and mitigations", "content": "One open readiness condition remains."},
        {"section": "Approvals and recommendation", "content": "Proceed with conditions; see 7."},
    ],
    "decision_records": [{"context": "latency against cost on the inference tier",
                          "drivers": ["responsiveness", "G08"],
                          "options": ["provisioned throughput", "consumption"],
                          "decision": "consumption",
                          "sacrificed": "p95 latency, by roughly 400 ms at peak",
                          "compensating_control": "a queue with a published depth alarm",
                          "review_trigger": "sustained volume above 10,000 referrals a day",
                          "approver": "the solution architect"}],
    "service_contracts": [{"name": "Triage referral", "consumers": ["the referrals portal"],
                           "offered_behaviour": "Returns a triage band and its rationale.",
                           "service_level": "p95 under two seconds, 99.5% availability",
                           "service_level_source": "the referrals business service level, clause 4",
                           "owned_entities": ["referral"],
                           "failure_semantics": "On failure the referral stays untriaged and is "
                                                "queued for a human.",
                           "versioning": "additive only within a major version"}],
    "work_items": [{"key": "EPIC-1", "title": "Build the triage agent", "owner": "delivery lead",
                    "obligations": ["G01", "G08"]}],
    "catalog_entry": {"name": "Referral triage", "owner": "clinical operations",
                      "description": "Triages an inbound referral and explains the band it gave.",
                      "capability": "c1"},
    "open_questions": [],
}
