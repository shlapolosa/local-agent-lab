"""The ANSWER half of the human gate: asking a person a structured question and getting a structured
answer back, plus what approving one releases.

Today an approval carries a rich question outward — its payload is schema-free JSON — and nothing
comes back but approve/decline/update, an actor and a comment. That is enough to RELEASE a staged
write and not enough to ANSWER one, which is what mapping anonymous speaker labels to real people
requires. These types close that gap.

Two properties are load-bearing and are pinned hardest:

  * **The gate stays kind-agnostic.** Nothing in the lab dispatches on approval kind, and that is
    worth keeping. So completeness lives in a generic check driven by what the PAYLOAD declares, and
    the per-answer SHAPE lives in a typed object. Completeness in the gate, shape in the type.
  * **What approving releases travels on the payload, not in a registry.** A static "A is followed
    by B" edge cannot carry the run-specific reference of THIS run.

Pure data: no Redis, no I/O.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/platform/test_contracts_answers.py
"""
import pytest

from lab.platform import contracts as C


# ----------------------------------------------------------------- the question a human is asked
def test_a_speaker_prompt_carries_what_a_human_needs_to_recognise_a_voice():
    p = C.SpeakerPrompt(label="SPEAKER_00", samples=("we retire the legacy portal",), seconds=42.5,
                        turns=7)
    assert p.to_dict() == {"label": "SPEAKER_00", "samples": ["we retire the legacy portal"],
                           "seconds": 42.5, "turns": 7}
    assert C.SpeakerPrompt.from_dict(p.to_dict()) == p


def test_a_prompt_needs_a_label_because_that_is_what_the_answer_keys_on():
    with pytest.raises(ValueError):
        C.SpeakerPrompt(label="  ")


def test_speaker_prompts_is_the_one_reader_of_a_payload():
    """Every surface — the review app, a card, the approval tools — reads the question through this,
    so they cannot drift into three slightly different renderings."""
    payload = {"question": {"items": [{"label": "SPEAKER_01", "seconds": 3.0},
                                      {"label": "SPEAKER_00", "turns": 2}]}}
    got = C.speaker_prompts(payload)
    assert [p.label for p in got] == ["SPEAKER_01", "SPEAKER_00"], "declared order is preserved"
    assert got[1].turns == 2 and got[1].samples == ()


def test_a_payload_with_no_question_yields_no_prompts_rather_than_raising():
    """Most approvals are not questions. Reading one must be safe on any payload."""
    assert C.speaker_prompts({}) == [] and C.speaker_prompts({"summary": {}}) == []


# ----------------------------------------------------------------- the generic completeness gate
QUESTION = {"question": {"prompt": "Who is each speaker?",
                         "items": [{"label": "SPEAKER_00"}, {"label": "SPEAKER_01"}]},
            "answer_labels": ["SPEAKER_00", "SPEAKER_01"], "answer_required": True}


def test_a_complete_answer_is_returned_normalised():
    answer = {"SPEAKER_00": {"identity": "a@b.com"}, "SPEAKER_01": {"tag": "guest"}}
    assert C.check_answer(QUESTION, answer) == answer


def test_a_missing_label_is_refused_and_named():
    """The user chose ONE decision covering every speaker, so a partial answer is not an answer."""
    with pytest.raises(ValueError) as e:
        C.check_answer(QUESTION, {"SPEAKER_00": {"identity": "a@b.com"}})
    assert "SPEAKER_01" in str(e.value)


def test_an_unknown_label_is_refused_because_it_is_probably_a_typo():
    with pytest.raises(ValueError) as e:
        C.check_answer(QUESTION, {"SPEAKER_00": {"tag": "x"}, "SPEAKER_01": {"tag": "y"},
                                  "SPEAKER_09": {"tag": "z"}})
    assert "SPEAKER_09" in str(e.value)


def test_a_required_answer_that_is_absent_is_refused():
    with pytest.raises(ValueError):
        C.check_answer(QUESTION, None)


