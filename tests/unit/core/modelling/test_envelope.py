"""The modelling envelope: the FR-11 spec UNCHANGED, with provenance and open questions beside it (D6)."""
from lab.core.modelling import envelope
from lab.core.modelling.provenance import Source

REF = "art://a/brief.docx"
TEXT = "The clinician assesses the referral. The referral is stored in the EHR."


def _spec():
    return {
        "name": "use case", "id": "usecase-model", "standard_views": True,
        "elements": [
            {"id": "ba-clinician", "type": "BusinessActor", "name": "Clinician", "folder": "Business",
             "props": {"provenance": "free text from before D5"}},
            {"id": "bo-referral", "type": "BusinessObject", "name": "Referral", "folder": "Business"},
        ],
        "relations": [{"id": "r-1", "type": "Association", "src": "ba-clinician", "tgt": "bo-referral"}],
        "dropped": [{"type": "Serving", "src": "x", "tgt": "y", "reason": "endpoint not declared"}],
        "gaps": [{"kind": "capability", "name": "triage"}],
    }


def _prov(quote="The clinician assesses the referral", ref=REF):
    return [{"source_ref": ref, "location": {"paragraph": 1}, "quote": quote}]


def _build(**kw):
    args = {"spec": _spec(),
            "provenance": {"elements": {"ba-clinician": _prov(), "bo-referral": _prov("the referral")},
                           "relations": {"r-1": _prov()}},
            "sources": [Source(ref=REF, name="brief.docx", media_type="application/vnd.openxmlformats-"
                               "officedocument.wordprocessingml.document", text=TEXT,
                               aliases=("urn:fabric:artifact:42",))]}
    return envelope.build(**(args | kw))


def test_the_spec_inside_carries_only_what_the_fr11_schema_allows():
    spec = _build()["spec"]
    assert "dropped" not in spec and "gaps" not in spec
    assert all("props" not in e for e in spec["elements"])
    assert [e["id"] for e in spec["elements"]] == ["ba-clinician", "bo-referral"]
    assert spec["standard_views"] is True


def test_what_the_spec_cannot_carry_rides_beside_it():
    env = _build()
    assert env["contract_version"] == envelope.CONTRACT_VERSION
    assert env["dropped"][0]["src"] == "x" and env["gaps"][0]["name"] == "triage"
    assert env["provenance"]["elements"]["ba-clinician"][0]["location"] == {"paragraph": 1}


def test_sources_are_listed_without_their_text():
    (src,) = _build()["sources"]
    assert src == {"ref": REF, "name": "brief.docx", "media_type": src["media_type"],
                   "aliases": ["urn:fabric:artifact:42"]}


def test_a_fully_grounded_model_has_no_open_questions():
    assert _build()["open_questions"] == []


def test_an_item_with_no_provenance_becomes_an_open_question():
    env = _build(provenance={"elements": {"ba-clinician": _prov()}, "relations": {"r-1": _prov()}})
    (q,) = env["open_questions"]
    assert q["kind"] == "no-provenance" and q["refs"] == {"elements": ["bo-referral"], "relations": []}


def test_a_paraphrased_quote_is_flagged_on_its_item():
    env = _build(provenance={"elements": {"ba-clinician": _prov(), "bo-referral": _prov("the referral")},
                             "relations": {"r-1": _prov("clinicians look at referrals")}})
    (q,) = env["open_questions"]
    assert q["kind"] == "quote-not-found" and q["refs"]["relations"] == ["r-1"]
    assert q["provenance"]["quote"] == "clinicians look at referrals"


def test_provenance_for_an_item_the_spec_lacks_is_reported_not_kept():
    env = _build(provenance={"elements": {"ba-clinician": _prov(), "bo-referral": _prov("the referral"),
                                          "ba-ghost": _prov()},
                             "relations": {"r-1": _prov()}})
    assert "ba-ghost" not in env["provenance"]["elements"]
    assert [q["kind"] for q in env["open_questions"]] == ["orphan-provenance"]


def test_a_malformed_provenance_entry_is_a_question_not_a_crash():
    """The builder runs on agent output inside a long workflow; bad data is reported, never raised."""
    env = _build(provenance={"elements": {"ba-clinician": [{"source_ref": REF, "quote": "x"}],
                                          "bo-referral": _prov("the referral")},
                             "relations": {"r-1": _prov()}})
    kinds = sorted(q["kind"] for q in env["open_questions"])
    assert kinds == ["malformed-provenance", "no-provenance"]


def test_raised_questions_pass_through_with_their_refs():
    env = _build(questions=[{"text": "Is the EHR in scope?", "refs": {"elements": ["bo-referral"]}}])
    (q,) = env["open_questions"]
    assert q["kind"] == "raised" and q["refs"] == {"elements": ["bo-referral"], "relations": []}


def test_question_ids_are_stable_across_rebuilds():
    a = _build(questions=[{"text": "Is the EHR in scope?"}])["open_questions"]
    b = _build(questions=[{"text": "Is the EHR in scope?"}])["open_questions"]
    assert [q["id"] for q in a] == [q["id"] for q in b] and a[0]["id"].startswith("oq-")


# ---------------------------------------------------------------- M-8: capability + realisation map references
def _cap(**kw):
    return {"element_id": "bo-referral", "map": "cafe-technology-capability-map", "map_version": "0.27",
            "capability_id": "KNW.11", "label": "Agentic retrieval", "level": 3, "status": "new",
            "confidence": "high"} | kw


def test_capability_and_realisation_references_ride_beside_the_spec():
    real = {"element_id": "bo-referral", "capability_id": "KNW.11", "realised_by": "Azure AI Search",
            "catalogue_id": "cmp-abc", "status": "consumed", "confidence": "medium"}
    env = _build(references={"capabilities": [_cap()], "realisations": [real]})
    assert env["references"]["capabilities"] == [_cap()] and env["references"]["realisations"] == [real]
    assert env["open_questions"] == []


def test_no_references_is_an_empty_block_not_a_missing_one():
    refs = _build()["references"]
    assert {"capabilities", "realisations"} <= set(refs) and not any(refs.values())


def test_a_reference_to_an_element_the_spec_lacks_is_reported_not_kept():
    env = _build(references={"capabilities": [_cap(element_id="ghost")]})
    assert env["references"]["capabilities"] == []
    assert [q["kind"] for q in env["open_questions"]] == ["orphan-reference"]


def test_a_status_outside_the_heatmap_vocabulary_is_reported_not_kept():
    env = _build(references={"capabilities": [_cap(status="probably")]})
    assert env["references"]["capabilities"] == []
    (q,) = env["open_questions"]
    assert q["kind"] == "malformed-reference" and q["refs"]["elements"] == ["bo-referral"]


def test_a_missing_capability_need_not_name_an_element():
    """'missing' = needed, and nothing in the model realises it yet: the capability is the subject."""
    env = _build(references={"capabilities": [_cap(element_id="", status="missing")]})
    assert len(env["references"]["capabilities"]) == 1 and env["open_questions"] == []
