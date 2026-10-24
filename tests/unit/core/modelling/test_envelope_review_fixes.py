"""The design review's findings on the envelope (24 Oct): each a promise the builder did not keep."""
import json
import os

import jsonschema
from referencing import Registry, Resource

from lab.core.archimate.ids import rid
from lab.core.modelling import envelope
from lab.core.modelling.provenance import Source, check, Provenance

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))
REF = "art://a/brief.md"
TEXT = "The clerk files the referral.\n\nThe referral is stored in the EHR."


def _contract():
    def load(n):
        with open(os.path.join(ROOT, "contracts", n), encoding="utf-8") as f:
            return json.load(f)
    m, s = load("modelling.json"), load("archimate-spec.schema.json")
    reg = Registry().with_resources([(s["$id"], Resource.from_contents(s)),
                                     (m["$id"], Resource.from_contents(m))])
    return jsonschema.Draft202012Validator(m, registry=reg)


def _p(quote="the referral", para=1, ref=REF):
    return {"source_ref": ref, "location": {"paragraph": para}, "quote": quote}


def _build(ids=("ba-clerk", "bo-referral"), rels=(), **kw):
    spec = {"name": "m", "elements": [{"id": i, "type": "BusinessObject" if i.startswith("bo-")
                                       else "BusinessActor", "name": i} for i in ids],
            "relations": [{"id": rid(s, t, g), "type": t, "src": s, "tgt": g} for s, t, g in rels]}
    prov = {"elements": {i: [_p()] for i in ids},
            "relations": {rid(s, t, g): [_p()] for s, t, g in rels}}
    args = {"spec": spec, "provenance": prov,
            "sources": [Source(ref=REF, name="brief.md", media_type="text/markdown", text=TEXT)]}
    return envelope.build(**(args | kw))


def _kinds(env):
    return sorted(q["kind"] for q in env["open_questions"])


# ---------------------------------------------------------------- 1: output always fits the contract
def test_a_reference_missing_a_required_field_is_reported_not_kept():
    env = _build(references={"capabilities": [{"element_id": "bo-referral", "capability_id": "K",
                                               "status": "new"}]})          # no `map`
    assert env["references"]["capabilities"] == [] and _kinds(env) == ["malformed-reference"]


def test_numbers_where_the_contract_says_string_are_coerced_not_kept_raw():
    env = _build(references={"capabilities": [{"element_id": "bo-referral", "map": "m",
                                               "capability_id": "K", "status": "new",
                                               "confidence": 0.8, "level": 3}]})
    (ref,) = env["references"]["capabilities"]
    assert ref["confidence"] == "0.8"
    _contract().validate(env)


def test_an_invalid_id_never_becomes_a_key_in_changes_or_renames():
    env = _build(ids=("B1.1.2", "bo-referral"), changes={"B1.1.2": "new"},
                 renamed_from={"B1.1.2": ["old"]})
    assert "B1.1.2" not in env["changes"] and "B1.1.2" not in env["renamed_from"]


def test_every_kind_of_bad_input_still_yields_a_contract_valid_envelope():
    env = _build(
        ids=("B1.1.2", "bo-referral"),
        provenance={"elements": {"bo-referral": ["not a dict", _p("absent words"),
                                                  {"source_ref": REF, "quote": "x"}],
                                 "ghost": [_p()]}, "relations": {}},
        references={"capabilities": [{"element_id": "x", "map": 1, "capability_id": "K",
                                      "status": "new", "confidence": 0.3}],
                    "concepts": [{"element_id": "bo-referral", "label": "R", "status": "linked",
                                  "confidence": 1}]},
        changes={"bo-referral": "updated", "B1.1.2": "new", "ghost": "new"},
        reviews=[{"item_kind": "element", "item_id": "ghost", "state": "accepted", "actor": "a"},
                 "garbage"],
        questions=[{"text": "?"}])
    _contract().validate(env)


# ---------------------------------------------------------------- 4: question ids are unique
def test_two_different_questions_never_share_an_id():
    env = _build(provenance={"elements": {"ba-clerk": [_p(ref="art://x/1"), _p(ref="art://x/2")],
                                          "bo-referral": [_p()]}, "relations": {}})
    ids = [q["id"] for q in env["open_questions"]]
    assert len(ids) == 2 and len(set(ids)) == 2


def test_an_exact_repeat_is_asked_once():
    env = _build(questions=[{"text": "Is the EHR in scope?"}, {"text": "Is the EHR in scope?"}])
    assert len(env["open_questions"]) == 1


# ---------------------------------------------------------------- 3: relation reviews follow renames
def test_a_relation_review_follows_a_rename_of_either_endpoint():
    old = rid("ba-clerk", "Association", "bo-referral")
    new = rid("ba-filing-clerk", "Association", "bo-referral")
    env = _build(ids=("ba-filing-clerk", "bo-referral"),
                 rels=[("ba-filing-clerk", "Association", "bo-referral")],
                 renamed_from={"ba-filing-clerk": ["ba-clerk"]},
                 reviews=[{"item_kind": "relation", "item_id": old, "state": "accepted", "actor": "a"}])
    assert [r["item_id"] for r in env["reviews"]] == [new] and env["open_questions"] == []


# ---------------------------------------------------------------- 9: the cited paragraph is checked
def _src():
    return {REF: Source(ref=REF, name="brief.md", media_type="text/markdown", text=TEXT)}


def test_a_quote_in_its_cited_paragraph_raises_nothing():
    assert check(Provenance.from_dict(_p("stored in the EHR", 2)), _src()) is None


def test_a_quote_found_in_another_paragraph_is_a_location_mismatch():
    assert check(Provenance.from_dict(_p("stored in the EHR", 1)), _src()) == "location-mismatch"


def test_a_paragraph_the_source_does_not_have_is_a_location_mismatch():
    assert check(Provenance.from_dict(_p("the referral", 99)), _src()) == "location-mismatch"


def test_a_quote_nowhere_in_the_source_is_still_not_found():
    assert check(Provenance.from_dict(_p("absent words", 1)), _src()) == "quote-not-found"


# ---------------------------------------------------------------- 11: never raises on junk
def test_a_non_mapping_provenance_or_review_is_reported_not_raised():
    env = _build(provenance={"elements": {"ba-clerk": ["junk"], "bo-referral": [_p()]}, "relations": {}},
                 reviews=["junk"])
    assert "malformed-provenance" in _kinds(env) and "malformed-review" in _kinds(env)