def test_an_approval_that_asks_nothing_accepts_no_answer():
    """Every existing approval is this case, so it must stay free of ceremony."""
    assert C.check_answer({"summary": {}}, None) is None
    assert C.check_answer({}, None) is None


def test_an_answer_to_a_question_that_was_not_asked_is_refused():
    """Otherwise a channel could smuggle arbitrary state onto any approval."""
    with pytest.raises(ValueError):
        C.check_answer({"summary": {}}, {"anything": {"tag": "x"}})


def test_the_gate_knows_nothing_about_speakers():
    """Completeness in the gate, shape in the type — so `ApprovalKind` never becomes a dispatch.

    Scans the CODE with docstrings and comments stripped, the way the vendor-name governance test
    does: the prose may (and should) explain WHY there is no dispatch; the executable statements may
    not contain one.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(C.check_answer)))
    fn = tree.body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(getattr(fn.body[0], "value", None), ast.Constant)):
        fn.body = fn.body[1:]                       # drop the docstring, keep the logic
    code = ast.unparse(ast.Module(body=fn.body, type_ignores=[])).lower()
    assert "speaker" not in code, "the generic gate must not learn what a speaker is"
    assert "kind" not in code, "nothing may dispatch on the approval kind"


# ----------------------------------------------------------------- what approving releases
def test_a_continuation_names_a_real_process_and_a_real_input():
    c = C.Continuation(process="visio_to_archimate",
                       inputs={"diagram": "art://a/b.vsdx"}, requester="maria@contoso.com")
    assert C.Continuation.from_dict(c.to_dict()) == c


def test_a_continuation_to_an_unknown_process_is_refused_at_construction():
    """A typo here would be discovered hours later, when a human approves and nothing happens."""
    with pytest.raises(ValueError):
        C.Continuation(process="not_a_process", inputs={})


def test_the_answer_binds_to_a_declared_input_of_that_process():
    with pytest.raises(ValueError) as e:
        C.Continuation(process="visio_to_archimate", inputs={}, answer_input="not_a_field")
    assert "not_a_field" in str(e.value)


def test_continuation_of_reads_a_payload_and_tolerates_its_absence():
    c = C.Continuation(process="visio_to_archimate", inputs={"diagram": "art://a/b.vsdx"})
    assert C.continuation_of({"continuation": c.to_dict()}) == c
    assert C.continuation_of({}) is None
    assert C.continuation_of({"summary": {}}) is None


def test_a_malformed_continuation_is_refused_loudly_not_ignored():
    """Silently ignoring it would mean an approved run simply never starts, with nothing to chase."""
    with pytest.raises(ValueError):
        C.continuation_of({"continuation": {"process": "nope", "inputs": {}}})


# ----------------------------------------------------------------- the new approval kind
def test_the_speaker_mapping_kind_exists_and_names_no_vendor():
    assert C.ApprovalKind.SPEAKER_MAPPING == "speaker-mapping"
    assert all(v.isascii() and "-" in v or v.isalpha() for v in (k.value for k in C.ApprovalKind))


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))


# ----------------------------------------------------------------- the input kinds a trigger needs
# A low-code flow must be able to start a run in ONE call, carrying who owns the recording and a
# reference to it. Neither is an art:// ref, and the existing kinds are art:// refs by construction.
def _f(kind, required=True):
    return C.InputField("field", kind, "prose an agent reads", required=required)


def test_a_provider_handle_is_accepted_and_a_url_is_not():
    """A handle carries IDS ONLY. A pre-signed download URL in an input would leak into a log, a
    trace and an agent's context, and would be stale by the time anything used it."""
    h = "collab://item/drive-1/item-9"
    assert _f(C.InputKind.HANDLE).coerce(h) == h
    for bad in ("https://example.com/file.mp4", "art://a/b.mp4", "/tmp/x.mp4", "collab://nope"):
        with pytest.raises(ValueError):
            _f(C.InputKind.HANDLE).coerce(bad)


