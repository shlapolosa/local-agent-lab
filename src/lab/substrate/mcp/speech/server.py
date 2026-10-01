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

from lab.core.meetings.model import Speakers
from lab.core.speech import AudioClip, SpeechError, Transcript
from lab.core.speech import voiceprint as V
from lab.platform import config
from lab.substrate import container
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
def speech_capabilities(deep: bool = False, provider: str = "") -> dict:
    """What this deployment's speech provider will actually serve, and why not where it will not.

    One entry per capability — transcription, diarization, code_switching, timestamps, vocabulary,
    speaker_hint — each either available or carrying a sentence naming the reason and the remedy.
    Read this before designing around a feature: providers differ sharply on whether they transcribe
    speech that switches language mid-sentence, and on whether they accept a speaker-count hint,
    which is the single most useful lever for a meeting recorded on one microphone in a room.
    `provider` asks about ONE named provider instead of the configured one, and `providers` in the
    answer lists every one this lab can be asked for — which is what makes choosing a lane possible
    without running it first. `deep=true` asks for a live check where one is cheap; where every call costs credits and an
    upload, the provider says so rather than pretending a shallow answer was verified."""
    # Symmetric with `speech_transcribe`: a caller choosing between LANES must be able to ask what
    # each one serves. Without this, capabilities could only ever describe the configured provider,
    # and every other lane's abilities would be discoverable only by running it.
    box = server.speech_named(provider=provider) if provider else server.speech()
    caps = box.capabilities(deep=deep)
    available = sorted(k for k, v in caps.items() if v is None)
    span().set_attributes({"speech.available": len(available), "speech.total": len(caps)})
    return {"provider_configured": "configuration" not in {getattr(v, "capability", "") for v in caps.values()},
            "available": available,
            "unavailable": {k: v.to_dict() for k, v in caps.items() if v is not None},
            "provider": provider or config.SPEECH_PROVIDER,
            "providers": sorted(container.SPEECH_PROVIDERS),   # what a lane may name
            "extraction_tool": bool(config.AUDIO_EXTRACT_BIN),
            "accepted_media": list(munsit_map.ACCEPTED_MEDIA)}


@governed
def speech_transcribe(audio_ref: str, languages: list[str] | None = None, diarize: bool = True,
                      speaker_count: int | None = None, vocabulary: list[str] | None = None,
                      provider: str = "") -> dict:
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

    `provider` names WHICH speech provider transcribes this recording — one of the lab's registered
    providers. Omit it for the deployment's configured one, which is what a lab running a single
    provider always does. It exists so the same recording can be run through several providers in
    their own lanes, each producing its own transcript to be compared; the returned `provider` says
    which one answered, and it is never the caller's credential that reaches the vendor.

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

    transcriber = server.speech_named(provider=provider) if provider else server.speech()
    t = transcriber.transcribe(clip, languages=langs, diarize=diarize,
                               speaker_count=speaker_count, vocabulary=vocab)
    # The lane is IN THE NAME. Four providers produce four transcripts of one recording, and a
    # person reading a list of refs — or a file delivered beside the recording — must be able to see
    # which is which without opening it.
    lane = (t.provider or provider or "").strip()
    ref = server.artifacts().put(
        f"{audio_ref.rstrip('/').split('/')[-1]}{'.' + lane if lane else ''}.segments.json",
        json.dumps({"duration": t.duration, "model": t.model, "provider": t.provider,
                    "segments": [{"speaker": s.speaker, "start": s.start, "end": s.end,
                                  "text": s.text, "language": s.language} for s in t.segments]},
                   ensure_ascii=False).encode("utf-8"),
        "application/json")
    # counts, durations and shapes only — never a word of what was said
    span().set_attributes({"speech.segments": len(t.segments), "speech.speakers": len(t.speakers),
                           "speech.duration": t.duration, "speech.code_switched": t.code_switched,
                           "speech.diarize": diarize, "speech.provider": t.provider or provider})
    return {"transcript_ref": ref, "duration": t.duration, "model": t.model,
            # WHICH provider answered, always — a comparison whose outputs cannot be attributed to a
            # provider is not a comparison, and the caller may have passed no name at all.
            "provider": t.provider or provider or config.SPEECH_PROVIDER,
            "speakers": _digest(t), "languages": list(t.languages),
            "code_switched": t.code_switched,
            "warnings": list(getattr(transcriber, "warnings", lambda *a: ())(langs, vocab)),
            "read_with": "storage_get"}


# ------------------------------------------------------------------ voiceprints
MIN_SEGMENT_S = 1.0     # below a second an embedding is mostly noise (measured, 29 Sep 2026)
MAX_LABEL_S = 120.0     # enough speech to know a voice; bounds one call on a long meeting


def _read(store, ref: str) -> bytes:
    blob = store.get(ref)
    return blob["body"] if isinstance(blob, dict) else blob


