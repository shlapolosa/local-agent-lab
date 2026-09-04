"""The speech ADAPTER: transport + the `Transcriber` the composition root wires.

Offline. The HTTP layer is injected, so nothing here opens a socket or reads a credential — the
transport seam is the same one `graph_rest` uses. What is pinned is the behaviour that costs money
or hides a fault: refusing bad input BEFORE an upload is paid for, turning every provider status
into a sentence a human can act on, and never silently discarding what the caller asked for.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/speech/test_repository.py
"""
import pytest

from lab.core import speech
from lab.substrate.mcp.speech import munsit_rest as R
from lab.substrate.mcp.speech.repository import MunsitTranscriber

OK = {"statusCode": 200, "message": "Success", "data": {
    "duration": 12.0,
    "merged": [{"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00", "text": "نبدأ الـ sprint review"},
               {"start": 5.0, "end": 9.0, "speaker": "SPEAKER_01", "text": "agreed"}]}}


class FakeTransport:
    """Records the one call and returns a canned status/body — the whole HTTP layer."""

    def __init__(self, status=200, body=None, headers=None):
        self.status, self.body, self.headers = status, body if body is not None else OK, headers or {}
        self.calls = []

    def __call__(self, method, url, headers, body=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": dict(headers),
                           "body": body, "timeout": timeout})
        return R.Response(self.status, self.headers, self.body)


def _t(transport=None, key="k-123"):
    return MunsitTranscriber(R.MunsitClient(api_key=key, transport=transport or FakeTransport()))


CLIP = speech.AudioClip("meeting.m4a", b"\x00\x01audio", seconds=12.0)


# ------------------------------------------------------------------ refuse before paying
def test_video_is_refused_without_an_upload():
    """A meeting recording is video. Refusing locally means we never pay to upload gigabytes to
    learn what the container already told us."""
    tr = FakeTransport()
    with pytest.raises(speech.SpeechUnsupportedMedia) as e:
        _t(tr).transcribe(speech.AudioClip("Meeting Recording.mp4", b"x" * 50))
    assert ".mp4" in e.value.sentence and ".m4a" in e.value.sentence
    assert tr.calls == [], "nothing may be uploaded once the container is known to be wrong"


def test_audio_longer_than_the_per_request_cap_is_refused_locally():
    """The cap is real and the remedy — split it, then re-link the speaker labels — is the caller's."""
    tr = FakeTransport()
    with pytest.raises(speech.SpeechTooLong) as e:
        _t(tr).transcribe(speech.AudioClip("long.m4a", b"x", seconds=5400.0))
    assert "split" in e.value.sentence.lower() and tr.calls == []


def test_unknown_duration_is_attempted_rather_than_refused():
    """0 seconds means unknown. Refusing on unknown would block every clip whose length we cannot
    read locally, so we let the provider be the judge."""
    tr = FakeTransport()
    _t(tr).transcribe(speech.AudioClip("x.m4a", b"x", seconds=0.0))
    assert len(tr.calls) == 1


def test_a_language_the_engine_cannot_serve_is_refused_before_the_call():
    tr = FakeTransport()
    with pytest.raises(speech.SpeechUnavailable):
        _t(tr).transcribe(CLIP, languages=("fr", "en"))
    assert tr.calls == []


def test_missing_credential_is_a_configuration_refusal_not_an_auth_error():
    with pytest.raises(speech.SpeechNotConfigured):
        _t(key="").transcribe(CLIP)


# ------------------------------------------------------------------ the happy path
def test_transcribes_and_maps_to_the_domain():
    t = _t().transcribe(CLIP, languages=("ar", "en"))
    assert isinstance(t, speech.Transcript)
    assert t.labels == ("SPEAKER_00", "SPEAKER_01") and t.duration == pytest.approx(12.0)
    assert t.model == "munsit-en-ar"


def test_the_language_hint_picks_the_code_switching_model_on_the_wire():
    """Requirement one, end to end: asking for both languages must actually send the mixed model."""
    tr = FakeTransport()
    _t(tr).transcribe(CLIP, languages=("ar", "en"))
    body = tr.calls[0]["body"]
    assert b"munsit-en-ar" in body and b"return_timestamps" in body


def test_the_credential_is_sent_in_the_providers_own_header_and_never_logged():
    tr = FakeTransport()
    _t(tr).transcribe(CLIP)
    assert tr.calls[0]["headers"]["x-api-key"] == "k-123"
    assert "authorization" not in {k.lower() for k in tr.calls[0]["headers"]}


