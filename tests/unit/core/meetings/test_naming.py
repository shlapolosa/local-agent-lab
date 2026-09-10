"""What a PERSON receives — `lab.core.meetings.naming`.

An anonymous label is a MODEL-INTERNAL key. The minutes schema tells the model "Labels only; who
they are is the human's answer, not yours", the gate validates what it wrote against those labels,
and the prose it reads must therefore show them — all correct, and all invisible to whoever asked
for the minutes.

Measured live 9 Sep 2026 on the 18:26 recording, after a human had tagged every speaker: the file
delivered into the meeting's own folder read `SPEAKER_01 (socrateshlapolosa): …` and the summary
narrative read "speaker_0 opened the meeting by setting out its purpose". The tagging worked; the
naming never happened. The whole point of asking a person who is speaking is that what comes back
says who — so the label is translated AT THE EDGE, on the way out, and nowhere else.

The audit artifacts keep their labels deliberately: they are what the gate validated and what the
graph is keyed on. This module builds the SECOND rendering, the one people read.
"""
import pytest

from lab.core.meetings import Speakers, named_minutes, transcript_for_people

MAP = Speakers.from_answer({
    "SPEAKER_00": {"identity": "maria.rossi@contoso.com"},
    "SPEAKER_01": {"tag": "a vendor engineer"},
})
SEGMENTS = [
    {"speaker": "SPEAKER_00", "text": "Morning all."},
    {"speaker": "SPEAKER_00", "text": "Let's start with the open items."},
    {"speaker": "SPEAKER_01", "text": "Two are still with us."},
    {"speaker": "SPEAKER_00", "text": "Then we close them this week."},
]


# ------------------------------------------------------------------ the transcript
def test_the_delivered_transcript_names_the_person_and_never_the_label():
    out = transcript_for_people(SEGMENTS, MAP)
    assert "SPEAKER_" not in out, out
    assert out.startswith("maria.rossi:")
    assert "a vendor engineer: Two are still with us." in out


def test_consecutive_turns_by_one_person_become_one_paragraph():
    """A diarizer breaks a turn whenever it hears a pause. Those breaks are an artefact of the
    ANALYSIS, not of the conversation, and preserving them gives a reader the same sentence chopped
    into pieces with the speaker's name repeated over each."""
    out = transcript_for_people(SEGMENTS, MAP).splitlines()
    assert len(out) == 3, out
    assert out[0] == "maria.rossi: Morning all. Let's start with the open items."


def test_two_labels_that_are_the_SAME_person_read_as_one_voice():
    """The case that made this obvious: a diarizer split one speaker in two, a human tagged both as
    themselves, and the delivered transcript still read as a dialogue between SPEAKER_00 and
    SPEAKER_01 — a conversation that never happened."""
    same = Speakers.from_answer({"SPEAKER_00": {"identity": "sam@contoso.com"},
                                 "SPEAKER_01": {"identity": "sam@contoso.com"}})
    segments = [{"speaker": "SPEAKER_00", "text": "Kayf halak?"},
                {"speaker": "SPEAKER_01", "text": "Alhamdulillah."}]
    assert transcript_for_people(segments, same) == "sam: Kayf halak? Alhamdulillah."


def test_a_silent_segment_is_not_a_turn():
    """A diarizer attributes breaths and keyboards. They carry no words, so they are not speech and
    must not open a paragraph under somebody's name."""
    segments = [{"speaker": "SPEAKER_00", "text": "Morning."},
                {"speaker": "SPEAKER_01", "text": "   "},
                {"speaker": "SPEAKER_00", "text": "Shall we start?"}]
    assert transcript_for_people(segments, MAP) == "maria.rossi: Morning. Shall we start?"


def test_an_empty_transcript_is_empty_not_a_crash():
    assert transcript_for_people([], MAP) == ""


# ------------------------------------------------------------------ the minutes
MINUTES = {
    "summary": "SPEAKER_00 opened the meeting; SPEAKER_01 raised the migration risk and "
               "SPEAKER_00 agreed to answer it.",
    "concepts": [{"id": "c1", "label": "open items"}],
    "decisions": [{"id": "d1", "statement": "close the items this week",
                   "decided_by": ["SPEAKER_00", "SPEAKER_01"], "concerns": ["c1"],
                   "evidence": [{"speaker": "SPEAKER_00", "quote": "we close them this week"}]}],
    "actions": [{"id": "a1", "commitment": "send the list", "owner": "SPEAKER_01",
                 "concerns": ["c1"]}],
    "keywords": ["open items"],
}


def test_every_label_in_the_minutes_becomes_the_person_who_said_it():
    out = named_minutes(MINUTES, MAP)
    assert out["decisions"][0]["decided_by"] == ["maria.rossi", "a vendor engineer"]
    assert out["actions"][0]["owner"] == "a vendor engineer"
    assert out["decisions"][0]["evidence"][0]["speaker"] == "maria.rossi"


def test_the_summary_a_person_reads_names_people_not_labels():
    """The narrative is free text the model wrote, and it is the part anybody actually reads."""
    out = named_minutes(MINUTES, MAP)
    assert "SPEAKER_" not in out["summary"]
    assert out["summary"].startswith("maria.rossi opened the meeting")
    assert "a vendor engineer raised the migration risk" in out["summary"]


