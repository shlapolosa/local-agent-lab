"""lab.substrate.meetingapp.cards — what the meeting app shows in a meeting chat, as pure data.

One card, two audiences. Everyone in the meeting chat sees the NEUTRAL card ("awaiting the
organiser"); only the organiser's client refreshes it into the speaker form, because what a voice
said is the organiser's to see before it is anyone's. Measured 5 Oct 2026: Teams matches the refresh
list against the user's Teams id (29:…), never the directory object id, so the card carries that.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/meetingapp/test_cards.py"""
import json

from lab.platform.contracts import SpeakerPrompt
from lab.substrate.meetingapp import cards

ORGANISER_MRI = "29:1faB-organiser"
PROMPTS = [SpeakerPrompt("SPEAKER_00", ("shall we start with the portal", "agreed"), 61.5, 4,
                         {"identity": "maria@contoso.com", "display": "Maria", "score": 0.62}),
           SpeakerPrompt("SPEAKER_01", ("نبدأ بالبوابة",), 12.0, 1)]


def flat(card) -> str:
    return json.dumps(card, ensure_ascii=False)


def test_the_neutral_card_refreshes_only_for_the_organiser_and_shows_no_speech():
    card = cards.awaiting("apr-1", ORGANISER_MRI, speakers=2, lane="soniox-en")
    assert card["refresh"]["userIds"] == [ORGANISER_MRI]
    assert card["refresh"]["action"]["data"] == {"approval_id": "apr-1"}
    assert "portal" not in flat(card) and "نبدأ" not in flat(card), "no utterance before the organiser sees it"
    assert "soniox-en" in flat(card), "several lanes post several cards; each must say which it is"


def test_the_organiser_form_has_a_row_per_speaker_with_samples_prefill_and_consent():
    card = cards.speaker_form("apr-1", PROMPTS, ORGANISER_MRI)
    ids = [e["id"] for e in _inputs(card)]
    for label in ("SPEAKER_00", "SPEAKER_01"):
        assert {f"identity_{label}", f"tag_{label}", f"consent_{label}"} <= set(ids)
    assert "shall we start with the portal" in flat(card) and "نبدأ بالبوابة" in flat(card)
    prefilled = next(e for e in _inputs(card) if e["id"] == "identity_SPEAKER_00")
    assert prefilled.get("value") == "maria@contoso.com", "a matched voice is a suggestion, pre-filled"
    assert "value" not in next(e for e in _inputs(card) if e["id"] == "identity_SPEAKER_01")
    consent = next(e for e in _inputs(card) if e["id"] == "consent_SPEAKER_00")
    assert consent["type"] == "Input.Toggle" and consent["valueOn"] == "yes" and consent.get("value") != "yes", \
        "consent is never pre-ticked — it is the person's to give"
    submit = card["actions"][0]
    assert submit["type"] == "Action.Execute" and submit["verb"] == "submit"
    assert submit["data"] == {"approval_id": "apr-1"}
    assert card["refresh"]["userIds"] == [ORGANISER_MRI], "it must stay the organiser's on every re-render"


def test_a_tag_suggestion_prefills_the_tag_not_the_identity():
    card = cards.speaker_form("apr-1", [SpeakerPrompt("SPEAKER_00", ("hi",), 5.0, 1, {"tag": "TV"})], ORGANISER_MRI)
    assert next(e for e in _inputs(card) if e["id"] == "tag_SPEAKER_00").get("value") == "TV"


def test_the_recorded_card_says_who_answered_and_drops_the_refresh():
    card = cards.recorded("Maria Perez")
    assert "Maria Perez" in flat(card) and "refresh" not in card and "actions" not in card


def test_the_minutes_card_lists_summary_and_counts_and_names_each_file():
    card = cards.minutes(summary="We agreed to start with the portal.", decisions=1, actions=2,
                         files=["Meeting.soniox-en.transcript.txt", "Meeting.soniox-en.minutes.txt"],
                         lane="soniox-en")
    text = flat(card)
    assert "We agreed to start with the portal." in text and "Meeting.soniox-en.minutes.txt" in text
    assert "1" in text and "2" in text


def test_the_welcome_card_says_what_is_processed_and_that_voice_is_kept_only_on_consent():
    text = flat(cards.welcome()).lower()
    assert "after the meeting" in text and "record" in text and "consent" in text


def _inputs(card):
    out = []

    def walk(node):
        if isinstance(node, dict):
            if str(node.get("type", "")).startswith("Input."):
                out.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(card)
    return out
