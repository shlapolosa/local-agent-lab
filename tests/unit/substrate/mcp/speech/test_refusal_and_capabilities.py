"""Shared refusal translation, and what each bake-off adapter says it can do.

`refusal.translate` is the one place a provider status becomes a sentence a person can act on, and
it is shared by four adapters — so a gap here is a gap in all of them at once. `capabilities()`
matters for the same reason the port makes it RETURN rather than raise: the bake-off skips an
unconfigured provider by reading it, so a wrong answer there silently drops a provider from a
comparison that claims to be complete.
"""
import pytest

from lab.core.speech import (CAPABILITIES, SpeechError, SpeechNotConfigured, SpeechThrottled,
                             SpeechUnavailable, SpeechUnsupportedMedia)
from lab.substrate.mcp.speech import assembly_repository as AR
from lab.substrate.mcp.speech import eleven_repository as ER
from lab.substrate.mcp.speech import refusal
from lab.substrate.mcp.speech import soniox_repository as SR
from lab.substrate.mcp.speech.http import ProviderError

ACCEPTED = (".mp3", ".wav")


def tr(status, message="", code="", retry=None):
    return refusal.translate(ProviderError(status, code, message, retry),
                             setting="SOME_KEY", accepted=ACCEPTED)


def test_a_rate_limit_becomes_a_throttle_carrying_the_providers_own_retry_delay():
    got = tr(429, "slow down", retry=12.0)
    assert isinstance(got, SpeechThrottled) and "12" in str(got)


def test_a_refused_credential_names_the_setting_an_operator_must_fix():
    for status in (401, 403):
        got = tr(status, "invalid key")
        assert isinstance(got, SpeechUnavailable)
        assert "SOME_KEY" in str(got) and "invalid key" in str(got)


@pytest.mark.parametrize("message", ["unsupported audio format", "cannot decode this codec",
                                     "bad media type", "unsupported file type"])
def test_a_media_complaint_becomes_the_typed_media_refusal_that_lists_what_is_accepted(message):
    got = tr(415, message)
    assert isinstance(got, SpeechUnsupportedMedia) and ".mp3" in str(got)


def test_a_plain_bad_request_is_not_mistaken_for_a_media_problem():
    """Guessing 'media' from any 400 would send a caller to re-encode audio that was fine."""
    got = tr(400, "speakers_expected must be positive")
    assert not isinstance(got, SpeechUnsupportedMedia) and "400" in str(got)


def test_a_provider_that_never_finished_says_so_rather_than_reporting_a_status():
    got = tr(0, "the provider did not finish within 900s", code="timeout")
    assert isinstance(got, SpeechError) and "did not finish" in str(got)


def test_an_unrecognised_status_still_quotes_the_providers_words():
    assert "teapot" in str(tr(418, "teapot"))


@pytest.mark.parametrize("build", [ER.build, AR.build, SR.build])
def test_an_unconfigured_provider_reports_every_capability_as_not_configured(build):
    """This is what the bake-off reads to SKIP a provider by name. If it raised, or answered
    optimistically, an unconfigured provider would either abort the run or be reported as failing."""
    caps = build(api_key="", transport=lambda *a, **k: None).capabilities()
    assert set(caps) == set(CAPABILITIES)
    assert all(isinstance(v, SpeechNotConfigured) for v in caps.values())


@pytest.mark.parametrize("build", [ER.build, AR.build, SR.build])
def test_a_configured_provider_answers_every_capability_named_by_the_port(build):
    caps = build(api_key="k", transport=lambda *a, **k: None).capabilities()
    assert set(caps) == set(CAPABILITIES)
    assert caps["transcription"] is None and caps["diarization"] is None


def test_each_provider_is_honest_about_the_one_thing_it_cannot_do():
    """Each of these was established from the provider's own documentation, and each is the reason
    that provider is in the bake-off rather than simply chosen."""
    t = lambda *a, **k: None                                                    # noqa: E731
    assert ER.build(api_key="k", transport=t).capabilities()["vocabulary"] is not None
    assert AR.build(api_key="k", transport=t).capabilities()["code_switching"] is not None
    assert SR.build(api_key="k", transport=t).capabilities()["speaker_hint"] is not None