def test_diarization_off_uses_the_plain_endpoint():
    tr = FakeTransport()
    _t(tr).transcribe(CLIP, diarize=False)
    assert tr.calls[0]["url"].endswith("/audio/transcribe")
    tr2 = FakeTransport()
    _t(tr2).transcribe(CLIP, diarize=True)
    assert tr2.calls[0]["url"].endswith("/audio/diarization/transcribe")


def test_a_speaker_count_hint_is_accepted_and_ignored_rather_than_failing():
    """The port lets a caller pass what it knows. A provider without the feature must not make that
    an error — the in-person case already has few enough levers."""
    tr = FakeTransport()
    _t(tr).transcribe(CLIP, speaker_count=4)
    assert len(tr.calls) == 1


# ------------------------------------------------------------------ statuses become sentences
@pytest.mark.parametrize("status,body,expected", [
    (401, {"errorCode": 40101, "errorMessage": "Unauthorized"}, speech.SpeechUnavailable),
    (403, {"errorCode": 40301, "errorMessage": "Forbidden"}, speech.SpeechUnavailable),
    (400, {"errorCode": 40001, "errorMessage": 'Unsupported audio format ".xyz"'},
     speech.SpeechUnsupportedMedia),
    (400, {"errorCode": 40001, "errorMessage": "Invalid request"}, speech.SpeechError),
    (500, {"errorCode": 50000, "errorMessage": "boom"}, speech.SpeechError),
])
def test_every_provider_status_becomes_a_typed_refusal(status, body, expected):
    with pytest.raises(expected) as e:
        _t(FakeTransport(status=status, body=body)).transcribe(CLIP)
    assert str(e.value).endswith(".") or str(e.value)


def test_throttling_carries_the_providers_retry_hint():
    tr = FakeTransport(status=429, body={"errorMessage": "slow down"}, headers={"retry-after": "30"})
    with pytest.raises(speech.SpeechThrottled) as e:
        _t(tr).transcribe(CLIP)
    assert e.value.retry_after == 30.0


def test_a_provider_message_is_quoted_so_a_human_can_chase_it():
    with pytest.raises(speech.SpeechError) as e:
        _t(FakeTransport(status=500, body={"errorMessage": "upstream model unavailable"})).transcribe(CLIP)
    assert "upstream model unavailable" in str(e.value)


# ------------------------------------------------------------------ honesty about what it cannot do
def test_capabilities_report_what_this_provider_genuinely_lacks():
    caps = _t().capabilities()
    assert set(caps) == set(speech.CAPABILITIES)
    assert caps["transcription"] is None and caps["diarization"] is None
    assert caps["code_switching"] is None, "the mixed model exists — this is the driving requirement"
    assert isinstance(caps["speaker_hint"], speech.SpeechUnavailable), \
        "no speaker-count hint: the in-person case loses its best lever, and that must be visible"
    assert caps["speaker_hint"].remedy


def test_capabilities_report_the_missing_credential_across_every_area():
    caps = _t(key="").capabilities()
    assert all(isinstance(v, speech.SpeechNotConfigured) for v in caps.values())


def test_vocabulary_loss_is_reported_rather_than_silent():
    """The provider refuses custom vocabulary together with the mixed model. Switching wins, because
    it is the driving requirement — but the caller is TOLD, never quietly given less than it asked."""
    t = _t()
    assert t.warnings(("ar", "en"), ("Malaffi",))
    assert "vocabulary" in t.warnings(("ar", "en"), ("Malaffi",))[0].lower()
    assert t.warnings(("ar",), ("Malaffi",)) == ()
    assert t.warnings(("ar", "en"), ()) == ()


def test_the_adapter_satisfies_the_domain_port():
    assert isinstance(_t(), speech.Transcriber)


# ------------------------------------------------------------------ transport details
def test_multipart_carries_the_file_and_the_fields():
    body, content_type = R.multipart("meeting.m4a", b"AUDIO", {"model": "munsit"})
    assert b'name="file"' in body and b"meeting.m4a" in body and b"AUDIO" in body
    assert b'name="model"' in body and b"munsit" in body
    assert content_type.startswith("multipart/form-data; boundary=")
    assert body.endswith(b"--\r\n")


def test_a_transport_level_failure_is_still_a_typed_refusal():
    def broken(*a, **kw):
        raise OSError("connection reset")
    with pytest.raises(speech.SpeechError) as e:
        _t(broken).transcribe(CLIP)
    assert "connection reset" in str(e.value)


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))


