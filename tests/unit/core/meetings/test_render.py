"""src/lab/core/meetings/render.py + the reference scoring in lab.core.speech.compare.

What a person receives is plain text in Teams' own layout, and every lane is scored against Teams'
transcript. Fixtures are SYNTHETIC: this repository is public, and a real meeting's words do not
belong in it.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/core/meetings/test_render.py"""
from lab.core.meetings import render as R
from lab.core.meetings.model import Speakers
from lab.core.meetings.naming import Turn, turns
from lab.core.speech import compare as C

SEGMENTS = [{"speaker": "S1", "start": 3.4, "end": 6.0, "text": "Shall we start with the portal"},
            {"speaker": "S1", "start": 6.2, "end": 8.0, "text": "and then the budget?"},
            {"speaker": "S2", "start": 9.0, "end": 9.5, "text": ""},
            {"speaker": "S2", "start": 75.0, "end": 80.0, "text": "الاتفاق إنه نبدأ بالبوابة"}]
PEOPLE = Speakers.from_answer({"S1": {"identity": "maria@contoso.com"}, "S2": {"tag": "Nabeel"}})


# ------------------------------------------------------------------ the transcript, Teams' layout
def test_turns_merge_one_person_s_consecutive_segments_and_drop_silence():
    got = turns(SEGMENTS, PEOPLE)
    assert got == [Turn("maria", 3.4, "Shall we start with the portal and then the budget?"),
                   Turn("Nabeel", 75.0, "الاتفاق إنه نبدأ بالبوابة")]


def test_the_transcript_reads_like_the_one_teams_lets_you_download():
    text = R.transcript(turns(SEGMENTS, PEOPLE), title="Weekly sync", when="2026-09-29T07:20:44Z",
                        seconds=128, lane="soniox")
    assert text.startswith("Weekly sync\n29 September 2026, 07:20 UTC\n2m 8s\nTranscription: soniox\n\n")
    assert "maria   0:03\nShall we start with the portal and then the budget?\n\nNabeel   1:15\n" in text


def test_reading_a_delivered_transcript_gives_back_its_turns():
    """The comparison scores what a person was GIVEN, so the reader must invert the writer exactly."""
    original = turns(SEGMENTS, PEOPLE)
    back = R.read_transcript(R.transcript(original, title="t", seconds=80))
    assert [(t.name, t.text) for t in back] == [(t.name, t.text) for t in original]
    assert [t.start for t in back] == [3.0, 75.0]


def test_a_delivered_file_s_utf8_mark_does_not_disturb_reading_it_back():
    text = "\ufeff" + R.transcript(turns(SEGMENTS, PEOPLE), title="t", seconds=80)
    assert [t.name for t in R.read_transcript(text)] == ["maria", "Nabeel"]


def test_clock_and_length_use_teams_units():
    assert (R.clock(3.9), R.clock(754), R.clock(3723)) == ("0:03", "12:34", "1:02:03")
    assert (R.length(45), R.length(128), R.length(3785)) == ("45s", "2m 8s", "1h 3m 5s")
    assert R.stamp("not a date") == ""


# ------------------------------------------------------------------ the minutes
def test_minutes_read_top_to_bottom_and_an_empty_section_says_so():
    text = R.minutes({"summary": "We agreed the order of work.",
                      "decisions": [{"statement": "Start with the portal", "decided_by": ["maria", "Nabeel"],
                                     "confidence": "medium"}],
                      "actions": [], "concepts": [{"label": "portal", "definition": "the public site"}],
                      "keywords": ["portal", "budget"]},
                     title="Weekly sync", when="2026-09-29T07:20:44Z", lane="soniox", people=["maria", "Nabeel"])
    assert text.startswith("Weekly sync — Minutes\n29 September 2026, 07:20 UTC · Transcription: soniox\n")
    assert "Speakers: maria, Nabeel" in text
    assert "1. Start with the portal\n   Decided by: maria, Nabeel · confidence: medium" in text
    assert "ACTION ITEMS\nNone recorded." in text
    assert "- portal: the public site" in text and "KEYWORDS\nportal, budget" in text


