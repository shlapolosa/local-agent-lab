"""speech-mcp — the SPEECH port as governed tools. Offline: the provider, the upload store and the
artifact store are all overridden on the container, so nothing opens a socket.

What is pinned here is what a CALLER experiences and what a caller must never experience: the tool
catalogue is the contract, an hour of speech never comes back inline, a typed refusal arrives as a
sentence rather than a status, and NO SPAN CARRIES A WORD OF WHAT WAS SAID — this lab's traces go to
a public, unauthenticated collector, and a transcript is the most sensitive thing it handles.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/speech/test_server.py
"""
import asyncio
import importlib
import json

import pytest
from fastmcp import Client

from lab.core import speech
from lab.platform.contracts import SpeechTools

TOOLS = {"speech_capabilities", "speech_transcribe"}

SEGS = (speech.Segment("SPEAKER_00", 0.0, 6.0, "خلينا نعمل migration بعد الـ review"),
        speech.Segment("SPEAKER_01", 6.0, 8.0, "agreed"),
        speech.Segment("SPEAKER_00", 8.0, 12.0, "we retire the legacy portal"))


@pytest.fixture(scope="module")
def srv():
    """The server composes at import, so the environment is pinned around a manual load.

    `config.AUDIO_EXTRACT_BIN` is pinned as an ATTRIBUTE, not as an environment variable: `config`
    reads env once at ITS import, which may already have happened in another test module, so setting
    os.environ here would silently do nothing. This is the seam CLAUDE.md means by "pin env with
    fixtures, never at import".
    """
    import os
    from lab.platform import config

    saved_env = {k: os.environ.get(k) for k in ("MCP_SHARED_SECRET", "OTEL_EXPORTER_OTLP_ENDPOINT")}
    saved_bin = config.AUDIO_EXTRACT_BIN
    os.environ["MCP_SHARED_SECRET"] = "shh"
    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    config.AUDIO_EXTRACT_BIN = "/usr/bin/ffmpeg"
    module = importlib.reload(importlib.import_module("lab.substrate.mcp.speech.server"))
    try:
        yield module
    finally:
        config.AUDIO_EXTRACT_BIN = saved_bin
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class FakeSpeech:
    """The Transcriber port, faked. Records what it was asked for."""

    def __init__(self, transcript=None, raises=None):
        self.transcript = transcript if transcript is not None else speech.Transcript(
            segments=SEGS, duration=26.9, model="mixed-model", provider="p")
        self.raises, self.calls = raises, []

    def capabilities(self, deep=False):
        return {c: None for c in speech.CAPABILITIES} | {
            "speaker_hint": speech.SpeechUnavailable("speaker_hint", "not offered", "improve the recording")}

    def warnings(self, languages=(), vocabulary=()):
        return ("custom vocabulary was dropped",) if vocabulary else ()

    def transcribe(self, audio, **kw):
        self.calls.append({"audio": audio, **kw})
        if self.raises:
            raise self.raises
        return self.transcript


class FakeStore:
    def __init__(self, blobs=None):
        self.blobs, self.written = blobs or {}, []

    def get(self, ref):
        return self.blobs[ref]

    def put(self, name, data, content_type=""):
        self.written.append({"name": name, "data": data, "content_type": content_type})
        return f"art://fake/{name}"


AUDIO_REF = "art://abc/meeting.m4a"
VIDEO_REF = "art://abc/Meeting Recording.mp4"
BLOBS = {AUDIO_REF: {"body": b"AUDIO", "name": "meeting.m4a"},
         VIDEO_REF: {"body": b"VIDEO", "name": "Meeting Recording.mp4"}}


@pytest.fixture
def wired(srv):
    sp, up, art = FakeSpeech(), FakeStore(BLOBS), FakeStore()
    with srv.server.container.speech.override(sp), \
         srv.server.container.uploads.override(up), \
         srv.server.container.artifacts.override(art):
        yield srv.server, sp, up, art


def call(server, _tool, **args):
    async def go():
        async with Client(server.mcp) as c:
            return await c.call_tool(_tool, args)
    return asyncio.run(go()).data


def call_error(server, _tool, **args) -> str:
    async def go():
        async with Client(server.mcp) as c:
            try:
                await c.call_tool(_tool, args)
            except Exception as e:                       # noqa: BLE001 - the message IS the contract
                return str(e)
            raise AssertionError(f"{_tool} did not fail")
    return asyncio.run(go())


def tools(server):
    async def go():
        async with Client(server.mcp) as c:
            return {t.name for t in await c.list_tools()}
    return asyncio.run(go())


# ------------------------------------------------------------------ the contract
def test_tool_catalogue_is_the_contract(wired):
    server, *_ = wired
    assert tools(server) == TOOLS == set(SpeechTools.names())


def test_no_tool_name_is_a_bare_literal_anywhere_in_the_catalogue():
    assert SpeechTools.SERVER == "speech_mcp"
    assert all(n.startswith("speech_") for n in SpeechTools.names())