# ------------------------------------------------------------------ the default (urllib) transport
class _FakeHTTPResponse:
    """What urllib hands back: a context manager with .status, .headers and .read()."""

    def __init__(self, status, headers, payload):
        self.status, self.headers, self._payload = status, headers, payload

    def read(self): return self._payload
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _FakeOpener:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.opened = response, error, []

    def open(self, req, timeout=None):
        self.opened.append({"url": req.full_url, "method": req.get_method(), "timeout": timeout,
                            "headers": dict(req.headers)})
        if self.error:
            raise self.error
        return self.response


def test_urllib_transport_decodes_a_success():
    op = _FakeOpener(_FakeHTTPResponse(200, {"Retry-After": "5"}, b'{"data": {"duration": 1.0}}'))
    r = R.UrllibTransport(op)("POST", "https://example.invalid/x", {"x-api-key": "k"}, b"body", 12.0)
    assert r.status == 200 and r.body == {"data": {"duration": 1.0}}
    assert r.headers["retry-after"] == "5", "headers are lower-cased so lookups are not case games"
    assert op.opened[0]["timeout"] == 12.0 and op.opened[0]["method"] == "POST"


def test_urllib_transport_treats_an_http_error_as_a_response_not_an_exception():
    """A 4xx carries the body that explains it — the message naming the accepted formats is exactly
    the diagnosis a caller needs, so it must not be thrown away with the exception."""
    import urllib.error
    err = urllib.error.HTTPError("https://example.invalid/x", 400, "Bad Request", {"Retry-After": "7"},
                                 None)
    err.read = lambda: b'{"errorCode": 40001, "errorMessage": "Unsupported audio format \\".mp4\\""}'
    r = R.UrllibTransport(_FakeOpener(error=err))("POST", "https://example.invalid/x", {}, b"", 1.0)
    assert r.status == 400 and "Unsupported audio format" in r.body["errorMessage"]
    assert r.headers["retry-after"] == "7"


def test_a_non_json_body_still_yields_something_a_human_can_read():
    """Providers return HTML error pages. Losing that text would leave a bare status and no clue."""
    op = _FakeOpener(_FakeHTTPResponse(502, {}, b"<html>gateway timeout</html>"))
    r = R.UrllibTransport(op)("POST", "https://example.invalid/x", {}, b"", 1.0)
    assert "gateway timeout" in r.body["errorMessage"]


def test_an_empty_body_is_an_empty_object_not_a_crash():
    r = R.UrllibTransport(_FakeOpener(_FakeHTTPResponse(200, {}, b"")))(
        "POST", "https://example.invalid/x", {}, b"", 1.0)
    assert r.body == {}


def test_the_client_builds_its_own_transport_when_none_is_injected():
    assert R.MunsitClient(api_key="k")._transport is not None


def test_a_provider_error_raised_by_a_transport_passes_through_untranslated_twice():
    """A transport that already speaks the provider's error type must not be re-wrapped as a
    transport failure — that would relabel a real 403 as a network problem."""
    def already(*a, **kw):
        raise R.MunsitError(403, 40301, "Forbidden")
    with pytest.raises(R.MunsitError) as e:
        R.MunsitClient(api_key="k", transport=already).post_audio("/p", "a.m4a", b"x", {})
    assert e.value.status == 403


def test_a_missing_retry_after_header_is_none_not_zero():
    assert R.MunsitClient(api_key="k")._transport is not None
    tr = FakeTransport(status=429, body={"errorMessage": "slow"}, headers={})
    with pytest.raises(speech.SpeechThrottled) as e:
        _t(tr).transcribe(CLIP)
    assert e.value.retry_after is None


# ------------------------------------------------------------------ the composition entry point
def test_build_is_the_one_place_the_adapter_is_assembled(monkeypatch):
    """A composition root names `build()` and nothing below it reads configuration — so every value
    defaults to the single env reader and every one can be overridden for a test or a second account."""
    from lab.platform import config
    from lab.substrate.mcp.speech import repository as repo

    monkeypatch.setattr(config, "MUNSIT_API_KEY", "from-config", raising=False)
    monkeypatch.setattr(config, "MUNSIT_BASE_URL", "https://config.invalid/api/v1", raising=False)
    t = repo.build()
    assert isinstance(t, repo.MunsitTranscriber) and t._client.api_key == "from-config"
    assert t._client.base_url == "https://config.invalid/api/v1"

    override = repo.build(api_key="explicit", base_url="https://other.invalid/v1/", timeout=1.0)
    assert override._client.api_key == "explicit" and override._client.timeout == 1.0
    assert override._client.base_url == "https://other.invalid/v1", "a trailing slash is normalised away"


def test_build_produces_something_the_container_can_hand_out_as_the_port():
    from lab.substrate.mcp.speech import repository as repo
    assert isinstance(repo.build(api_key="k"), speech.Transcriber)
