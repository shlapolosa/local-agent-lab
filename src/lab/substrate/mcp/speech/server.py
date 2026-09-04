"""speech-mcp — the SPEECH port as governed tools (port 9600, /mcp).

Why a server, and why here: a speech provider needs a long-lived credential and, for a real meeting,
a large upload. A workload must never hold either (agents never hold tool credentials — the gateway
injects them), so both live HERE, in the substrate, and every call goes gateway -> this server:
granted per team, allow-listed per tool, metered, PII-scanned and traced like any other call.

VENDOR-NEUTRAL BY CONSTRUCTION. The alias is `speech_mcp` and every tool is `speech_*`
(`lab.platform.contracts.SpeechTools`); the provider is named only by the SERVICE and by the adapter
the container resolves. This file talks to `lab.core.speech.Transcriber` — the domain port — and
never to a provider SDK, so a second provider is one entry in
`lab.substrate.container.SPEECH_PROVIDERS` plus its adapter, with no change here and none in any
caller. That matters more than usual here: the first adapter was chosen on evidence that is thin and
partly unverifiable, so being able to swap it cheaply is the point.

WORDS AND SPEAKER LABELS, NEVER A SUMMARY. This server does not summarise, and the absence is
deliberate. Minutes, decisions and keywords are produced by the lab's own governed model through the
gateway, so "the vendor does not summarise our meetings" is a property of the architecture and not a
promise in a document.

CONTENT BY REFERENCE, DIGEST INLINE. Audio arrives as an `art://` reference the caller never opens;
the full segment timeline goes back as another reference. What comes back inline is only what a
caller needs in hand — the anonymous speaker digest, the duration, whether more than one language
was recognised, and anything the provider would not honour. An hour of speech is not a tool result.

VIDEO IN, AUDIO OUT. A meeting recording is video and providers take audio, so extraction happens
here, behind the port, using a host tool. It is an OPTIONAL capability: without the tool, audio
still transcribes and video is refused with a sentence naming the setting.

NO SPAN CARRIES SPEECH. Tool arguments and results cross the gateway, where the PII guardrail scans
them; span attributes do NOT — they go straight to an OTLP endpoint that in this lab is public and
unauthenticated. A transcript is the most sensitive thing this lab handles, so span attributes carry
COUNTS, DURATIONS and SHAPES only: never a word of what was said, never a speaker label paired with
anything identifying, never a file name. Do not "helpfully" add text back.
"""
from __future__ import annotations

import functools
import json

from fastmcp.exceptions import ToolError

from lab.core.speech import AudioClip, SpeechError, Transcript
from lab.platform import config
from lab.platform.contracts import SpeechTools
from lab.substrate.mcp.speech import audio as audio_tools
from lab.substrate.mcp.speech import munsit_map
from lab.substrate.mcpserver import LabServer, span

SERVICE = "speech-mcp"
server = LabServer(SERVICE, config.SPEECH_MCP_PORT)

MAX_SAMPLE_CHARS = 240          # a sample is evidence for a human, not a transcript excerpt


