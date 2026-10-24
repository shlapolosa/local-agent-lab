"""The modelling agent's output -> the envelope: deterministic, legal, and every item cited."""
import jsonschema

from lab.core.archimate.engine import _REL_TYPES, _TYPES
from lab.core.modelling import agent_schema, mapping
from lab.core.modelling.provenance import Source

TEXT = ("The triage nurse assesses each referral.\n\n"
        "Referrals are stored in the Cerner EHR, which runs on the hospital's PostgreSQL cluster.")
SRC = {"S1": Source(ref="art://1/brief.docx", name="brief.docx", media_type="x", text=TEXT)}


def _cite(quote, para=1, source="S1"):
    return {"source": source, "location": {"paragraph": para}, "quote": quote}


def _el(name, atype, layer, aspect, quote, para=1):
    return {"name": name, "role": f"the {name}", "type": atype, "provenance": [_cite(quote, para)]}


OUTPUT = {
    "systemName": "Referral triage",
    "summary": "Nurses triage referrals held in the EHR.",
    "elements": [
        _el("Triage nurse", "BusinessRole", "Business", "active", "The triage nurse"),
        _el("Assess referral", "BusinessProcess", "Business", "behaviour", "assesses each referral"),
        _el("Referral", "BusinessObject", "Business", "passive", "each referral"),
        _el("Cerner EHR", "ApplicationComponent", "Application", "active", "the Cerner EHR", 2),
        _el("PostgreSQL cluster", "SystemSoftware", "Technology", "active",
            "the hospital's PostgreSQL cluster", 2),
    ],
    "relationships": [
        {"source": "Triage nurse", "target": "Assess referral", "type": "Assignment", "provenance": [_cite("The triage nurse assesses")]},
        {"source": "Assess referral", "target": "Referral", "type": "Access", "accessType": "Read", "provenance": [_cite("assesses each referral")]},
        {"source": "PostgreSQL cluster", "target": "Cerner EHR", "type": "Serving", "provenance": [_cite("runs on the hospital's PostgreSQL cluster", 2)]},
    ],
    "openQuestions": [{"text": "Is the EHR in scope?", "elements": ["Cerner EHR"]}],
}


def test_the_agent_schema_offers_exactly_the_engine_s_types():
    s = agent_schema.schema()
    jsonschema.Draft202012Validator.check_schema(s)
    el = s["$defs"]["element"]["properties"]["type"]["enum"]
    rel = s["$defs"]["relationship"]["properties"]["type"]["enum"]
    assert set(el) == set(_TYPES) and set(rel) == set(_REL_TYPES)


def test_the_prompt_names_every_field_the_schema_requires():
    """A prompt that never mentions a required field gets it omitted; the gate then burns a retry."""
    text = agent_schema.prompt()
    s = agent_schema.schema()
    for field in s["required"] + s["$defs"]["citation"]["required"]:
        assert f"`{field}`" in text, field
    assert "[¶n]" in text


def test_the_reference_output_validates():
    jsonschema.Draft202012Validator(agent_schema.schema()).validate(OUTPUT)


def test_a_citation_without_a_quote_is_refused_by_the_schema():
    bad = {**OUTPUT, "elements": [{**OUTPUT["elements"][0], "provenance": []}]}
    assert list(jsonschema.Draft202012Validator(agent_schema.schema()).iter_errors(bad))


def test_elements_get_stable_typed_ids_across_every_layer():
    env = mapping.to_envelope(OUTPUT, SRC)
    ids = {e["id"]: e["type"] for e in env["spec"]["elements"]}
    assert ids == {"business-role-triage-nurse": "BusinessRole", "bp-assess-referral": "BusinessProcess",
                   "bo-referral": "BusinessObject", "ac-cerner-ehr": "ApplicationComponent",
                   "system-software-postgresql-cluster": "SystemSoftware"}
    assert env["spec"]["name"] == "Referral triage"


def test_relations_resolve_by_name_and_carry_their_provenance():
    env = mapping.to_envelope(OUTPUT, SRC)
    rels = {(r["src"], r["type"], r["tgt"]): r for r in env["spec"]["relations"]}
    acc = rels[("bp-assess-referral", "Access", "bo-referral")]
    assert acc["accessType"] == "Read"
    (p,) = env["provenance"]["relations"][acc["id"]]
    assert p == {"source_ref": "art://1/brief.docx", "location": {"paragraph": 1},
                 "quote": "assesses each referral"}


