"""MAPPER: Soniox payloads -> `lab.core.speech`. Pure; no I/O, no credential.

This is the only provider in the bake-off that answers BOTH of the lab's requirements in ONE call:
`enable_speaker_diarization` together with `translation: {type: one_way, target_language: en}`
returns a single token stream carrying the original speech AND its translation, with the `speaker`
field preserved on both, distinguished by `translation_status`.

That unified stream is why this mapper has a `want` selector rather than returning one fixed thing.
The domain port returns ONE transcript, and the renderings are genuinely different artifacts: the
verbatim record is the audit trail, the English one is what minutes should be written from. So the
adapter asks for the rendering it wants, and the bake-off runs this provider twice and compares them
as two entries. No port change, and the run keeps both. There are THREE renderings, not two — see
`WANTED`; the third exists because a provider's translated half alone is a side-by-side column and
asking for it by mistake cost this lane 90% of a meeting.
"""
from __future__ import annotations

from typing import Any, NamedTuple

from lab.core.speech import SpeechError, Transcript
from lab.substrate.mcp.speech.tokenmap import RENDERED, Tok, group_into_segments

__all__ = ["PROVIDER", "MODEL_DEFAULT", "to_transcript", "request_body", "NONE", "ORIGINAL",
           "TRANSLATION", "ENGLISH", "WANTED", "TERMINAL", "ACCEPTED_MEDIA"]

PROVIDER = "soniox"
MODEL_DEFAULT = "stt-async-v5"
#: The three values `translation_status` actually takes, measured against the live API on
#: 12 Sep 2026 over one 91.8-second bilingual meeting (435 tokens): `none` 335, `original` 53,
#: `translation` 47. The mapper knew about two of them, which is why a mostly-English meeting
#: rendered as 21 words — `none`, the bulk, matched neither half.
NONE, ORIGINAL, TRANSLATION = "none", "original", "translation"
#: ...and the three renderings those make possible. ENGLISH is the one a person reads.
ENGLISH = "english"
WANTED = {
    ORIGINAL:    {NONE, ORIGINAL},        # the verbatim record: what was said, in the language said
    ENGLISH:     {NONE, TRANSLATION},     # fully English: untranslated speech + rendered Arabic
    TRANSLATION: {TRANSLATION},           # only what was rendered — a side-by-side column, not a read
}
#: Soniox emits SUB-WORD tokens carrying their own leading space, so they concatenate rather than
#: being stripped and re-spaced. See tokenmap.group_into_segments.
CONCAT = True
TERMINAL = {"completed", "error"}
ACCEPTED_MEDIA = (".aac", ".flac", ".m4a", ".mp3", ".mp4", ".mpeg", ".ogg", ".opus", ".wav",
                  ".webm")


def request_body(file_id: str = "", audio_url: str = "", languages: tuple[str, ...] = (),
                 diarize: bool = True, translate_to: str = "") -> dict:
    """The create-transcription payload.

    `language_hints` takes the WHOLE hint, plural — this provider is one of the few that accepts a
    list, which is exactly what the port promises and what makes mid-sentence switching work.

    `enable_language_identification` is NOT optional here, because the port requires the recognised
    language PER SEGMENT — without it this provider returns no `language` field at all, and the
    consequences went well past a missing column (measured 12 Sep 2026, the same recording twice):
    `tokenmap` breaks a speaker's run at a change of language, so with the field absent the
    code-switch this lab exists to make visible was invisible; and the provider ALSO stopped marking
    the Arabic as `original`, returning it under `translation_status: none` in Arabic script with a
    `translation` run after it — a shape in which nothing in the payload says which words the
    rendering replaces. With the flag on, the same audio came back clean: 335 `none`/en, 53
    `original`/ar, 47 `translation`/en, strictly alternating. One missing boolean was the whole
    defect; no heuristic recovers what it suppresses.
    """
    if bool(file_id) == bool(audio_url):
        raise SpeechError("give this provider a file id or an audio url, not both and not neither")
    body: dict[str, Any] = {"model": MODEL_DEFAULT,
                            "enable_speaker_diarization": bool(diarize),
                            "enable_language_identification": True}
    body["file_id" if file_id else "audio_url"] = file_id or audio_url
    hints = [l.strip().lower().split("-")[0] for l in languages if (l or "").strip()]
    if hints:
        body["language_hints"] = sorted(set(hints))
    if translate_to:
        body["translation"] = {"type": "one_way", "target_language": translate_to}
    return body