def governed(fn):
    """`@server.tool()` plus the ONE failure path: a typed refusal leaves as its SENTENCE — what is
    unavailable, why, and the step that fixes it — so no caller relays a bare provider status."""
    @functools.wraps(fn)
    def call(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SpeechError as refused:
            span().set_attribute("speech.refused", getattr(refused, "capability", "") or "")
            raise ToolError(refused.sentence) from refused
    return server.tool()(call)


def _clip(ref: str) -> AudioClip:
    """Read one `art://` reference out of the upload store as a clip.

    The store is reached HERE and never by the caller: a workload holds references, the substrate
    holds credentials. Length is left unknown — reading it would need the same host tool extraction
    uses, and the provider is the authority on whether a clip is too long anyway.
    """
    blob = server.uploads().get(ref)
    data = blob["body"] if isinstance(blob, dict) else blob
    name = (blob.get("name") if isinstance(blob, dict) else "") or ref.rstrip("/").split("/")[-1]
    return AudioClip(name=name, data=data)


def _digest(t: Transcript) -> list[dict]:
    """The anonymous speaker digest: what a human needs to tell the voices apart, and nothing more.

    Samples are truncated because their job is recognition, not reading, and a long quote in a tool
    result is a long quote in a gateway log.
    """
    return [{"label": s.label, "seconds": round(s.seconds, 2), "turns": s.turns,
             "samples": [x[:MAX_SAMPLE_CHARS] for x in t.samples_for(s.label)]}
            for s in t.speakers]


@governed
def speech_capabilities(deep: bool = False) -> dict:
    """What this deployment's speech provider will actually serve, and why not where it will not.

    One entry per capability — transcription, diarization, code_switching, timestamps, vocabulary,
    speaker_hint — each either available or carrying a sentence naming the reason and the remedy.
    Read this before designing around a feature: providers differ sharply on whether they transcribe
    speech that switches language mid-sentence, and on whether they accept a speaker-count hint,
    which is the single most useful lever for a meeting recorded on one microphone in a room.
    `deep=true` asks for a live check where one is cheap; where every call costs credits and an
    upload, the provider says so rather than pretending a shallow answer was verified."""
    caps = server.speech().capabilities(deep=deep)
    available = sorted(k for k, v in caps.items() if v is None)
    span().set_attributes({"speech.available": len(available), "speech.total": len(caps)})
    return {"provider_configured": "configuration" not in {getattr(v, "capability", "") for v in caps.values()},
            "available": available,
            "unavailable": {k: v.to_dict() for k, v in caps.items() if v is not None},
            "extraction_tool": bool(config.AUDIO_EXTRACT_BIN),
            "accepted_media": list(munsit_map.ACCEPTED_MEDIA)}


@governed
def speech_transcribe(audio_ref: str, languages: list[str] | None = None, diarize: bool = True,
                      speaker_count: int | None = None,
                      vocabulary: list[str] | None = None) -> dict:
    """Transcribe a recording into timed, speaker-labelled segments.

    `audio_ref` is an `art://<id>/<name>` reference to audio OR video already in the lab's upload
    store — never a path, never a URL, never the bytes. If it is video, the audio track is extracted
    here first; a meeting recording normally is.

    `languages` is a HINT of what is expected, and it is the most important argument. Pass every
    language the meeting actually uses, for example Arabic and English together for speakers who
    switch mid-sentence: that is what selects a provider model able to transcribe the switch instead
    of translating or transliterating it. Passing a single language when two are spoken is the
    commonest way to get fluent, confident, wrong text. An unservable combination is refused rather
    than quietly downgraded.

    `speaker_count`, when the organiser knows it, helps a recording made on one device in a room.
    Providers that do not support it accept and ignore it rather than failing — check
    speech_capabilities to see which this is.

    `vocabulary` biases toward names a general model will not know. Some providers refuse it
    together with a mixed-language model; when that happens the mixed language wins and the loss is
    reported in `warnings` rather than hidden.

    Returns the full timeline BY REFERENCE (`transcript_ref`) plus what a caller needs in hand: the
    anonymous speaker digest with sample utterances, the duration, the languages recognised, and
    `code_switched`. Speaker labels are ANONYMOUS and meaningful only within this one result — they
    are not stable across two calls, so mapping them to real people is a separate, human-gated step.
    Note that a provider which reports no per-segment language will show `languages: []` and
    `code_switched: false` even on mixed audio: that means "not reported", never "did not happen"."""
    langs = tuple(str(x) for x in (languages or []))
    vocab = tuple(str(x) for x in (vocabulary or []))
    clip = _clip(audio_ref)

    if audio_tools.needs_extraction(clip.suffix, munsit_map.ACCEPTED_MEDIA):
        clip = audio_tools.extract(clip, config.AUDIO_EXTRACT_BIN)
        span().set_attribute("speech.extracted", True)

    transcriber = server.speech()
    t = transcriber.transcribe(clip, languages=langs, diarize=diarize,
                               speaker_count=speaker_count, vocabulary=vocab)
    ref = server.artifacts().put(
        f"{audio_ref.rstrip('/').split('/')[-1]}.segments.json",
        json.dumps({"duration": t.duration, "model": t.model, "provider": t.provider,
                    "segments": [{"speaker": s.speaker, "start": s.start, "end": s.end,
                                  "text": s.text, "language": s.language} for s in t.segments]},
                   ensure_ascii=False).encode("utf-8"),
        "application/json")
    # counts, durations and shapes only — never a word of what was said
    span().set_attributes({"speech.segments": len(t.segments), "speech.speakers": len(t.speakers),
                           "speech.duration": t.duration, "speech.code_switched": t.code_switched,
                           "speech.diarize": diarize})
    return {"transcript_ref": ref, "duration": t.duration, "model": t.model,
            "speakers": _digest(t), "languages": list(t.languages),
            "code_switched": t.code_switched,
            "warnings": list(getattr(transcriber, "warnings", lambda *a: ())(langs, vocab)),
            "read_with": "storage_get"}


# the catalogue is the contract: registering under any other name fails the parity test
assert {speech_capabilities.__name__, speech_transcribe.__name__} == set(SpeechTools.names())


if __name__ == "__main__":
    print(f"speech-mcp: provider = {config.SPEECH_PROVIDER}, "
          f"extraction tool = {config.AUDIO_EXTRACT_BIN or 'NONE (video will be refused)'}; "
          f"call {SpeechTools.capabilities} to see what it actually serves")
    server.serve()
