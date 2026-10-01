"""speech_identify / speech_enrol — voiceprints on speech-mcp, end to end with no model and no database.

The audio is a REAL WAV, cut by the real slicer: each "voice" is a constant sample value over its
seconds, and the fake model maps that value to a direction. So what is exercised is everything except
the neural network — segment selection, slicing, one batched model call, matching, the consent rule —
and nothing here could pass by accident of a fake that ignored the audio.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/speech/test_voiceprint_tools.py"""
import io
import json
import struct
import wave

import pytest

from lab.core.speech import AudioClip
from lab.core.speech.voiceprint import Voiceprint

from .test_server import FakeStore, call, call_error, srv  # noqa: F401 - srv is a fixture

RATE = 16000
VOICES = {1000: (1.0, 0.0, 0.0), 2000: (0.0, 1.0, 0.0), 3000: (0.0, 0.0, 1.0)}   # sample value -> voice
AUDIO_REF, SEGS_REF = "art://rec/Meeting Recording.mp4", "art://seg/meeting.segments.json"


def wav_of(spans):
    """A 16 kHz mono WAV whose every span [start, end, value] holds that constant sample value."""
    total = max(e for _, e, _ in spans)
    samples = [0] * int(total * RATE)
    for b, e, v in spans:
        samples[int(b * RATE):int(e * RATE)] = [v] * (int(e * RATE) - int(b * RATE))
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return out.getvalue()


class FakeModel:
    model = "fake-ecapa"

    def __init__(self):
        self.calls = []

    def embed(self, clips):
        self.calls.append(len(clips))
        return [VOICES[struct.unpack("<h", c[44:46])[0]] for c in clips]


class FakeGallery:
    def __init__(self, *vps):
        self.rows = list(vps)

    def voiceprints(self, model):
        return [v for v in self.rows if v.model == model]

    def add(self, vp):
        self.rows.append(vp)


# A meeting: S1 speaks voice 1000 (the chair), S2 voice 2000 (Nabeel), S3 voice 3000 (nobody known).
SPANS = [(0, 4, 1000), (4, 8, 2000), (8, 12, 3000), (12, 16, 1000), (16, 20, 2000), (20, 24, 3000)]
SEGMENTS = [{"speaker": f"S{(i % 3) + 1}", "start": b, "end": e, "text": "words", "language": "en"}
            for i, (b, e, _) in enumerate(SPANS)]
SEGMENTS.append({"speaker": "S3", "start": 0, "end": 4, "text": "", "language": ""})   # a breath, no words


def chair():
    return Voiceprint(kind="identity", key="chair@lab.example", vector=(1, 0, 0), model="fake-ecapa",
                      consented_by="chair@lab.example")


def nabeel():
    return Voiceprint(kind="tag", key="Nabeel", vector=(0, 1, 0), model="fake-ecapa", consented_by="chair@lab.example")


@pytest.fixture
def lab(srv, monkeypatch):  # noqa: F811
    model, gallery = FakeModel(), FakeGallery(chair(), nabeel())
    up = FakeStore({AUDIO_REF: {"body": b"VIDEO", "name": "Meeting Recording.mp4"}})
    art = FakeStore({SEGS_REF: {"body": json.dumps({"segments": SEGMENTS}).encode()}})
    monkeypatch.setattr(srv.audio_tools, "to_wav16k",
                        lambda clip, tool: AudioClip(name="m.wav", data=wav_of(SPANS)))
    c = srv.server.container
    with c.uploads.override(up), c.artifacts.override(art), c.speaker_embedder.override(model), \
         c.voiceprints.override(gallery):
        yield srv.server, model, gallery


# ------------------------------------------------------------------ identify
def test_known_voices_are_suggested_and_an_unknown_one_is_left_empty(lab):
    server, model, _ = lab
    got = {s["label"]: s for s in call(server, "speech_identify", audio_ref=AUDIO_REF, segments_ref=SEGS_REF)["speakers"]}
    assert got["S1"]["suggestion"]["identity"] == "chair@lab.example"
    assert got["S2"]["suggestion"]["tag"] == "Nabeel"
    assert got["S3"]["suggestion"] == {}, "an unknown voice must not be given the nearest person"
    assert got["S1"]["seconds"] == 8.0
    assert model.calls == [6], "every clip goes to the model in ONE call, and a wordless segment is not a clip"


def test_identify_stores_nothing(lab):
    server, _, gallery = lab
    call(server, "speech_identify", audio_ref=AUDIO_REF, segments_ref=SEGS_REF)
    assert len(gallery.rows) == 2


def test_an_unreachable_model_is_a_sentence_naming_the_setting(srv):  # noqa: F811
    from lab.substrate.voiceprint.client import HttpEmbedder
    art = FakeStore({SEGS_REF: {"body": json.dumps({"segments": SEGMENTS}).encode()}})
    up = FakeStore({AUDIO_REF: {"body": b"VIDEO", "name": "Meeting Recording.mp4"}})
    c = srv.server.container
    with c.uploads.override(up), c.artifacts.override(art), c.speaker_embedder.override(HttpEmbedder("")), \
         pytest.MonkeyPatch.context() as mp:
        mp.setattr(srv.audio_tools, "to_wav16k", lambda clip, tool: AudioClip(name="m.wav", data=wav_of(SPANS)))
        msg = call_error(srv.server, "speech_identify", audio_ref=AUDIO_REF, segments_ref=SEGS_REF)
    assert "VOICEPRINT_URL" in msg


# ------------------------------------------------------------------ enrol
def test_only_ticked_unrecognised_voices_are_kept_with_who_attested_consent(lab):
    server, model, gallery = lab
    got = call(server, "speech_enrol", audio_ref=AUDIO_REF, segments_ref=SEGS_REF, consented_by="chair@lab.example",
               source="art://seg/t", speaker_map={
                   "S1": {"identity": "chair@lab.example", "consent": "yes"},   # already known -> left alone
                   "S2": {"tag": "Nabeel"},                                     # no tick -> never kept
                   "S3": {"tag": "Ahmed", "consent": "yes"}})                   # new + ticked -> kept
    assert got["enrolled"] == ["S3"]
    assert got["skipped"] == {"S1": "already recognised as the person named"}
    added = gallery.rows[-1]
    assert (added.kind, added.key, added.consented_by, added.source) == ("tag", "Ahmed", "chair@lab.example", "art://seg/t")
    assert model.calls == [4], "an unticked voice is never even embedded"
    assert "Ahmed" not in json.dumps(got), "the result carries labels, never names"


def test_with_no_tick_anywhere_nothing_is_decoded_embedded_or_stored(lab):
    server, model, gallery = lab
    got = call(server, "speech_enrol", audio_ref=AUDIO_REF, segments_ref=SEGS_REF, consented_by="c@x",
               speaker_map={"S3": {"tag": "Ahmed"}})
    assert got["enrolled"] == [] and model.calls == [] and len(gallery.rows) == 2


def test_a_voiceprint_is_never_kept_without_who_attested_consent(lab):
    server, *_ = lab
    msg = call_error(server, "speech_enrol", audio_ref=AUDIO_REF, segments_ref=SEGS_REF, consented_by=" ",
                     speaker_map={"S3": {"tag": "Ahmed", "consent": "yes"}})
    assert "consent" in msg