# ------------------------------------------------------------------ transcribe
def test_the_timeline_comes_back_by_reference_and_the_digest_inline(wired):
    """An hour of speech is not a tool result; a speaker list is."""
    server, sp, up, art = wired
    out = call(server, "speech_transcribe", audio_ref=AUDIO_REF, languages=["ar", "en"])
    assert out["transcript_ref"] == "art://fake/meeting.m4a.segments.json"
    assert out["duration"] == pytest.approx(26.9) and out["read_with"] == "storage_get"
    assert [s["label"] for s in out["speakers"]] == ["SPEAKER_00", "SPEAKER_01"]
    assert out["speakers"][0]["turns"] == 2 and out["speakers"][0]["seconds"] == pytest.approx(10.0)
    # the stored artifact carries the FULL timeline, which the inline result never does
    stored = json.loads(art.written[0]["data"])
    assert len(stored["segments"]) == 3 and stored["segments"][0]["text"]


def test_the_language_hint_reaches_the_provider(wired):
    server, sp, *_ = wired
    call(server, "speech_transcribe", audio_ref=AUDIO_REF, languages=["ar", "en"])
    assert sp.calls[0]["languages"] == ("ar", "en")


def test_samples_are_truncated_because_they_are_evidence_not_an_excerpt(wired, srv):
    server, sp, *_ = wired
    long = "x" * (srv.MAX_SAMPLE_CHARS + 200)
    sp.transcript = speech.Transcript(segments=(speech.Segment("SPEAKER_00", 0.0, 5.0, long),), duration=5.0)
    out = call(server, "speech_transcribe", audio_ref=AUDIO_REF)
    assert len(out["speakers"][0]["samples"][0]) == srv.MAX_SAMPLE_CHARS


def test_a_dropped_capability_is_reported_to_the_caller_not_hidden(wired):
    server, *_ = wired
    out = call(server, "speech_transcribe", audio_ref=AUDIO_REF, languages=["ar", "en"],
               vocabulary=["Malaffi"])
    assert out["warnings"] and "vocabulary" in out["warnings"][0]


def test_no_reported_language_reads_as_unknown_not_as_no_switch(wired):
    """The provider we have reports no per-segment language. `code_switched: false` must therefore
    mean "not reported", and the tool docstring says so — this pins the shape a caller relies on."""
    server, *_ = wired
    out = call(server, "speech_transcribe", audio_ref=AUDIO_REF, languages=["ar", "en"])
    assert out["languages"] == [] and out["code_switched"] is False


def test_video_is_extracted_before_it_reaches_the_provider(wired, srv, monkeypatch):
    """A meeting recording is video. The extraction happens HERE, behind the port."""
    server, sp, *_ = wired
    seen = {}

    def fake_extract(clip, tool, **kw):
        seen["tool"], seen["name"] = tool, clip.name
        return speech.AudioClip("Meeting Recording.m4a", b"EXTRACTED")

    monkeypatch.setattr(srv.audio_tools, "extract", fake_extract)
    call(server, "speech_transcribe", audio_ref=VIDEO_REF)
    assert seen["name"] == "Meeting Recording.mp4" and seen["tool"] == "/usr/bin/ffmpeg"
    assert sp.calls[0]["audio"].data == b"EXTRACTED"


def test_audio_is_not_re_encoded(wired, srv, monkeypatch):
    server, *_ = wired
    monkeypatch.setattr(srv.audio_tools, "extract",
                        lambda *a, **k: pytest.fail("audio must never be extracted"))
    call(server, "speech_transcribe", audio_ref=AUDIO_REF)


# ------------------------------------------------------------------ refusals are sentences
def test_a_typed_refusal_arrives_as_a_sentence_not_a_status(wired):
    server, sp, *_ = wired
    sp.raises = speech.SpeechUnsupportedMedia(".xyz", (".m4a", ".wav"))
    msg = call_error(server, "speech_transcribe", audio_ref=AUDIO_REF)
    assert ".xyz" in msg and ".m4a" in msg


def test_an_unservable_language_pair_is_refused_with_its_remedy(wired):
    server, sp, *_ = wired
    sp.raises = speech.SpeechUnavailable("code_switching", "serves ar and en only", "ask for ar and en")
    msg = call_error(server, "speech_transcribe", audio_ref=AUDIO_REF, languages=["fr"])
    assert "Remedy:" in msg


# ------------------------------------------------------------------ capabilities
def test_capabilities_reports_the_table_including_what_is_missing(wired):
    server, *_ = wired
    out = call(server, "speech_capabilities")
    assert "speaker_hint" in out["unavailable"] and out["unavailable"]["speaker_hint"]["remedy"]
    assert set(out["available"]) == set(speech.CAPABILITIES) - {"speaker_hint"}
    assert out["extraction_tool"] is True and ".m4a" in out["accepted_media"]


# ------------------------------------------------------------------ the privacy rule
def test_no_span_attribute_carries_a_word_of_what_was_said(wired, srv, monkeypatch):
    """Span attributes bypass the gateway's PII guardrail and reach a public collector. Counts,
    durations and shapes only — never speech, never a file name."""
    recorded = {}

    class FakeSpan:
        def set_attribute(self, k, v): recorded[k] = v
        def set_attributes(self, d): recorded.update(d)

    monkeypatch.setattr(srv, "span", lambda: FakeSpan())
    server, *_ = wired
    call(server, "speech_transcribe", audio_ref=AUDIO_REF, languages=["ar", "en"])
    assert recorded, "the tool must still emit telemetry"
    said = {w for s in SEGS for w in s.text.split()}
    for key, value in recorded.items():
        assert isinstance(value, (int, float, bool)), f"{key} is not a count/shape: {value!r}"
        assert not any(w in str(value) for w in said), f"{key} leaked speech"
    assert not any("name" in k or "ref" in k for k in recorded), "no file name or ref on a span"


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