def to_transcript(payload: Any, want: str = ORIGINAL, model: str = MODEL_DEFAULT,
                  duration: float = 0.0) -> Transcript:
    """One rendering of the unified token stream -> a domain `Transcript`.

    Three renderings, because the stream carries three kinds of token (see WANTED):

      ORIGINAL     `none` + `original` — the verbatim record, in the languages actually spoken.
      ENGLISH      `none` + `translation` — every word in English: the speech that needed no
                   translation, plus the rendering of the speech that did. This is what a person
                   reads and what minutes should be written from.
      TRANSLATION  `translation` alone — only the rendered spans. Useful as a column in a
                   side-by-side, useless as a transcript: on a mostly-English meeting it returns
                   the handful of sentences that happened to contain Arabic.

    A token with no `translation_status` is `none` and belongs to BOTH of the first two — it is
    untranslated speech, which is as much part of the verbatim record as it is of the English one.

    Three properties of this stream the published schema does not state, all measured live:

    1. **A rendering carries NO timestamps** (`start_ms: 0, end_ms: 0`) and is emitted in stream
       order right after the run it renders, so it BORROWS that run's span. Without the borrow the
       English rendering is a timeline that rewinds to zero once per translated span and the domain
       model refuses it outright; the translation-only column does NOT throw, which is worse — every
       segment sits at 0.0, so nothing is out of order and a column that cannot be aligned in time
       looks correct.
    2. **The borrowed span is the run IMMEDIATELY before** — one contiguous group of the same status
       AND the same speaker. Keyed on status alone, two consecutive translated turns by different
       speakers pool into one span and each rendering is laid over the other speaker's talk, which
       raises nothing and doubles both speakers' share of the recording.
    3. **A rendering must not share a segment with speech.** Both carry the same speaker and, once
       translated, the same language, so `Tok.kind` is the only thing holding them apart. A segment
       is quoted to a human at the speaker-naming approval as words that speaker said.

    An `original` run that no rendering follows is KEPT in the English transcript rather than
    dropped. Its script then shows in the digest, which is a visible imperfection; silently losing
    speech from the transcript minutes are written from is not.
    """
    if not isinstance(payload, dict):
        raise SpeechError(f"unexpected response from {PROVIDER}: {type(payload).__name__}")
    keep = WANTED.get(want)
    if keep is None:
        raise SpeechError(f"unknown Soniox rendering {want!r} — expected one of {sorted(WANTED)}")
    runs = _runs(payload.get("tokens") or [])
    toks: list[Tok] = []
    for i, run in enumerate(runs):
        before = runs[i - 1] if i and runs[i - 1].status != TRANSLATION else None
        after = runs[i + 1] if i + 1 < len(runs) else None
        if run.status == TRANSLATION:
            if TRANSLATION not in keep:
                continue
            span = run.span if run.span != (0.0, 0.0) else (before.span if before else run.span)
            toks += [t._replace(start=span[0], end=span[1], kind=RENDERED) for t in run.toks]
            continue
        if run.status in keep:
            toks += run.toks
        elif (run.status == ORIGINAL and want == ENGLISH
              and not (after is not None and after.status == TRANSLATION)):
            toks += run.toks                      # nothing rendered it; losing it would be worse
    segments = group_into_segments(toks, concat=CONCAT)
    try:
        return Transcript(segments=segments,
                          duration=duration or _num(payload.get("audio_duration_ms")) / 1000.0
                          or round(max((s.end for s in segments), default=0.0), 3),
                          model=model, provider=f"{PROVIDER}-{want}")
    except ValueError as e:
        # The port promises a TYPED refusal. Left as a ValueError this escapes the adapter, the
        # governed tool's `except SpeechError` and the span's `speech.refused` attribute, and the
        # workload fails with nothing a person can act on.
        raise SpeechError(f"{PROVIDER} returned a stream this rendering cannot be placed on a "
                          f"timeline: {e}") from e


class _Run(NamedTuple):
    """A contiguous group of tokens sharing a `translation_status` AND a speaker."""

    status: str
    speaker: str
    toks: tuple[Tok, ...]
    span: tuple[float, float]


def _runs(raw: Any) -> tuple[_Run, ...]:
    """The stream, grouped. Its ORDER is the only thing that says which speech a rendering renders."""
    out: list[_Run] = []
    cur: list[Tok] = []
    status = speaker = ""
    for t in raw:
        if not isinstance(t, dict):
            continue
        st = str(t.get("translation_status") or NONE)
        tok = Tok(text=str(t.get("text") or ""),
                  start=_s(t, "start_ms", "start"), end=_s(t, "end_ms", "end"),
                  speaker=_label(t.get("speaker")), language=str(t.get("language") or ""))
        if cur and (st != status or tok.speaker != speaker):
            out.append(_close(status, speaker, cur))
            cur = []
        status, speaker = st, tok.speaker
        cur.append(tok)
    if cur:
        out.append(_close(status, speaker, cur))
    return tuple(out)


def _close(status: str, speaker: str, toks: list[Tok]) -> _Run:
    timed = [t for t in toks if (t.start, t.end) != (0.0, 0.0)]
    span = (min(t.start for t in timed), max(t.end for t in timed)) if timed else (0.0, 0.0)
    return _Run(status, speaker, tuple(toks), span)


def _s(tok: dict, ms_key: str, s_key: str) -> float:
    """Milliseconds when the provider sends them, seconds when it sends those — one place, so the
    two cannot be mixed inside one transcript."""
    if tok.get(ms_key) is not None:
        return round(_num(tok.get(ms_key)) / 1000.0, 3)
    return round(_num(tok.get(s_key)), 3)


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _label(speaker: Any) -> str:
    s = str(speaker or "").strip()
    if not s:
        return "SPEAKER_00"
    return f"SPEAKER_{int(s):02d}" if s.isdigit() else s
