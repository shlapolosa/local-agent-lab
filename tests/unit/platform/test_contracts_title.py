"""InputKind.TITLE — the one piece of free text a run may carry: what people call the thing.

An opted-in meeting is otherwise known only by ids, so its minutes were "Meeting.<lane>.minutes.txt"
and nobody could find them by the meeting's name. A title is a LABEL, so it is held to what a label is:
one line, short, never a link. A caller holding a longer one clips it (`fit_title`) rather than losing
the run over a name.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/platform/test_contracts_title.py"""
import pytest

from lab.platform import contracts as C

FIELD = C.InputField("title", C.InputKind.TITLE, "what the meeting is called", required=False)


def test_a_title_is_one_line_with_its_whitespace_collapsed():
    assert FIELD.coerce("  Weekly\n sync \t— portal  ") == "Weekly sync — portal"


def test_a_title_in_any_script_is_kept_as_written():
    assert FIELD.coerce("اجتماع المشروع") == "اجتماع المشروع"


@pytest.mark.parametrize("bad", ["see https://evil.example/x", "x" * (C.MAX_TITLE_CHARS + 1), "\x00\x07", 42])
def test_a_link_an_essay_or_a_non_string_is_refused(bad):
    with pytest.raises(ValueError, match="title"):
        FIELD.coerce(bad)


def test_fit_title_clips_what_the_contract_would_refuse_and_drops_what_it_cannot_fix():
    assert len(C.fit_title("word " * 100)) <= C.MAX_TITLE_CHARS
    assert C.fit_title("Sync with https://x.example") == ""
    assert C.fit_title(None) == "" and C.fit_title("  ") == ""
    assert FIELD.coerce(C.fit_title("word " * 100))


@pytest.mark.parametrize("spec", [C.MEETING_TO_TRANSCRIPT, C.TRANSCRIPT_TO_MINUTES])
def test_both_meeting_processes_take_an_optional_title(spec):
    field = next(f for f in spec.inputs if f.name == "title")
    assert field.kind is C.InputKind.TITLE and not field.required
