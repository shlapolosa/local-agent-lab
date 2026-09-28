"""Component to family, derived from what the corpus publishes — and silent where it does not."""
from lab.workloads.usecase import families

# The corpus's shapes since the CAFÉ workbook (28 Sep 2026): `cap` names technology L3s as "id name",
# and the realisation view carries one row per L3 by `l3_id`.
GUARDRAILS = [{"id": "G06", "cap": "KNW.13 Grounding source registry"},
              {"id": "G13", "cap": "KNW.12 Federated retrieval"},
              {"id": "G01", "cap": "COG.02 Agent runtime; XCT.22 Gate decision"},
              {"id": "G99", "cap": ""}]
MAP = [{"l3_id": "KNW.13", "capability": "Grounding source registry", "components": "cmp-search"},
       {"l3_id": "COG.02", "capability": "Agent runtime", "components": "cmp-runtime; cmp-hosts"},
       {"l3_id": "XCT.22", "capability": "Gate decision", "components": "cmp-approval"}]
ENFORCEMENT = {"F1": ["G06", "G13"], "F2": ["G01"], "F9": ["G99"]}


def test_a_component_carries_a_family_when_it_realises_a_capability_that_enforces_its_guardrail():
    got = families.by_component(ENFORCEMENT, GUARDRAILS, MAP)
    assert got == {"cmp-approval": ["F2"], "cmp-hosts": ["F2"], "cmp-runtime": ["F2"],
                   "cmp-search": ["F1"]}
    assert families.of_component("cmp-search", ENFORCEMENT, GUARDRAILS, MAP) == ["F1"]
    assert families.of_component("cmp-nothing", ENFORCEMENT, GUARDRAILS, MAP) == []


def test_a_family_the_corpus_says_nothing_about_is_named_rather_than_counted_as_uncovered():
    """Ten of twenty-six published guardrails name a capability. A family whose guardrails name none
    is the corpus being silent, not the design failing — and a rule that cannot tell them apart
    refuses work nobody could have done."""
    assert families.unclaimed(ENFORCEMENT, GUARDRAILS, MAP) == ["F9"]
    assert families.unclaimed({}, GUARDRAILS, MAP) == []


def test_a_cell_may_arrive_joined_or_already_decoded():
    joined = [{"l3_id": "KNW.13", "capability": "Grounding source registry",
               "components": "cmp-a; cmp-b"}]
    decoded = [{"l3_id": "KNW.13", "capability": "Grounding source registry",
                "components": ["cmp-a", "cmp-b"]}]
    for rows in (joined, decoded):
        got = families.by_component({"F1": "G06"}, GUARDRAILS, rows)
        assert got == {"cmp-a": ["F1"], "cmp-b": ["F1"]}


def test_the_real_corpus_resolves_some_families_and_admits_the_rest():
    from fixtures.usecase_corpus import corpus
    c = corpus()
    enforcement = {r["id"]: r.get("guardrails") for r in c["family-triggers"]}
    got = families.by_component(enforcement, c["guardrails"], c["ai-capability-map"])
    silent = families.unclaimed(enforcement, c["guardrails"], c["ai-capability-map"])
    assert got, "the published chain resolves something"
    assert all(f.startswith("F") for fams in got.values() for f in fams)
    assert set(silent) < set(enforcement), "not every family is unclaimed, or the join is broken"
