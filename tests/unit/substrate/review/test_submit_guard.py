"""The Submit form refuses what the contract would refuse, instead of a run discovering it.

Measured live 18 Sep 2026, twice in ten minutes: a person typed their name into `submission_handle`
(the first text box on the form, its format hidden in a hover) and was rejected; then pressed Run
with nothing attached, which queued a run, minted a trace id and died at the first executor with
"got neither". A 600-second run is not a validator.
"""
import pytest

from fixtures.streamlit import APP, FakeSt, install
from lab.platform import contracts

SPEC = contracts.PROCESSES["use_case_screening"]


def test_every_text_kind_with_a_strict_validator_shows_its_shape():
    """A placeholder is the cheapest possible fix for "this looks like free text and is not"."""
    kinds = contracts.InputKind
    for kind in (kinds.HANDLE, kinds.IDENTITY, kinds.CONVERSATION):
        assert APP.PLACEHOLDERS.get(kind), kind


def test_the_handle_placeholder_is_what_the_validator_actually_parses():
    """A placeholder that disagreed with the validator would teach the wrong format with more
    confidence than no placeholder at all."""
    from lab.core.collab.model import ContentHandle

    shown = APP.PLACEHOLDERS[contracts.InputKind.HANDLE]
    scheme, _, rest = shown.partition("://")
    assert scheme == "collab" and rest.count("/") == 2
    assert str(ContentHandle.parse("collab://item/drive1/item1"))


def test_the_identity_placeholder_names_what_a_principal_is_not_a_person():
    shown = APP.PLACEHOLDERS[contracts.InputKind.IDENTITY]
    assert "@" in shown and "domain" in shown


# ---------------------------------------------------------------- the button


def _ready(supplied: dict) -> bool:
    """The Run button's own three questions, against a given set of filled fields."""
    def got(name):
        v = supplied.get(name)
        return bool(v.strip()) if isinstance(v, str) else bool(v)
    missing = [f.name for f in SPEC.inputs if f.required and not got(f.name)]
    unmet = [g for g in SPEC.one_of if sum(got(n) for n in g) != 1]
    return not missing and not unmet


def test_run_is_refused_with_nothing_attached():
    """The case that burned a run: both submission routes are individually optional, so the old
    `required_files` list was EMPTY and Run was always enabled."""
    assert _ready({}) is False


def test_run_is_refused_when_the_submission_is_missing_but_the_submitter_is_not():
    assert _ready({"submitter": "a@b.com"}) is False


def test_run_is_refused_when_both_submission_routes_are_given():
    assert _ready({"submitter": "a@b.com", "submission": "art://a/b.md",
                   "submission_handle": "collab://item/d/i"}) is False


@pytest.mark.parametrize("route", ["submission", "submission_handle"])
def test_run_is_allowed_with_a_submitter_and_exactly_one_route(route):
    assert _ready({"submitter": "a@b.com", route: "x"}) is True


def test_a_required_non_file_field_is_guarded_too():
    """`submitter` is required and was never checked either — validate caught it, but only after
    the form had already said the submission was ready to send."""
    assert _ready({"submission": "art://a/b.md"}) is False


def test_the_button_asks_exactly_what_the_contract_asks():
    """The guard must not become a SECOND rule that can disagree with `validate`. Anything this
    lets through, the contract accepts; anything it stops, the contract would refuse."""
    good = {"submitter": "a@b.com", "submission": "art://a/b.md"}
    assert _ready(good) and SPEC.validate(good)
    for bad in ({}, {"submitter": "a@b.com"}, {"submission": "art://a/b.md"}):
        assert not _ready(bad)
        with pytest.raises(ValueError):
            SPEC.validate(bad)
