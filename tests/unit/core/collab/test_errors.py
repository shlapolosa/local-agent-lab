"""src/lab/core/collab/errors.py — why a collaboration capability did not answer, TYPED, so a caller
renders a SENTENCE naming the missing grant and its remedy instead of relaying an opaque 403.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/core/collab/test_errors.py"""
import pytest

from lab.core.collab.errors import (CollabError, CollabNotConfigured, CollabThrottled,
                                    CollabUnavailable)


def test_an_unavailable_capability_renders_a_sentence_naming_the_grant_and_the_remedy():
    err = CollabUnavailable("recordings", reason="the app has no meeting-recording grant",
                            remedy="ask an administrator to grant it, then re-run the capability probe")
    assert err.capability == "recordings"
    assert str(err) == ("recordings is unavailable: the app has no meeting-recording grant. "
                        "Remedy: ask an administrator to grant it, then re-run the capability probe.")
    assert err.sentence == str(err)


def test_a_remedy_is_optional_and_the_sentence_stays_whole_without_one():
    err = CollabUnavailable("meetings", reason="the tenant returned 403")
    assert str(err) == "meetings is unavailable: the tenant returned 403." and err.remedy == ""


def test_a_sentence_is_punctuated_once_however_the_adapter_wrote_its_prose():
    err = CollabUnavailable("sites", reason="no grant.", remedy="grant it.")
    assert str(err) == "sites is unavailable: no grant. Remedy: grant it."


def test_an_unavailable_capability_serialises_for_a_tool_result():
    err = CollabUnavailable("watches", reason="no subscription grant", remedy="grant it")
    assert err.to_dict() == {"capability": "watches", "reason": "no subscription grant",
                             "remedy": "grant it", "sentence": err.sentence}


def test_a_capability_is_required_because_an_unnamed_failure_cannot_be_remedied():
    with pytest.raises(ValueError, match="capability"):
        CollabUnavailable("  ", reason="something went wrong")


def test_not_configured_is_the_labs_own_side_of_the_same_story():
    err = CollabNotConfigured("COLLAB_CLIENT_SECRET")
    assert isinstance(err, CollabUnavailable) and err.capability == "configuration"
    assert "COLLAB_CLIENT_SECRET is not configured" in str(err) and "COLLAB_CLIENT_SECRET" in err.remedy
    assert CollabNotConfigured("X", remedy="run the runbook").remedy == "run the runbook"


def test_throttling_says_when_to_come_back():
    err = CollabThrottled("items", retry_after=12.5)
    assert err.capability == "items" and err.retry_after == 12.5
    assert str(err) == "items is throttled by the provider: retry in 12.5 s."
    assert err.to_dict()["retry_after"] == 12.5


def test_throttling_without_a_retry_hint_still_reads_as_a_sentence():
    err = CollabThrottled("items")
    assert err.retry_after is None and str(err) == "items is throttled by the provider: retry later."
    assert err.to_dict()["retry_after"] is None


def test_one_base_catches_every_collaboration_failure():
    for err in (CollabUnavailable("a", "b"), CollabNotConfigured("C"), CollabThrottled("d")):
        assert isinstance(err, CollabError) and isinstance(err, Exception)
        assert err.sentence and err.to_dict()["sentence"] == err.sentence
