"""Contract 1.1.0 additions (D15–D20): reviews that survive a re-run, renames, repository matches,
vocabulary links, per-element change status, and the id rule."""
from lab.core.modelling import envelope
from lab.core.modelling.provenance import Source

REF = "art://a/brief.md"
TEXT = "The clinician assesses the referral."
PROV = [{"source_ref": REF, "location": {"paragraph": 1}, "quote": "the referral"}]


def _spec(*ids):
    return {"name": "m", "elements": [{"id": i, "type": "BusinessObject", "name": i} for i in ids]}


def _build(ids=("bo-referral", "bo-plan"), **kw):
    args = {"spec": _spec(*ids), "provenance": {"elements": {i: PROV for i in ids}, "relations": {}},
            "sources": [Source(ref=REF, name="brief.md", media_type="text/markdown", text=TEXT)]}
    return envelope.build(**(args | kw))


def _kinds(env):
    return sorted(q["kind"] for q in env["open_questions"])


def _review(item_id="bo-referral", **kw):
    return {"item_kind": "element", "item_id": item_id, "state": "accepted", "actor": "ea@tenant"} | kw


# ---------------------------------------------------------------- R-1 reviews round-trip
def test_reviews_on_ids_that_still_exist_carry_over():
    env = _build(reviews=[_review()])
    assert env["reviews"] == [_review()] and env["open_questions"] == []


def test_a_review_whose_item_disappeared_is_surfaced_not_dropped():
    env = _build(reviews=[_review("bo-gone")])
    assert env["reviews"] == []
    (q,) = env["open_questions"]
    assert q["kind"] == "review-orphaned" and q["refs"]["elements"] == ["bo-gone"]


def test_a_review_without_an_actor_is_refused_as_malformed():
    assert _kinds(_build(reviews=[_review(actor=" ")])) == ["malformed-review"]


def test_no_reviews_is_an_empty_list():
    assert _build()["reviews"] == []


# ---------------------------------------------------------------- R-2 renames
def test_a_review_follows_an_element_across_a_declared_rename():
    env = _build(ids=("bo-referral-letter", "bo-plan"),
                 renamed_from={"bo-referral-letter": ["bo-referral"]}, reviews=[_review("bo-referral")])
    assert env["reviews"] == [_review("bo-referral-letter")]
    assert env["renamed_from"] == {"bo-referral-letter": ["bo-referral"]}


def test_a_rename_onto_an_element_the_model_lacks_is_reported():
    env = _build(renamed_from={"bo-ghost": ["bo-old"]})
    assert env["renamed_from"] == {} and _kinds(env) == ["orphan-reference"]


# ---------------------------------------------------------------- R-3 repository, R-4 concepts
def test_repository_matches_use_the_change_vocabulary():
    hit = {"element_id": "bo-referral", "repository_id": "obj-9", "repository_class": "C_BUSINESS_OBJECT",
           "match": "consumed", "confidence": "high", "candidates": [{"repository_id": "obj-9"}]}
    env = _build(references={"repository": [hit]})
    assert env["references"]["repository"] == [hit] and env["open_questions"] == []
    assert _kinds(_build(references={"repository": [hit | {"match": "reuse"}]})) == ["malformed-reference"]


def test_concept_links_are_linked_or_candidate():
    link = {"element_id": "bo-referral", "concept_iri": "urn:fabric:concept:referral", "label": "Referral",
            "scheme": "cafe", "status": "linked", "confidence": "high"}
    assert _build(references={"concepts": [link]})["references"]["concepts"] == [link]
    assert _kinds(_build(references={"concepts": [link | {"status": "new"}]})) == ["malformed-reference"]


def test_every_reference_kind_is_present_even_when_empty():
    assert set(_build()["references"]) == {"capabilities", "realisations", "repository", "concepts"}


# ---------------------------------------------------------------- R-5 / M-10 change status
def test_changes_are_keyed_by_element_and_use_the_change_vocabulary():
    env = _build(changes={"bo-referral": "updated", "bo-plan": "new"})
    assert env["changes"] == {"bo-referral": "updated", "bo-plan": "new"}


def test_a_bad_change_is_reported_not_kept():
    env = _build(changes={"bo-referral": "modified", "bo-ghost": "new"})
    assert env["changes"] == {} and _kinds(env) == ["malformed-reference", "orphan-reference"]


def test_missing_is_for_capabilities_only():
    assert "missing" not in envelope.CHANGES and set(envelope.STATUSES) == set(envelope.CHANGES) | {"missing"}


# ---------------------------------------------------------------- id rule
def test_an_id_outside_the_local_name_rule_is_flagged():
    env = _build(ids=("B1.1.2", "bo-plan"))
    assert "invalid-id" in _kinds(env)
    assert envelope.ID_PATTERN.fullmatch("cap-b1-1-2") and not envelope.ID_PATTERN.fullmatch("B1.1.2")