def test_one_person_behind_two_labels_is_named_once_not_twice():
    """`decided_by` is a set of people, not of labels: naming the same person twice reads as two
    people agreeing with each other."""
    same = Speakers.from_answer({"SPEAKER_00": {"identity": "sam@contoso.com"},
                                 "SPEAKER_01": {"identity": "sam@contoso.com"}})
    out = named_minutes(MINUTES, same)
    assert out["decisions"][0]["decided_by"] == ["sam"]


def test_a_longer_label_is_not_corrupted_by_a_shorter_one_inside_it():
    """`speaker_0` is a prefix of `speaker_01`, so a naive replace turns the latter into
    '<name>1'. Longest-first is the whole reason this is a function and not a loop at the call
    site."""
    tricky = Speakers.from_answer({"speaker_0": {"tag": "the chair"},
                                   "speaker_01": {"tag": "the auditor"}})
    m = {"summary": "speaker_01 asked and speaker_0 answered.", "concepts": [],
         "decisions": [], "actions": [], "keywords": []}
    assert named_minutes(m, tricky)["summary"] == "the auditor asked and the chair answered."


def test_the_original_minutes_are_left_untouched():
    """The labelled minutes are the audit artifact and what the graph is keyed on. Naming builds a
    SECOND rendering; it must not quietly rewrite the first."""
    before = MINUTES["actions"][0]["owner"]
    named_minutes(MINUTES, MAP)
    assert MINUTES["actions"][0]["owner"] == before
    assert MINUTES["summary"].startswith("SPEAKER_00")


def test_a_label_nobody_identified_is_left_alone_rather_than_guessed():
    """The gate already refuses minutes naming a label the transcript does not use, so this cannot
    normally happen. If it ever does, presentation is the wrong place to fail: a reader is better
    served by one un-named label than by no minutes at all."""
    m = {"summary": "SPEAKER_09 said something.", "concepts": [], "decisions": [],
         "actions": [{"id": "a1", "commitment": "x", "owner": "SPEAKER_09", "concerns": []}],
         "keywords": []}
    out = named_minutes(m, MAP)
    assert out["summary"] == "SPEAKER_09 said something."
    assert out["actions"][0]["owner"] == "SPEAKER_09"


@pytest.mark.parametrize("bad", [None, {}, {"summary": ""}])
def test_it_survives_minutes_that_are_missing_the_parts_it_names(bad):
    assert isinstance(named_minutes(bad, MAP), dict)


def test_a_label_in_free_text_the_schema_never_named_is_still_replaced():
    """The leak the first version shipped with, measured live 9 Sep 2026 on two of three lanes.

    The schema puts a speaker label in exactly three places, so the first `named_minutes` handled
    those plus `summary`. The model writes PROSE wherever the schema allows prose, and in that prose
    it refers to speakers by the only name it was ever given — so `concepts[].definition` came back
    reading "The outstanding items being tracked from previous work; speaker_0 recalled only two
    remained", in a delivered file, after a human had said who speaker_0 was.

    The rule is about the LABEL, not about the field it happens to sit in.
    """
    m = {"summary": "SPEAKER_00 opened.",
         "concepts": [{"id": "c1", "label": "open items",
                       "definition": "Items being tracked; SPEAKER_00 recalled only two remained.",
                       "evidence": [{"speaker": "SPEAKER_00", "quote": "two left"}]}],
         "decisions": [{"id": "d1", "statement": "SPEAKER_01 will close them", "decided_by": [],
                        "concerns": ["c1"]}],
         "actions": [{"id": "a1", "commitment": "SPEAKER_01 sends the list", "owner": "SPEAKER_01",
                      "concerns": ["c1"]}],
         "keywords": ["open items"]}
    out = named_minutes(m, MAP)

    import json
    assert "SPEAKER_" not in json.dumps(out), "a label survived somewhere in the delivered minutes"
    assert out["concepts"][0]["definition"].startswith("Items being tracked; maria.rossi recalled")
    assert out["decisions"][0]["statement"] == "a vendor engineer will close them"
    assert out["actions"][0]["commitment"] == "a vendor engineer sends the list"
    # ...and the parts that are not speakers are untouched
    assert out["concepts"][0]["label"] == "open items" and out["keywords"] == ["open items"]


def test_nothing_that_merely_looks_structural_is_rewritten():
    """Substituting everywhere must not mean substituting anything else. Only the exact labels a
    human answered for are replaced — ids, concept labels and quoted words stay as they were."""
    m = {"summary": "SPEAKER_00 spoke about SPEAKER training and c1.",
         "concepts": [{"id": "SPEAKER_00_c1", "label": "SPEAKER training"}],
         "decisions": [], "actions": [], "keywords": ["SPEAKER"]}
    out = named_minutes(m, MAP)
    assert out["summary"] == "maria.rossi spoke about SPEAKER training and c1."
    assert out["concepts"][0]["label"] == "SPEAKER training"   # not a label anybody answered for
    assert out["keywords"] == ["SPEAKER"]
    assert out["concepts"][0]["id"] == "maria.rossi_c1"        # it DOES contain one, honestly
