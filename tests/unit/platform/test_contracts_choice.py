"""`InputKind.CHOICE` — one value from a CLOSED set, and the speech-provider vocabulary it carries.

Why a new kind rather than reusing something: running four providers in their own lanes means a run
must SAY which lane it is, and that value is neither content, nor a reference, nor an identity, nor
a human's answer. The alternative was a free-text field, which is the one thing this contract has
deliberately never had — "it would admit a URL, a whole document or an injected prompt into a
contract whose entire discipline is by-reference". A closed set admits none of those: a value is
either in the list or the run is refused, and the list is the lab's own.
"""
import pytest

from lab.platform import contracts as C


def test_a_choice_accepts_only_a_declared_member():
    f = C.InputField("provider", C.InputKind.CHOICE, "which lane", required=False,
                     choices=("munsit", "elevenlabs"))
    assert f.coerce("munsit") == "munsit"
    assert f.coerce(" ElevenLabs ") == "elevenlabs"        # trimmed and case-folded, like an alias
    with pytest.raises(ValueError, match="provider"):
        f.coerce("whisper")


def test_the_refusal_names_what_would_have_been_accepted():
    """A closed set is only usable if a caller can see what the members are."""
    f = C.InputField("provider", C.InputKind.CHOICE, "which lane", choices=("a", "b"))
    with pytest.raises(ValueError, match=r"a.*b"):
        f.coerce("c")


def test_a_choice_refuses_anything_that_is_not_one_scalar_value():
    f = C.InputField("provider", C.InputKind.CHOICE, "which lane", choices=("a",))
    for bad in (["a"], {"provider": "a"}, 1, True):
        with pytest.raises(ValueError):
            f.coerce(bad)


def test_a_choice_field_must_declare_its_choices_or_it_is_not_closed():
    """An empty set would accept nothing and read as a mistake; a missing one would accept anything,
    which is the free-text field this kind exists to avoid."""
    with pytest.raises(ValueError):
        C.InputField("provider", C.InputKind.CHOICE, "which lane")


def test_an_optional_choice_left_out_stays_out():
    f = C.InputField("provider", C.InputKind.CHOICE, "which lane", required=False, choices=("a",))
    assert f.coerce(None) is None and f.coerce("") is None


# ------------------------------------------------------------------ the vocabulary itself
def test_both_meeting_processes_carry_the_lane_and_it_is_optional():
    """Optional deliberately: a deployment running ONE provider submits exactly as it does today,
    and an absent lane means 'this deployment's configured provider'."""
    for spec in (C.MEETING_TO_TRANSCRIPT, C.TRANSCRIPT_TO_MINUTES):
        field = {f.name: f for f in spec.inputs}["provider"]
        assert field.kind is C.InputKind.CHOICE and field.required is False
        assert set(field.choices) == set(C.SPEECH_PROVIDERS)
        assert spec.validate(_minimal(spec)) == _minimal(spec)          # still valid without it


def test_a_lane_that_is_not_a_known_provider_is_refused_at_submit():
    values = {**_minimal(C.MEETING_TO_TRANSCRIPT), "provider": "not-a-provider"}
    with pytest.raises(ValueError, match="provider"):
        C.MEETING_TO_TRANSCRIPT.validate(values)


def test_the_vocabulary_is_not_empty_and_names_no_credential():
    assert C.SPEECH_PROVIDERS and all(p == p.lower().strip() for p in C.SPEECH_PROVIDERS)


def _minimal(spec) -> dict:
    return {f.name: _example(f) for f in spec.inputs if f.required}


def _example(f):
    return {C.InputKind.REF: "art://abc123/x.json",
            C.InputKind.HANDLE: "collab://recording/scope/id",
            C.InputKind.IDENTITY: "maria@contoso.com",
            C.InputKind.MAPPING: {"SPEAKER_00": {"identity": "maria@contoso.com"}},
            C.InputKind.CONVERSATION: "19:meeting_abc@thread.v2",
            C.InputKind.REF_LIST: ["art://abc123/x.json"]}[f.kind]
