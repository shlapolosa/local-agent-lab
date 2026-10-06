"""lab.substrate.meetingapp.answers — the organiser's card submission, as the gate's answer.

The SAME wire shape the review app and the Power Automate card produce, so `Speakers.from_answer`
reads one answer whichever surface it came from: a typed identity beats a pick, a tag is free text,
and consent is an explicit "yes" or it is no.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/meetingapp/test_answers.py"""
from lab.core.meetings.model import Speakers
from lab.substrate.meetingapp import answers

LABELS = ("SPEAKER_00", "SPEAKER_01")


def test_the_card_data_becomes_one_entry_per_label():
    data = {"approval_id": "apr-1", "identity_SPEAKER_00": " maria@contoso.com ", "consent_SPEAKER_00": "yes",
            "tag_SPEAKER_01": "TV in the room"}
    got = answers.from_card(data, LABELS)
    assert got == {"SPEAKER_00": {"identity": "maria@contoso.com", "consent": "yes"},
                   "SPEAKER_01": {"tag": "TV in the room", "consent": "no"}}
    speakers = Speakers.from_answer(got)
    assert speakers.of("SPEAKER_00").consent and not speakers.of("SPEAKER_01").consent


def test_a_typed_identity_beats_a_picked_one():
    got = answers.from_card({"pick_SPEAKER_00": "a@x.com", "identity_SPEAKER_00": "b@x.com"}, LABELS[:1])
    assert got["SPEAKER_00"]["identity"] == "b@x.com"
    got = answers.from_card({"pick_SPEAKER_00": "a@x.com"}, LABELS[:1])
    assert got["SPEAKER_00"]["identity"] == "a@x.com"


def test_unanswered_labels_are_reported_so_the_card_can_say_which():
    missing = answers.unanswered(answers.from_card({"identity_SPEAKER_00": "m@x.com"}, LABELS))
    assert missing == ["SPEAKER_01"]


def test_consent_is_anything_but_an_explicit_yes_is_no():
    for value in ("", "false", "on", "true-ish", None):
        assert answers.from_card({"consent_SPEAKER_00": value, "tag_SPEAKER_00": "x"}, LABELS[:1])[
            "SPEAKER_00"]["consent"] == "no"


def test_the_answer_passes_the_minutes_process_own_input_contract():
    """Measured 6 Oct 2026: the card sent BOTH fields, one empty, and the minutes process refused it —
    `speaker_map[SPEAKER_01].tag must be a non-empty string` — after the approval was already recorded,
    so the organiser's answer produced no minutes. The answer is checked against the real contract."""
    from lab.platform.contracts import TRANSCRIPT_TO_MINUTES
    answer = answers.from_card({"identity_SPEAKER_00": "m@x.com", "consent_SPEAKER_00": "yes",
                                "tag_SPEAKER_01": "TV"}, LABELS)
    TRANSCRIPT_TO_MINUTES.validate({"transcript": "art://t/x.json", "speaker_map": answer})
