#!/usr/bin/env python
"""Run ONE recording through every configured speech provider and write the artifacts to compare.

A PROBE, not production code: it holds credentials, it costs money per run, and it exists to answer
one procurement question — which provider should transcribe this lab's meetings. What it must never
be is the place a decision rule hides, so the scoring it prints lives in `lab.core.speech.compare`
and is unit-tested there; this file only orchestrates and writes files.

    .venv/bin/python scripts/speech_bakeoff.py var/inputs/meeting.mp4 \
        [--reference teams.vtt] [--providers munsit,soniox,soniox-en] [--languages ar,en]

Every provider is optional. One without its API key is SKIPPED by name with the setting it wants,
so a lab holding a single credential still produces a usable run instead of an error. Video is
converted to audio first when the provider will not take a container — the same helper the workload
uses, so the bake-off measures the provider rather than our upload.

Artifacts land in var/out/bakeoff/<timestamp>/:
    <provider>.json     the full transcript, every segment, as returned
    <provider>.md       the same thing readable, one speaker turn per line
    comparison.md       every provider side by side, aligned on the TIMELINE
    digests.json        the numbers: script mix, speakers, coverage, words, seconds
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lab.core.speech import AudioClip, SpeechError, Transcript, Segment      # noqa: E402
from lab.core.speech import compare                                          # noqa: E402
from lab.platform import config                                              # noqa: E402
from lab.substrate import container                                          # noqa: E402
from lab.substrate.mcp.speech import audio as audiotool                      # noqa: E402
from lab.substrate.mcp.speech.http import UrllibTransport                    # noqa: E402

DEFAULT_LANGUAGES = ("ar", "en")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("audio", help="the recording: any local audio or video file")
    p.add_argument("--providers", default="", help="comma-separated; default = every registered one")
    p.add_argument("--languages", default=",".join(DEFAULT_LANGUAGES),
                   help="the language HINT, plural — several means 'detect', never 'pick the first'")
    p.add_argument("--reference", default="",
                   help="a .vtt to include as a column (Microsoft's own transcript is the honest "
                        "yardstick for a Teams meeting, and it costs nothing)")
    p.add_argument("--repeat", type=int, default=1,
                   help="run each provider N times. Earned by measurement, not caution: the same "
                        "recording through the same model produced Arabic script on one run and "
                        "Latin on another, so a single run cannot tell a provider's behaviour from "
                        "one sample of it")
    p.add_argument("--out", default=str(ROOT / "var/out/bakeoff"))
    args = p.parse_args()

    languages = tuple(x.strip() for x in args.languages.split(",") if x.strip())
    names = [x.strip() for x in args.providers.split(",") if x.strip()] or \
        sorted(container.SPEECH_PROVIDERS)
    source = Path(args.audio)
    if not source.is_file():
        print(f"no such file: {source}", file=sys.stderr)
        return 2

    outdir = Path(args.out) / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    outdir.mkdir(parents=True, exist_ok=True)
    clip = AudioClip(source.name, source.read_bytes())
    print(f"{source.name}  {len(clip.data) / 1e6:.1f} MB  ->  {outdir}\n")

    # RECORDED, because it is not a detail: the same recording through the same model returned 0%
    # Arabic script via afconvert (which re-encodes) and 75% via ffmpeg (which stream-copies), and
    # the re-encode also lost a THIRD of the words. A comparison that does not say how the audio was
    # prepared is not reproducible and may be measuring this lab rather than the provider.
    extractor = config.AUDIO_EXTRACT_BIN or "afconvert"
    results: dict[str, Transcript] = {}
    digests: dict[str, dict] = {"_run": {"source": source.name, "extractor": extractor,
                                         "languages": list(languages), "repeat": args.repeat}}
    print(f"extraction: {extractor}")

    if args.reference:
        ref = parse_vtt(Path(args.reference).read_text(encoding="utf-8", errors="replace"))
        results["reference"] = ref
        digests["reference"] = {**compare.digest(ref), "seconds_taken": 0.0, "note": "not a provider"}
        write_one(outdir, "reference", ref)
        print(f"  reference    {len(ref.segments):>3} segments  (the tenant's own transcript)")

    for name in [f"{n}#{i + 1}" if args.repeat > 1 else n
                 for n in names for i in range(args.repeat)]:
        started = time.monotonic()
        try:
            got = run_one(name.split("#")[0], clip, languages, outdir, label=name)
        except Skipped as s:
            digests[name] = {"skipped": str(s)}
            print(f"  {name:<12} SKIPPED — {s}")
            continue
        except (SpeechError, Exception) as e:            # noqa: BLE001 — one provider must not stop the rest
            digests[name] = {"failed": f"{type(e).__name__}: {e}"}
            print(f"  {name:<12} FAILED  — {type(e).__name__}: {e}")
            continue
        took = round(time.monotonic() - started, 1)
        results[name] = got
        digests[name] = {**compare.digest(got), "seconds_taken": took}
        write_one(outdir, name, got)
        d = digests[name]
        print(f"  {name:<12} {d['spoken_segments']:>3} segments  {d['speakers']} speaker(s)  "
              f"{d['words']:>4} words  arabic {d['arabic_share']:.0%}  {took}s")

    (outdir / "digests.json").write_text(json.dumps(digests, indent=2, ensure_ascii=False) + "\n",
                                         encoding="utf-8")
    (outdir / "comparison.md").write_text(comparison(results, digests), encoding="utf-8")
    print(f"\n{outdir}/comparison.md")
    return 0


class Skipped(RuntimeError):
    """This provider was not configured — a fact to report, never a failure to raise."""


class Recording:
    """The injected transport, wrapped so every RESPONSE is kept beside the transcript.

    This exists because of how three Soniox mapping defects survived review for a week: the fixtures
    had been typed from the published schema, so the code and the tests shared the same three wrong
    assumptions about the payload and agreed with each other. Nothing in the repo held a real
    response to check against. One `write_text` in the probe closes that — a bake-off run now leaves
    `<provider>.raw.json`, which is where the next fixture should come from.

    Responses only. The request body is the AUDIO (megabytes) and the headers carry the API key, so
    neither is recorded — the method, url and status are enough to read the exchange.
    """

    def __init__(self, inner, dest: Path) -> None:
        self._inner, self._dest, self._seen = inner, dest, []

    def __call__(self, method, url, headers, body=None, timeout=None):
        r = self._inner(method, url, headers, body, timeout)
        self._seen.append({"method": method, "url": url, "status": r.status, "body": r.body})
        return r

    def save(self) -> None:
        if self._seen:
            self._dest.write_text(json.dumps(self._seen, indent=1, ensure_ascii=False) + "\n",
                                  encoding="utf-8")


def run_one(name: str, clip: AudioClip, languages: tuple[str, ...], outdir: Path,
            label: str = "") -> Transcript:
    tape = Recording(UrllibTransport(), outdir / f"{label or name}.raw.json")
    box = container.speech_transcriber(name, transport=tape)
    try:
        unavailable = box.capabilities().get("transcription")
        if unavailable is not None:
            raise Skipped(str(unavailable))
        ready = as_audio(clip, box)
        for warning in getattr(box, "warnings", lambda **_k: ())(languages=languages):
            print(f"     ! {warning}")
        return box.transcribe(ready, languages=languages, diarize=True)
    finally:
        # In `finally` deliberately: the payload is most valuable on the run that FAILED to map.
        tape.save()


def as_audio(clip: AudioClip, box) -> AudioClip:
    """Convert a video container when THIS provider will not take one — the same helper the
    workload uses, so what is measured is the provider and not our upload.

    Each adapter module imports its own mapper as `M`, and the mapper owns `ACCEPTED_MEDIA`; asking
    the adapter's module is how one probe stays correct as providers are added, without a second
    table of who accepts what.
    """
    import importlib
    mapper = getattr(importlib.import_module(type(box).__module__), "M", None)
    accepted = tuple(getattr(mapper, "ACCEPTED_MEDIA", ()) or ())
    if accepted and audiotool.needs_extraction(clip.suffix, accepted):
        # The tool is CONFIGURED, not hardcoded: macOS ships `afconvert` and a container ships
        # ffmpeg, and a probe that insisted on one of them would fail on the other machine.
        return audiotool.extract(clip, tool=config.AUDIO_EXTRACT_BIN or "afconvert")
    return clip


# ---------------------------------------------------------------------- artifacts
def write_one(outdir: Path, name: str, t: Transcript) -> None:
    (outdir / f"{name}.json").write_text(json.dumps({
        "provider": t.provider, "model": t.model, "duration": t.duration,
        "digest": compare.digest(t),
        "segments": [{"start": s.start, "end": s.end, "speaker": s.speaker,
                      "language": s.language, "text": s.text} for s in t.segments],
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [f"# {name}", "", f"`{t.provider}` · model `{t.model}` · {t.duration:.1f}s", ""]
    lines += [f"**{s.speaker}** [{s.start:7.2f}] {s.text}" for s in t.spoken]
    (outdir / f"{name}.md").write_text("\n\n".join(lines) + "\n", encoding="utf-8")


def comparison(results: dict[str, Transcript], digests: dict[str, dict]) -> str:
    cols = list(results)
    run = digests.get("_run", {})
    out = ["# Speech provider bake-off", "",
           f"`{run.get('source', '')}` · audio extracted with `{run.get('extractor', '')}` · "
           f"language hint `{', '.join(run.get('languages', []))}`", "",
           "## What each provider returned", "",
           "| provider | segments | speakers | words | arabic share | coverage | seconds |",
           "|---|---|---|---|---|---|---|"]
    for name, d in digests.items():
        if name.startswith("_"):
            continue
        if "skipped" in d or "failed" in d:
            out.append(f"| {name} | — | — | — | — | — | {d.get('skipped') or d.get('failed')} |")
            continue
        out.append(f"| {name} | {d['spoken_segments']} | {d['speakers']} | {d['words']} | "
                   f"{d['arabic_share']:.0%} | {d['coverage']:.0%} | {d.get('seconds_taken', '')} |")
    out += ["",
            "**arabic share** is the fraction of LETTERS written in Arabic script. It is the "
            "headline number because the failure this lab hit is orthographic, not semantic: a "
            "provider can hear English perfectly and write it in Arabic letters. For a meeting "
            "held in English it should be near 0% apart from genuine Arabic phrases.", "",
            "## Side by side, aligned on the timeline", ""]
    if cols:
        out += ["| t | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
        for row in compare.side_by_side(results):
            cells = [row["by_provider"].get(c, "").replace("|", "\\|") for c in cols]
            out.append(f"| {row['start']:.1f} | " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------- the reference column
CUE = re.compile(r"(?P<h1>\d+):(?P<m1>\d+):(?P<s1>[\d.]+)\s*-->\s*(?P<h2>\d+):(?P<m2>\d+):(?P<s2>[\d.]+)")
VOICE = re.compile(r"<v\s+([^>]+)>(.*?)</v>", re.S)


def parse_vtt(text: str) -> Transcript:
    """A WebVTT transcript -> the domain's shape, so the tenant's own answer is just another column.

    Microsoft names the speaker in a `<v ...>` tag, which is a REAL identity rather than an
    anonymous label — the one column here that did not need a human to attribute it.
    """
    segments, start, end = [], None, None
    for line in text.splitlines():
        cue = CUE.search(line)
        if cue:
            start = _secs(cue.group("h1"), cue.group("m1"), cue.group("s1"))
            end = _secs(cue.group("h2"), cue.group("m2"), cue.group("s2"))
            continue
        voice = VOICE.search(line)
        if voice and start is not None:
            segments.append(Segment(start=start, end=end, text=voice.group(2).strip(),
                                    speaker=voice.group(1).strip() or "SPEAKER_00"))
            start = None
    return Transcript(segments=tuple(segments),
                      duration=round(max((s.end for s in segments), default=0.0), 3),
                      model="TranscriptV2", provider="reference")


def _secs(h: str, m: str, s: str) -> float:
    return round(int(h) * 3600 + int(m) * 60 + float(s), 3)


if __name__ == "__main__":
    raise SystemExit(main())
