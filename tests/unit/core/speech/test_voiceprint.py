"""src/lab/core/speech/voiceprint.py — recognising a voice the lab has met before, as pure rules.

The numbers these tests lean on (0.40, 0.25, 3 s, 5 s) were MEASURED on 29 Sep 2026 against a real
three-person meeting; see docs/speech-voiceprint-gallery.md. The vectors below are tiny and hand-made
so each rule is visible: `A`, `B` and `C` are three orthogonal "voices".
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/core/speech/test_voiceprint.py"""
import math

import pytest

from lab.core.meetings.model import Speakers
from lab.core.speech import voiceprint as V

A, B, C = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)


def near(v, other, t=0.1):
    """`v` nudged towards `other` — the same voice on a different day."""
    return V.unit(tuple(x + t * y for x, y in zip(v, other)))


def vp(kind, key, vector, model="m1", consented_by="organiser@lab.example"):
    return V.Voiceprint(kind=kind, key=key, vector=vector, model=model, consented_by=consented_by)


GALLERY = [vp("identity", "chair@lab.example", A), vp("tag", "Nabeel", B)]


# ------------------------------------------------------------------ the stored thing
def test_a_voiceprint_must_record_who_attested_consent():
    """Every stored voiceprint answers "who said this person agreed" — it is the audit trail for
    biometric data, so a row without it is refused rather than stored."""
    with pytest.raises(ValueError, match="consent"):
        vp("identity", "chair@lab.example", A, consented_by="")


def test_a_voiceprint_is_keyed_by_an_identity_or_a_tag_and_nothing_else():
    with pytest.raises(ValueError, match="identity|tag"):
        vp("email", "chair@lab.example", A)
    with pytest.raises(ValueError, match="key"):
        vp("tag", "  ", A)


def test_a_voiceprint_holds_a_normalised_vector_and_the_model_that_made_it():
    got = vp("tag", "Nabeel", (3.0, 4.0, 0.0))
    assert math.isclose(sum(x * x for x in got.vector), 1.0)
    with pytest.raises(ValueError, match="model"):
        vp("tag", "Nabeel", A, model="")


# ------------------------------------------------------------------ purity
def test_purify_drops_a_segment_that_does_not_sound_like_the_rest_of_its_label():
    """Measured: a diarizer label can mix people. Pooling the whole label would give one person
    another's voice, so the odd one out is dropped before anything is matched or stored."""
    kept = V.purify([(A, 4.0), (near(A, B), 4.0), (C, 3.0)])
    assert [s for _, s in kept] == [4.0, 4.0]


def test_purify_leaves_a_single_segment_alone_because_there_is_nothing_to_compare_it_with():
    assert V.purify([(A, 4.0)]) == [(A, 4.0)]


# ------------------------------------------------------------------ identify
def test_a_known_voice_is_suggested_with_its_score():
    got = V.identify({"SPEAKER_01": [(near(A, C), 6.0)]}, GALLERY)["SPEAKER_01"]
    assert (got.kind, got.key) == ("identity", "chair@lab.example")
    assert got.score >= V.THRESHOLD


def test_an_unknown_voice_gets_no_suggestion_rather_than_the_nearest_person():
    """The measured failure to avoid is a confident WRONG name. Below the threshold the card is
    left empty and the human answers, exactly as before this feature existed."""
    assert V.identify({"SPEAKER_02": [(C, 8.0)]}, GALLERY)["SPEAKER_02"] is None


def test_too_little_speech_gets_no_suggestion_however_well_it_matches():
    got = V.identify({"SPEAKER_03": [(A, 1.2), (A, 1.0)]}, GALLERY)
    assert got["SPEAKER_03"] is None


def test_voiceprints_from_another_model_are_never_compared():
    """A vector compares only with vectors from the same model; mixing them yields numbers that
    look like scores and mean nothing."""
    assert V.identify({"S": [(A, 6.0)]}, [vp("identity", "chair@lab.example", A, model="old")],
                      model="m1")["S"] is None


def test_a_person_with_several_voiceprints_is_matched_on_their_average():
    gallery = [vp("tag", "Ahmed", near(C, A, 0.3)), vp("tag", "Ahmed", near(C, B, 0.3))]
    assert V.identify({"S": [(C, 6.0)]}, gallery)["S"].key == "Ahmed"


def test_every_label_is_answered_even_when_the_gallery_is_empty():
    assert V.identify({"S1": [(A, 6.0)], "S2": [(B, 6.0)]}, []) == {"S1": None, "S2": None}


def test_a_suggestion_renders_in_the_answer_shape_a_card_prefills():
    s = V.identify({"S": [(near(B, A), 6.0)]}, GALLERY)["S"]
    d = s.to_dict()
    assert d["tag"] == "Nabeel" and "identity" not in d and d["display"] == "Nabeel"
    assert 0 < d["score"] <= 1


# ------------------------------------------------------------------ enrol policy
def speakers(**answers):
    return Speakers.from_answer(answers)


def test_an_unmatched_voice_the_organiser_names_WITH_consent_is_enrolled():
    got = V.to_enrol(speakers(S1={"tag": "Ahmed", "consent": "yes"}), {"S1": None})
    assert got == {"S1": ("tag", "Ahmed")}


def test_without_the_consent_tick_nothing_is_stored():
    assert V.to_enrol(speakers(S1={"tag": "Ahmed"}), {"S1": None}) == {}


def test_a_confirmed_match_is_not_re_enrolled():
    """The user's rule: voiceprints grow from what the gallery did NOT already know."""
    s = V.Suggestion(kind="identity", key="chair@lab.example", score=0.6)
    got = V.to_enrol(speakers(S1={"identity": "Chair@Lab.example", "consent": "yes"}), {"S1": s})
    assert got == {}


def test_a_wrong_suggestion_the_organiser_corrects_is_enrolled_under_the_corrected_name():
    s = V.Suggestion(kind="tag", key="Nabeel", score=0.45)
    got = V.to_enrol(speakers(S1={"tag": "Ahmed", "consent": "yes"}), {"S1": s})
    assert got == {"S1": ("tag", "Ahmed")}


def test_an_identity_is_stored_lower_cased_so_one_person_is_one_key():
    got = V.to_enrol(speakers(S1={"identity": "Chair@Lab.Example", "consent": "yes"}), {"S1": None})
    assert got == {"S1": ("identity", "chair@lab.example")}


def test_enrol_builds_one_voiceprint_from_the_purified_label_and_refuses_too_little_speech():
    made = V.enrolment("tag", "Ahmed", [(C, 3.0), (near(C, A), 3.0), (A, 2.0)], model="m1",
                       source="apr-1", consented_by="organiser@lab.example")
    assert made.key == "Ahmed" and made.seconds == 6.0 and made.source == "apr-1"
    assert V.enrolment("tag", "Ahmed", [(C, 2.0), (C, 2.0)], model="m1", source="apr-1",
                       consented_by="organiser@lab.example") is None