def test_an_identity_is_a_principal_not_a_display_name():
    """This is WHO the question gets asked of, so the run cannot complete without a resolvable one."""
    assert _f(C.InputKind.IDENTITY).coerce(" maria@contoso.com ") == "maria@contoso.com"
    assert _f(C.InputKind.IDENTITY).coerce("0f8fad5b-d9cb-469f-a165-70867728950e")
    for bad in ("Maria Perez", "", "https://contoso.com", "maria at contoso"):
        with pytest.raises(ValueError):
            _f(C.InputKind.IDENTITY).coerce(bad)


def test_a_mapping_carries_a_humans_answer_into_the_next_run():
    m = {"SPEAKER_00": {"identity": "a@b.com"}, "SPEAKER_01": {"tag": "guest"}}
    assert _f(C.InputKind.MAPPING).coerce(m) == m


def test_a_mapping_is_bounded_so_it_cannot_become_a_smuggling_channel():
    with pytest.raises(ValueError):
        _f(C.InputKind.MAPPING).coerce({f"S{i}": {"tag": "x"} for i in range(200)})
    with pytest.raises(ValueError):
        _f(C.InputKind.MAPPING).coerce({"S0": {"tag": "x" * 20000}})


def test_a_mapping_must_be_flat_strings():
    for bad in ({"S0": "not a dict"}, {"S0": {"tag": {"nested": 1}}}, {"": {"tag": "x"}}, ["not a dict"]):
        with pytest.raises(ValueError):
            _f(C.InputKind.MAPPING).coerce(bad)


def test_an_empty_mapping_is_absence_not_a_value():
    """`{}` slips past the usual empty checks, so it needs saying explicitly: a required field with
    an empty mapping is missing, and an optional one is simply absent."""
    with pytest.raises(ValueError):
        _f(C.InputKind.MAPPING).coerce({})
    assert _f(C.InputKind.MAPPING, required=False).coerce({}) is None


def test_the_new_kinds_still_refuse_absence_when_required():
    for kind in (C.InputKind.HANDLE, C.InputKind.IDENTITY, C.InputKind.MAPPING):
        with pytest.raises(ValueError):
            _f(kind).coerce(None)
        assert _f(kind, required=False).coerce(None) is None


# ---------------------------------------------------------------- who the human can PICK
def test_a_candidate_shows_the_address_beside_the_name():
    """Two people share a display name far more often than an address, and the answer records the
    address — so a picker that showed only "Sam" would be a coin flip."""
    from lab.platform.contracts import SpeakerCandidate
    assert SpeakerCandidate("sam@contoso.com", "Sam Patel").label == "Sam Patel <sam@contoso.com>"
    assert SpeakerCandidate("sam@contoso.com").label == "sam@contoso.com"
    assert SpeakerCandidate("sam@contoso.com", "sam@contoso.com").label == "sam@contoso.com"


def test_a_candidate_without_an_identity_is_refused():
    from lab.platform.contracts import SpeakerCandidate
    with pytest.raises(ValueError, match="identity"):
        SpeakerCandidate("  ")


def test_candidates_are_deduplicated_and_malformed_ones_skipped():
    """A convenience must not be able to break the question: one odd attendee record should cost that
    entry, never the whole approval."""
    from lab.platform.contracts import speaker_candidates
    p = {"question": {"candidates": [{"identity": "a@b.c", "display": "Ann"},
                                     {"identity": "A@B.C"},           # same person, different case
                                     {"display": "no identity"},      # unusable
                                     "not even a dict"]}}
    got = speaker_candidates(p)
    assert [c.identity for c in got] == ["a@b.c"] and got[0].label == "Ann <a@b.c>"


def test_an_approval_that_offers_nobody_is_normal():
    """Empty is the usual case — the meeting could not be resolved — and the question still works."""
    from lab.platform.contracts import speaker_candidates
    assert speaker_candidates({}) == []
    assert speaker_candidates({"question": {"items": [{"label": "SPEAKER_00"}]}}) == []