def test_an_action_shows_its_owner_and_due_date_only_when_one_was_said():
    text = R.minutes({"summary": "x", "actions": [{"commitment": "Send the plan", "owner": "maria", "due": "2026-10-09"},
                                                  {"commitment": "Book a room", "owner": "Nabeel", "due": None}]},
                     title="t")
    assert "   Owner: maria · Due: 2026-10-09" in text and "   Owner: Nabeel\n" in text


# ------------------------------------------------------------------ scoring against the tenant's transcript
VTT = """WEBVTT

00:00:03.000 --> 00:00:08.000
<v Maria Perez>Shall we start with the portal and then the budget?</v>

00:01:15.000 --> 00:01:20.000
<v Maria Perez>Okay, now</v>
"""


def test_the_tenant_s_vtt_becomes_named_segments():
    t = C.parse_vtt(VTT)
    assert [(s.speaker, s.start, s.text) for s in t.segments] == [
        ("Maria Perez", 3.0, "Shall we start with the portal and then the budget?"), ("Maria Perez", 75.0, "Okay, now")]


def test_a_lane_is_scored_on_agreement_with_teams_and_on_what_it_holds_beyond_it():
    teams = " ".join(s.text for s in C.parse_vtt(VTT).segments)               # 12 words, English only
    lane = "Shall we start with the portal and then the budget? الاتفاق إنه نبدأ بالبوابة"
    s = C.score(lane, speakers=2, reference=teams)
    assert s.reference_recall == 10 / 12, "every Teams word it has, counted once each"
    assert s.of_reference == 14 / 12 and 0 < s.arabic_share < 1 and s.speakers == 2


def test_with_no_reference_a_score_is_just_the_transcript_measured():
    s = C.score("hello there", speakers=1)
    assert (s.words, s.of_reference, s.reference_recall) == (2, None, None)


def test_the_comparison_lists_teams_first_then_every_lane_with_a_legend():
    teams = C.score("one two three four", speakers=1)
    text = R.comparison("Weekly sync", teams, {"munsit": C.score("one two", 3, "one two three four"),
                                               "soniox-en": C.score("one two three four five", 3, "one two three four")})
    lines = text.splitlines()
    assert lines[0] == "Weekly sync — transcription compared with Microsoft Teams"
    rows = [l for l in lines if l.startswith(("Microsoft Teams", "munsit", "soniox-en"))]
    assert rows[0].split()[2] == "4" and rows[1].split()[1:4] == ["2", "50%", "50%"]
    assert rows[2].split()[1:4] == ["5", "125%", "100%"]
    assert "How to read this" in text and "agreement, not accuracy" in text


def test_compare_lanes_scores_every_lane_against_the_tenant_transcript_in_one_table():
    """The one home of 'Teams VTT + each lane's transcript -> the comparison table' — the minutes run
    and the meeting app both call it, so they cannot disagree about what a comparison says."""
    vtt = "WEBVTT\n\n00:00:03.000 --> 00:00:08.000\n<v Maria Perez>Shall we start with the portal</v>\n"
    lanes = {"soniox": R.transcript([Turn("Maria", 3.0, "Shall we start with the portal")], title="M"),
             "munsit": R.transcript([Turn("Maria", 3.0, "start portal")], title="M")}
    table = R.compare_lanes(vtt, lanes, title="Meeting")
    rows = [l.split()[0] for l in table.splitlines() if l.startswith(("Microsoft", "soniox", "munsit"))]
    assert rows == ["Microsoft", "munsit", "soniox"], "Teams first, then every lane, in a stable order"


def test_compare_lanes_says_nothing_when_the_tenant_transcript_has_no_speech():
    assert R.compare_lanes("WEBVTT\n\n", {"soniox": "x"}, title="M") is None
