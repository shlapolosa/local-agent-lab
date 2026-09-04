"""Extract the audio track from a recording, because a meeting recording is VIDEO.

Every speech provider surveyed takes audio containers only, and a conferencing platform hands out
`.mp4`. So this step is not a detail — without it the pipeline cannot run at all. It lives on the
speech service rather than in a workload for the same reason the credential does: a workload holds
references, the substrate holds capabilities.

A HOST TOOL does the work, exactly as document rendering elsewhere in the lab depends on an office
suite. That makes it an optional capability with an honest failure: no tool configured means a video
input is refused with a sentence naming the setting, never a stack trace, and audio input keeps
working regardless.

Which tool is a REGISTRY, not a branch: `ffmpeg` in a container, `afconvert` on macOS where it is
built in and needs no install. Adding a third is one entry. Both are asked to COPY the existing
audio stream rather than re-encode it, since a conferencing recording is already AAC — that makes
extraction near-instant and lossless.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Callable

from lab.core.speech import (AudioClip, SpeechError, SpeechUnavailable, SpeechUnsupportedMedia)

__all__ = ["VIDEO_CONTAINERS", "EXTRACTORS", "OUT_SUFFIX", "needs_extraction", "extract", "SETTING"]

SETTING = "AUDIO_EXTRACT_BIN"
OUT_SUFFIX = ".m4a"          # AAC in an MP4 audio container: what a conferencing recording already is

VIDEO_CONTAINERS = (".mp4", ".mov", ".mkv", ".avi", ".m4v", ".wmv", ".flv", ".3gp", ".webm")

# basename of the tool -> how to invoke it (input, output). Copy the stream where the tool can.
EXTRACTORS: dict[str, Callable[[str, str, str], list[str]]] = {
    "ffmpeg": lambda exe, src, dst: [exe, "-nostdin", "-y", "-i", src, "-vn", "-acodec", "copy", dst],
    # afconvert cannot stream-copy, but it is built into macOS, so a developer needs no install.
    "afconvert": lambda exe, src, dst: [exe, "-f", "m4af", "-d", "aac", src, dst],
}


def needs_extraction(suffix: str, accepted: tuple[str, ...]) -> bool:
    """Whether this container must have its audio extracted before a provider will take it.

    Acceptance wins over appearance: `.webm` carries video, but if the provider takes it we leave it
    alone rather than re-encode for nothing. Anything that is neither accepted audio nor a known
    video container is refused here, so a wrong file never costs a subprocess or an upload.
    """
    suffix = (suffix or "").lower()
    if suffix in accepted:
        return False
    if suffix in VIDEO_CONTAINERS:
        return True
    raise SpeechUnsupportedMedia(suffix or "(no extension)", accepted)


def extract(clip: AudioClip, tool: str, run=subprocess.run) -> AudioClip:
    """The audio of `clip`, as a clip a provider will accept. `run` is injected so tests never shell out."""
    if not (tool or "").strip():
        raise SpeechUnavailable(
            "transcription",
            f"this recording is video and no audio-extraction tool is configured ({SETTING} is unset)",
            f"set {SETTING} to ffmpeg (or afconvert on macOS), or submit audio rather than video")
    name = os.path.basename(tool.strip())
    build = EXTRACTORS.get(name)
    if build is None:
        raise SpeechUnavailable(
            "transcription", f"{name!r} is not an audio-extraction tool this lab knows",
            f"set {SETTING} to one of {sorted(EXTRACTORS)}, or add it to the extractor registry")

    stem = os.path.splitext(os.path.basename(clip.name))[0] or "audio"
    tmp = tempfile.mkdtemp(prefix="lab-audio-")
    src = os.path.join(tmp, f"in{os.path.splitext(clip.name)[1] or '.bin'}")
    dst = os.path.join(tmp, f"out{OUT_SUFFIX}")
    try:
        with open(src, "wb") as fh:
            fh.write(clip.data)
        result = run(build(tool, src, dst), capture_output=True, text=True, timeout=900)
        if getattr(result, "returncode", 1) != 0:
            raise SpeechError(f"audio extraction failed ({name}): "
                              f"{(getattr(result, 'stderr', '') or 'no error text').strip()[:300]}")
        data = open(dst, "rb").read() if os.path.exists(dst) else b""
        if not data:
            # exit code 0 and nothing produced: without this the empty file is uploaded as audio.
            raise SpeechError(f"audio extraction produced no audio ({name}) — "
                              "the recording may have no audio track")
        # The original name is kept (with the audio suffix) so a log line still says which meeting.
        return AudioClip(name=f"{stem}{OUT_SUFFIX}", data=data, seconds=clip.seconds)
    finally:
        for path in (src, dst):
            if os.path.exists(path):
                os.remove(path)
        if os.path.isdir(tmp):
            os.rmdir(tmp)