# ---------------------------------------------------------------- a blank is not an answer
def test_a_key_with_nothing_in_it_is_refused():
    """The gate's whole purpose is that unanswered work cannot proceed, and a blank slipped through
    it live: a card that rendered with no input controls submitted {"SPEAKER_00": {"tag": ""}}, the
    gate accepted it, and the run it released carried a mapping identifying nobody."""
    from lab.platform.contracts import check_answer
    p = {"answer_labels": ["SPEAKER_00"]}
    for blank in ({"SPEAKER_00": {"tag": ""}}, {"SPEAKER_00": {"identity": "   "}},
                  {"SPEAKER_00": {}}, {"SPEAKER_00": ""}, {"SPEAKER_00": []}, {"SPEAKER_00": None}):
        with pytest.raises(ValueError, match="blank"):
            check_answer(p, blank)


def test_a_real_answer_in_either_form_still_passes():
    from lab.platform.contracts import check_answer
    p = {"answer_labels": ["SPEAKER_00"]}
    for good in ({"SPEAKER_00": {"identity": "maria@contoso.com"}},
                 {"SPEAKER_00": {"tag": "the vendor's architect"}},
                 {"SPEAKER_00": "maria@contoso.com"}):
        assert check_answer(p, good) == good


def test_only_the_blank_label_is_named():
    """Two speakers, one answered — the error must say which one needs attention."""
    from lab.platform.contracts import check_answer
    p = {"answer_labels": ["SPEAKER_00", "SPEAKER_01"]}
    with pytest.raises(ValueError) as e:
        check_answer(p, {"SPEAKER_00": {"identity": "a@b.c"}, "SPEAKER_01": {"tag": ""}})
    assert "SPEAKER_01" in str(e.value) and "SPEAKER_00" not in str(e.value)


def test_a_falsy_but_real_value_is_an_answer():
    """Genericity cuts both ways: zero is a value, and this gate must not decide otherwise for some
    future question that is not about speakers."""
    from lab.platform.contracts import check_answer
    assert check_answer({"answer_labels": ["n"]}, {"n": 0}) == {"n": 0}


# ------------------------------------------------------------------ reading ONE value out of an answer
def test_answer_value_is_the_single_value_of_a_mapping_entry():
    """A MAPPING answer is {label: {field: value}} — the inner object exists so a speaker can be
    an identity OR a tag. A question with one thing to say per label (a criticality class) still
    travels in that shape, and its consumer reads the one value without caring what the surface
    called the field."""
    assert C.answer_value({"value": "business-critical"}) == "business-critical"
    assert C.answer_value({"tag": " routine "}) == "routine"


@pytest.mark.parametrize("bad", [None, "", {}, "business-critical", {"a": "x", "b": "y"}])
def test_answer_value_refuses_anything_but_one_field(bad):
    with pytest.raises(ValueError, match="exactly one value"):
        C.answer_value(bad)


@pytest.mark.parametrize("bad", [{"value": "  "}, {"value": 3}])
def test_answer_value_refuses_a_blank_or_non_string_value(bad):
    with pytest.raises(ValueError, match="non-empty string"):
        C.answer_value(bad)


def test_the_asker_declares_the_fields_an_answer_carries():
    """A surface renders what the PAYLOAD declares, never what it infers: a speaker question
    answered as identity-or-tag and a class to confirm answered as one value are told apart by the
    asker's own declaration. An approval staged before the declaration existed is a speaker
    question, because that is the only kind there was."""
    assert C.answer_fields({"question": {"fields": ["value"]}}) == ("value",)
    assert C.answer_fields({"question": {"items": [{"label": "S0"}]}}) == ("identity", "tag")
    assert C.answer_fields({}) == ("identity", "tag")


def test_a_continuation_says_in_one_word_what_approving_starts():
    """The registry's naming convention makes a process name's last segment a noun; the button on
    every surface reads it from ONE place rather than each guessing."""
    assert C.Continuation(process="use_case_design", inputs={}).starts == "design"
    assert C.Continuation(process="transcript_to_minutes", inputs={}).starts == "minutes"
    assert "answer_value" in C.__all__ and "answer_fields" in C.__all__
