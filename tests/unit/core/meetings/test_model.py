"""`lab.core.meetings.model` — the ONE home for what a speaker is.

This invariant used to exist twice, here and in `lab.platform.contracts`, on the argument that a
domain type could not be reached from the platform tier. It can (`contracts` already imports
`ContentHandle` from `lab.core.collab`), the platform copy had no production caller, and two homes
for one rule is how two rules drift. These are the assertions that came back with it.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/core/meetings/test_model.py
"""
import pytest

from lab.core.meetings.model import Speaker, Speakers


def test_a_speaker_is_a_directory_identity_or_a_free_tag_never_both():
    """The human's decision: a directory identity, else a free tag, because not everyone in the room
    is in the directory — and pretending otherwise would either lose the external participants or
    invent identities for them. Both at once is ambiguous and is refused; neither is unanswered."""
    assert Speaker("SPEAKER_00", identity="maria@contoso.com").identity
    assert Speaker("SPEAKER_01", tag="the vendor's architect").tag
    with pytest.raises(ValueError):
        Speaker("SPEAKER_00", identity="a@b.com", tag="also this")
    with pytest.raises(ValueError):
        Speaker("SPEAKER_00")


def test_a_speaker_needs_the_label_it_answers_for():
    with pytest.raises(ValueError):
        Speaker("   ", tag="someone")


def test_display_never_exposes_a_raw_address():
    """The transcript the minutes agent reads carries display names only. The gateway's guardrail
    pseudonymises addresses, so a transcript full of them reaches the model as placeholders and
    degrades silently the moment the model paraphrases one instead of repeating it verbatim."""
    assert "@" not in Speaker("SPEAKER_00", identity="maria.perez@contoso.com").display
    assert Speaker("SPEAKER_00", identity="maria.perez@contoso.com").display == "maria.perez"
    assert Speaker("SPEAKER_01", tag="the vendor's architect").display == "the vendor's architect"


def test_the_wire_shape_a_human_s_answer_arrives_in_is_accepted_in_one_place():
    """`from_answer` is the edge. Nothing else in the domain needs to know the answer travelled
    through an approval."""
    got = Speakers.from_answer({"SPEAKER_00": {"identity": "a@b.com"}, "SPEAKER_01": {"tag": "guest"}})
    assert got == Speakers((Speaker("SPEAKER_00", identity="a@b.com"),
                            Speaker("SPEAKER_01", tag="guest")))
    assert got.of("SPEAKER_01").tag == "guest"


def test_asking_for_an_unmapped_label_names_it():
    """An unattributed speaker must fail loudly here rather than reach the minutes as SPEAKER_03."""
    with pytest.raises(KeyError) as e:
        Speakers((Speaker("SPEAKER_00", tag="x"),)).of("SPEAKER_09")
    assert "SPEAKER_09" in str(e.value)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