def _samples(audio_ref: str, segments_ref: str, only=None) -> tuple[dict, str]:
    """Each label's speech as (vector, seconds) pairs, and the model that made the vectors.

    Only segments with WORDS count: a diarizer segments audio, not speech, and a breath attributed to
    a voice is not that voice. The recording is decoded ONCE and cut in-process; every clip goes to
    the model in ONE call. `only` limits the work to the labels that may be kept — a voice nobody
    consented to keeping is never even embedded by `speech_enrol`.
    """
    segs = json.loads(_read(server.artifacts(), segments_ref)).get("segments") or []
    picked: dict[str, list[tuple[float, float]]] = {}
    for s in segs:
        label, start, end = s.get("speaker") or "", float(s.get("start") or 0), float(s.get("end") or 0)
        if (only is not None and label not in only) or not (s.get("text") or "").strip():
            continue
        if end - start >= MIN_SEGMENT_S and sum(e - b for b, e in picked.get(label, [])) < MAX_LABEL_S:
            picked.setdefault(label, []).append((start, end))
    if not picked:
        return {}, ""
    wav = audio_tools.to_wav16k(_clip(audio_ref), config.AUDIO_EXTRACT_BIN).data
    order = [(label, b, e) for label, spans in picked.items() for b, e in spans]
    embedder = server.speaker_embedder()
    vectors = embedder.embed([audio_tools.slice_wav(wav, b, e) for _, b, e in order])
    out: dict[str, list] = {}
    for (label, b, e), v in zip(order, vectors):
        out.setdefault(label, []).append((v, e - b))
    return out, embedder.model


@governed
def speech_identify(audio_ref: str, segments_ref: str) -> dict:
    """Which anonymous speakers sound like someone the lab has heard before.

    `audio_ref` is the recording (audio or video) and `segments_ref` the `transcript_ref` that
    speech_transcribe returned for it. Returns one entry per speaker label: a `suggestion` in the
    answer's own shape ({"identity" or "tag", "display", "score"}) when the voice matches a stored
    voiceprint closely enough, and an EMPTY suggestion when it does not. A suggestion is for a human
    to confirm, never an answer: present it pre-filled and let the person change it.

    Only voices whose owners consented were ever stored, and nothing is stored by this call."""
    samples, model = _samples(audio_ref, segments_ref)
    people = server.voiceprints().voiceprints(model) if model else []
    found = V.identify(samples, people, model=model)
    span().set_attributes({"voiceprint.labels": len(found), "voiceprint.gallery": len(people),
                           "voiceprint.suggested": sum(1 for s in found.values() if s)})
    return {"model": model, "speakers": [
        {"label": label, "seconds": round(sum(sec for _, sec in samples.get(label, [])), 1),
         "suggestion": s.to_dict() if s else {}} for label, s in found.items()]}


@governed
def speech_enrol(audio_ref: str, segments_ref: str, speaker_map: dict, consented_by: str,
                 source: str = "") -> dict:
    """KEEP the voices a human named and ticked consent for, so the next meeting can suggest them.

    `speaker_map` is the organiser's answer: label -> {"identity" or "tag", "consent": "yes"}.
    `consented_by` is who attested that consent; it is stored with every voiceprint. A voice is kept
    only when consent was ticked AND the gallery did not already recognise it as that person — a
    confirmed match is left alone, a corrected one is kept under the corrected name. Speech too short
    or too mixed to trust is skipped and reported. Returns labels and reasons — never a name."""
    if not (consented_by or "").strip():
        raise SpeechError("a voiceprint is kept only with the name of whoever attested consent")
    answer = Speakers.from_answer(speaker_map)
    consenting = {e.label for e in answer.entries if e.consent}
    if not consenting:
        return {"model": "", "enrolled": [], "skipped": {}, "reason": "no speaker was ticked for consent"}
    samples, model = _samples(audio_ref, segments_ref, only=consenting)
    gallery = server.voiceprints()
    plan = V.to_enrol(answer, V.identify(samples, gallery.voiceprints(model) if model else [], model=model))
    enrolled, skipped = [], {}
    for label in sorted(consenting):
        if label not in plan:
            skipped[label] = "already recognised as the person named"
            continue
        kind, key = plan[label]
        vp = V.enrolment(kind, key, samples.get(label, []), model=model or "unknown", source=source,
                         consented_by=consented_by.strip())
        if vp is None:
            skipped[label] = "too little clean speech to keep"
            continue
        gallery.add(vp)
        enrolled.append(label)
    span().set_attributes({"voiceprint.consented": len(consenting), "voiceprint.enrolled": len(enrolled)})
    return {"model": model, "enrolled": enrolled, "skipped": skipped}


# the catalogue is the contract: registering under any other name fails the parity test
assert {speech_capabilities.__name__, speech_transcribe.__name__, speech_identify.__name__,
        speech_enrol.__name__} == set(SpeechTools.names())


if __name__ == "__main__":
    print(f"speech-mcp: provider = {config.SPEECH_PROVIDER}, "
          f"extraction tool = {config.AUDIO_EXTRACT_BIN or 'NONE (video will be refused)'}; "
          f"call {SpeechTools.capabilities} to see what it actually serves")
    server.serve()