def test_a_fully_grounded_output_raises_only_the_agent_s_own_questions():
    env = mapping.to_envelope(OUTPUT, SRC)
    (q,) = env["open_questions"]
    assert q["kind"] == "raised" and q["refs"]["elements"] == ["ac-cerner-ehr"]


def test_an_illegal_relation_is_dropped_not_raised():
    out = {**OUTPUT, "relationships": [{"source": "Referral", "target": "Triage nurse",
                                        "type": "Assignment",
                                        "provenance": [_cite("each referral")]}]}
    env = mapping.to_envelope(out, SRC)
    assert env["spec"]["relations"] == [] and env["dropped"][0]["src"] == "bo-referral"


def test_a_relation_naming_an_unknown_or_ambiguous_element_is_dropped_with_the_reason():
    out = {**OUTPUT,
           "elements": OUTPUT["elements"] + [_el("Referral", "DataObject", "Application", "passive",
                                                 "each referral")],
           "relationships": [
               {"source": "Ghost", "target": "Referral", "type": "Association",
                "provenance": [_cite("x")]},
               {"source": "Triage nurse", "target": "Referral", "type": "Association",
                "provenance": [_cite("x")]}]}
    reasons = sorted(d["reason"] for d in mapping.to_envelope(out, SRC)["dropped"])
    assert reasons == ["ambiguous endpoint: Referral", "endpoint not declared: Ghost"]


def test_a_name_shared_by_two_types_resolves_to_the_one_reading_that_is_legal():
    """Review finding 5: `Referral` as an object and as a process. Assignment from a role is legal
    only to the process, so that is the edge, not a drop."""
    out = {**OUTPUT,
           "elements": OUTPUT["elements"] + [_el("Referral", "BusinessProcess", "Business", "behaviour",
                                                 "each referral")],
           "relationships": [{"source": "Triage nurse", "target": "Referral", "type": "Assignment",
                              "provenance": [_cite("The triage nurse")]}]}
    env = mapping.to_envelope(out, SRC)
    assert [(r["src"], r["tgt"]) for r in env["spec"]["relations"]] == \
        [("business-role-triage-nurse", "bp-referral")]


def test_two_different_names_that_slug_alike_are_a_question_not_a_silent_merge():
    out = {**OUTPUT, "elements": [_el("C++ Service", "ApplicationService", "Application", "behaviour",
                                      "Referrals", 2),
                                  _el("C Service", "ApplicationService", "Application", "behaviour",
                                      "Referrals", 2)],
           "relationships": [], "openQuestions": []}
    env = mapping.to_envelope(out, SRC)
    assert [q["kind"] for q in env["open_questions"]] == ["name-collision"]


def test_a_dropped_relation_keeps_the_citations_that_proposed_it():
    out = {**OUTPUT, "relationships": [{"source": "Referral", "target": "Triage nurse",
                                        "type": "Assignment", "provenance": [_cite("each referral")]}]}
    (d,) = mapping.to_envelope(out, SRC)["dropped"]
    assert d["provenance"][0]["quote"] == "each referral"


def test_the_agent_is_not_asked_for_fields_nothing_reads():
    el = agent_schema.schema()["$defs"]["element"]["properties"]
    rel = agent_schema.schema()["$defs"]["relationship"]["properties"]
    assert not {"layer", "aspect"} & set(el) and "intent" not in rel
    assert "representation" not in agent_schema.schema()["$defs"]["citation"]["properties"]


def test_a_citation_to_a_key_the_run_did_not_show_is_flagged():
    out = {**OUTPUT, "elements": [{**OUTPUT["elements"][0],
                                   "provenance": [_cite("The triage nurse", source="S9")]}],
           "relationships": [], "openQuestions": []}
    (q,) = mapping.to_envelope(out, SRC)["open_questions"]
    assert q["kind"] == "unknown-source"


def test_the_same_element_named_twice_merges_and_keeps_both_citations():
    dup = _el("Referral", "BusinessObject", "Business", "passive", "Referrals are stored", 2)
    out = {**OUTPUT, "elements": OUTPUT["elements"] + [dup], "relationships": [], "openQuestions": []}
    env = mapping.to_envelope(out, SRC)
    assert [e["id"] for e in env["spec"]["elements"]].count("bo-referral") == 1
    assert len(env["provenance"]["elements"]["bo-referral"]) == 2
