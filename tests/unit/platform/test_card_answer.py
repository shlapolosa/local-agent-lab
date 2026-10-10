"""A card's FLAT submit response, as the gate's keyed answer.

An Adaptive Card posts what its inputs are keyed by, flat and all strings:

    {"cand:0": "admit", "cand:0::id": "", "cand:1": "existing", "cand:1::id": "ClinicalReview"}

The gate wants `{label: {"value": …}}`. Turning one into the other inside Power Automate means
assembling a keyed object from N dynamic labels in a flow expression — debuggable only against a live
card, and untestable anywhere. So the flow posts the response VERBATIM and this does the shaping: a pure
function, in Python, with tests. The same move as putting the catalogue walk in `semantic_view_corpus`
instead of in a script — the part that can be got wrong belongs where it can be unit-tested.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/platform/test_card_answer.py
"""
import pytest

from lab.platform.contracts import ID_SUFFIX, card_answer


def test_one_choice_per_label_becomes_the_gates_shape():
    assert card_answer({"a": "admit", "b": "decline"}, ["a", "b"]) == \
        {"a": {"value": "admit"}, "b": {"value": "decline"}}


def test_a_companion_field_is_JOINED_onto_its_choice_not_answered_separately():
    """`existing` means nothing without the concept it already means, and the gate takes ONE value per
    label — so the two controls a person sees become the one answer the contract accepts."""
    flat = {"a": "existing", f"a{ID_SUFFIX}": "ClinicalReview", "b": "admit", f"b{ID_SUFFIX}": ""}
    assert card_answer(flat, ["a", "b"]) == \
        {"a": {"value": "existing:ClinicalReview"}, "b": {"value": "admit"}}


def test_an_existing_with_no_id_is_left_for_the_gate_to_refuse():
    """NOT silently turned into a decline. A person who chose "it already exists" and typed nothing has
    made a mistake worth telling them about, and `plan` already says so in a sentence."""
    assert card_answer({"a": "existing", f"a{ID_SUFFIX}": "  "}, ["a"]) == {"a": {"value": "existing"}}


def test_only_the_labels_the_CARD_declared_are_read():
    """A card posts whatever its client sent. The asker said which labels it asked about, and anything
    else in the body is not an answer to this question."""
    flat = {"a": "admit", "zzz": "admit", "request_id": "apr-1", "labels": ["a"]}
    assert card_answer(flat, ["a"]) == {"a": {"value": "admit"}}


def test_a_label_the_person_did_not_answer_is_ABSENT_rather_than_guessed():
    """`check_answer` enforces completeness; inventing a default here would walk past it, and the default
    that got invented would be a decision nobody made."""
    assert card_answer({"a": "admit"}, ["a", "b"]) == {"a": {"value": "admit"}}


def test_values_are_strings_and_blanks_are_not_answers():
    assert card_answer({"a": "", "b": None, "c": "  admit  "}, ["a", "b", "c"]) == {"c": {"value": "admit"}}
    with pytest.raises(ValueError):
        card_answer("not a mapping", ["a"])
