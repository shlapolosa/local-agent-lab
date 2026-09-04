"""Audio extraction — the step that exists because a meeting recording is VIDEO and every speech
provider we surveyed takes audio only.

A host tool does the work, exactly as a document renderer does elsewhere in the lab, so the tool is
INJECTED here and nothing shells out during a test. What is pinned is the decision logic: when
extraction is needed at all, that a missing tool degrades to a sentence rather than a stack trace,
and that adding another tool is a registry entry rather than a new branch.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/speech/test_audio.py
"""
import pytest

from lab.core import speech
from lab.substrate.mcp.speech import audio as A

ACCEPTED = (".m4a", ".wav", ".mp3", ".webm")


def test_audio_the_provider_accepts_is_left_alone():
    """Never re-encode what already works: it costs time and loses quality for nothing."""
    assert A.needs_extraction(".m4a", ACCEPTED) is False
    assert A.needs_extraction(".wav", ACCEPTED) is False


def test_a_container_that_is_both_video_and_accepted_audio_is_left_alone():
    """`.webm` carries video but this provider takes it, so acceptance wins over "looks like video"."""
    assert ".webm" in A.VIDEO_CONTAINERS and A.needs_extraction(".webm", ACCEPTED) is False


def test_video_needs_extraction():
    assert A.needs_extraction(".mp4", ACCEPTED) is True
    assert A.needs_extraction(".mov", ACCEPTED) is True


def test_something_that_is_neither_is_refused_rather_than_guessed():
    """A `.pdf` is not audio and not video. Attempting extraction would waste a subprocess and
    produce a confusing failure; saying so immediately is the honest answer."""
    with pytest.raises(speech.SpeechUnsupportedMedia):
        A.needs_extraction(".pdf", ACCEPTED)


# ------------------------------------------------------------------ the extraction itself
class FakeRun:
    """Stands in for the host tool: records argv and writes the output file it was asked for."""

    def __init__(self, returncode=0, stderr="", writes=b"EXTRACTED"):
        self.returncode, self.stderr, self.writes, self.calls = returncode, stderr, writes, []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        if self.writes is not None and self.returncode == 0:
            open(argv[-1], "wb").write(self.writes)
        return type("R", (), {"returncode": self.returncode, "stderr": self.stderr})()


CLIP = speech.AudioClip("Meeting Recording.mp4", b"\x00videobytes", seconds=1800.0)


def test_extraction_returns_an_audio_clip_the_provider_will_take():
    run = FakeRun()
    out = A.extract(CLIP, "/usr/bin/ffmpeg", run=run)
    assert isinstance(out, speech.AudioClip)
    assert out.suffix == ".m4a" and out.data == b"EXTRACTED"
    assert out.seconds == 1800.0, "the known length must survive extraction"
    assert out.name.startswith("Meeting Recording"), "the original name is kept so logs stay legible"


def test_each_known_tool_gets_its_own_argv_from_a_registry():
    """Adding a third tool is one registry entry, not a branch in the extraction logic."""
    assert set(A.EXTRACTORS) == {"ffmpeg", "afconvert"}
    ff = FakeRun(); A.extract(CLIP, "/usr/bin/ffmpeg", run=ff)
    assert "-vn" in ff.calls[0], "ffmpeg must be told to drop the video stream"
    af = FakeRun(); A.extract(CLIP, "/usr/bin/afconvert", run=af)
    assert af.calls[0][0] == "/usr/bin/afconvert"


def test_an_unknown_tool_is_refused_by_name():
    with pytest.raises(speech.SpeechUnavailable) as e:
        A.extract(CLIP, "/usr/bin/sox", run=FakeRun())
    assert "sox" in e.value.sentence


def test_no_tool_configured_is_a_sentence_naming_the_setting_not_a_crash():
    """The likeliest real failure: the container shipped without the tool. A caller must be told
    which setting to fill in, not handed a file-not-found."""
    with pytest.raises(speech.SpeechUnavailable) as e:
        A.extract(CLIP, "", run=FakeRun())
    assert "AUDIO_EXTRACT_BIN" in e.value.sentence and e.value.remedy


def test_a_failing_tool_reports_its_own_error_text():
    """Whatever the tool said is the diagnosis; swallowing it leaves an unfixable failure."""
    with pytest.raises(speech.SpeechError) as e:
        A.extract(CLIP, "/usr/bin/ffmpeg", run=FakeRun(returncode=1, stderr="moov atom not found"))
    assert "moov atom not found" in str(e.value)


def test_a_tool_that_succeeds_but_produces_nothing_is_still_a_failure():
    """Exit code zero with an empty file would otherwise be uploaded as valid audio."""
    with pytest.raises(speech.SpeechError):
        A.extract(CLIP, "/usr/bin/ffmpeg", run=FakeRun(writes=b""))


def test_temporary_files_do_not_survive_the_call():
    run = FakeRun()
    A.extract(CLIP, "/usr/bin/ffmpeg", run=run)
    import os
    for path in run.calls[0]:
        if path.startswith("/") and ("." in os.path.basename(path)):
            assert not os.path.exists(path), f"{path} was left behind"


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
