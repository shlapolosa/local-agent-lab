# Choosing the first speech adapter

Research completed 4 Sep 2026. The PORT (`lab.core.speech`, `SpeechTools`, alias `speech_mcp`) stays
vendor-neutral; this doc is about which ADAPTER to write first. The Munsit API reference is in
`speech-provider-api.md`.

The driving requirement is **Arabic to English mid-sentence** (intra-sentential code-switching), then
**speaker allocation for in-person meetings** on one microphone.

## The decision in one paragraph

**Speechmatics first, Munsit as the residency answer.** Speechmatics wins because code-switching is a
named language-pack contract (`ar_en`) rather than emergent behaviour, its Arabic pack explicitly names
**Gulf**, and it has by far the richest diarization surface — including **speaker enrolment**, which is
the only mechanism any candidate offers for keeping speaker labels stable across a long meeting. Munsit
is the right first adapter instead if **in-country data residency is a hard regulatory constraint**,
which for a DOH Abu Dhabi context is a real possibility and is the one question that flips the ranking.

## Why not Azure, which is what we wanted

Strategically an Azure-native answer would be worth real accuracy cost, since the lab is built to migrate
there. It does not work today, and the refusal is in Microsoft's own documentation.

Azure's continuous language identification re-identifies the language as audio proceeds, but the docs
state plainly that it **"doesn't support changing languages within the same sentence"**, and give the
exact example of Spanish with English words inserted. That is our requirement, refused in writing. The
architecture is a classifier at segment boundaries, so an intra-sentential switch is invisible to it.

Arabic coverage on that path is otherwise excellent — eighteen locales including `ar-AE` — and
diarization does compose with language identification on batch (fewer than 36 speakers, 240 minutes,
**mono only**, so a stereo conference device must be downmixed). The fast multilingual model does true
code-switching but supports **no Arabic at all**.

The only Azure paths that could meet the requirement are **LLM Speech and MAI-Transcribe-2**, and two
things block them. MAI-Transcribe advertises mid-utterance code switching but names only Hinglish and
Spanglish, never Arabic–English, which is a meaningful silence. More decisively, **UAE North does not
support fast transcription**, which is the gateway to both, so Azure's only capable path cannot run
in-country, and it is public preview with no SLA.

**Treat this as a watch item.** Re-evaluate at general availability and when it reaches UAE North. It is
the only path that would make this problem disappear into the governance plane we already run.

> Do not be misled by third-party benchmarks scoring Azure worst on Arabic code-switching. At least one
> widely cited study configured Azure as continuous language identification, which is the structurally
> wrong path, and even quotes the same Microsoft sentence. That number measures the wrong thing.

## The candidates

**Speechmatics — first adapter.** `ar_en` is documented for Arabic and English *in the same media file
or stream*, and the Arabic pack covers MSA plus **Gulf**, Egypt and the Levant. Diarization gives
per-word speaker labels, two real tuning knobs (`speaker_sensitivity`, `prefer_current_speaker`) and
**speaker enrolment** from short clips, which the docs say also improves diarization accuracy. Batch and
real time share the model, so live captioning later does not force a second vendor. On-prem is a GPU
container distributed from an **Azure Container Registry**, which suits our trajectory. A separate
Arabic-English bilingual model shipped in March 2026, which signals sustained investment in this exact
pair. Its `melia-1` model is worth a diagnostic arm in the bake-off because it emits **per-word language
tags**, useful both downstream and for measuring switch points, though it is early access and less
accurate. Weaknesses: no maximum speaker count and no speaker-count hint documented; cloud regions are
EU, US and Australia only, so residency means on-prem; and its "6.3% WER, 35% better" claim names no
benchmark and should be discounted entirely.

**Munsit — runner-up, and the residency answer.** UAE-built and UAE-hosted, with SaaS, dedicated VPC and
on-prem including air-gapped, plus a mode guaranteeing no stored recordings and **no secondary use of
audio for training**. Its `munsit-en-ar` model is documented for speakers alternating between the two
languages *within the same utterance*, and the diarization endpoint takes the same `model` parameter, so
switching and diarization compose in one call. It holds the only piece of external validation in the
field: **first place in NADI 2025**, organiser-corroborated.

Its weakness is exactly our second priority. No diarization tuning parameters at all, no speaker-count
hint, no documented maximum, no per-word attribution, and **no enrolment**. Combined with the 60-minute
cap, that is a real problem: labels are assigned per request, so a 90-minute meeting must be chunked and
`SPEAKER_00` in the second chunk is not necessarily the same person as in the first. Re-linking them
means voice-embedding the segments ourselves, which hands us back the hard part of diarization.
Choosing `munsit-en-ar` also forfeits custom vocabulary, and timestamps default to off.

**ElevenLabs Scribe v2 — test it anyway.** The only candidate with a *measured* Arabic-English
code-switching win, and it degrades gracefully on harder audio where others collapse. But the capability
is **not in the contract**: the API returns a single language code for the whole file, with no field that
could express a switch. Arabic is one locale with no dialect selection. Two commercial blockers for an
enterprise lab: it **trains on your data by default** below Enterprise, and processing may occur outside
the selected storage region. No Azure private deployment until H2 2026.

**AssemblyAI — best documentation, no Arabic evidence.** The only vendor with a dedicated code-switching
page, with Arabic inside its elite 18-language set and native mid-sentence switching. Diarization takes a
speaker range and defaults to 30 maximum. But **no Arabic error rate has ever been published, by anyone**,
and Arabic is conspicuously absent from its own five-language benchmark table. One trap: under automatic
language detection an unsupported feature is *silently omitted*, so always pass an explicit Arabic
language code to make gaps fail loudly.

**Deepgram — eliminated on documented grounds.** Its multilingual code-switching mode covers ten
languages and **Arabic is not among them**, while its seventeen Arabic locales are a *monolingual* model.
Arabic support and code-switching support are disjoint feature sets. This is scope exclusion, not weak
performance.

**Whisper — control arm only, disqualified as a candidate.** It predicts one language token per
30-second window, so a mixed utterance has no representation in its output space. Peer-reviewed
evaluation on code-switched Arabic found it **produced no code-switched words in any configuration**,
translating or transliterating instead, and that naming the language makes it *worse*. Keep it as a floor
to measure commercial systems against.

**Multimodal LLMs as transcribers — the thesis is half right.** Removing the language-identification
bottleneck genuinely helps, but the measured winner is a dedicated language-agnostic engine, not an LLM.
No independent Arabic number exists, vendor-run figures contradict each other, and there are
acknowledged long-audio failures plus severe timestamp drift. Diarization is prompt-engineered behaviour,
not a product feature with an SLA. Our gateway carries no audio-capable model today in any case.

## What to expect from in-person meetings, honestly

From the closest public analogue — real meetings, four to eight people, one device — speaker-attributed
error on a single channel runs about **41% for a stock pipeline and about 22% for a state-of-the-art
research system**, on English. Dialectal Arabic with code-switching will be worse. Plan for the machine
getting a meaningful share of attribution wrong. This is why the human mapping gate is load-bearing.

**The microphone is a bigger lever than the model.** A microphone array roughly halves the error, which
outweighs the difference between our top two vendors. Overlapping speech dominates the error budget,
running four to five times worse than clean single-speaker audio. In descending order of effect: an array
with beamforming, less overlapping speech, speakers close and equidistant, a speaker-count hint where the
API accepts one, and enrolment where available.

## Bake-off protocol

Rank on **speaker-attributed word error**, not diarization error. In that challenge the winning system
had the *worst* diarization of the top four and still won overall, and another transcribed better than
everything that beat it yet placed fifth purely on attribution.

**Decide the reference convention before transcribing.** Are embedded English words written in Latin
script or transliterated into Arabic? This single choice moves the score by tens of points and is the
commonest way these evaluations reach a wrong answer. Pick what the downstream agent actually needs.

Take one real meeting, 60–90 minutes, four to six speakers, on the device we intend to deploy. Human-
transcribe a stratified 20–30 minute sample verbatim with speaker turns and timings, over-sampling
switch-dense passages and including overlapped stretches and short backchannels. Normalise once,
identically, for every system, preserving Latin script.

Measure: attributed word error as the ranking number; speaker-agnostic word error, whose gap to the first
is the attribution cost; word **and character** error, because for Arabic these diverge sharply and word
error alone will make us reject a working system; **switch-point error** in a small window around each
language switch, which is the only metric that isolates priority one; the ratio of code-switched to
monolingual error, which is the tax the mixed audio costs; and a transliteration-tolerant metric, since
the difference between "unusable" and "marginal" here is often a metric artefact.

Report diarization error **four ways**: with and without the usual forgiveness window, and with overlap
scored and unscored. The window alone removes a quarter to a third of the apparent error, largely by
forgiving short backchannels, which flatters systems that simply drop them. Also record estimated versus
true speaker count, since merging two people is a different failure from splitting one.

**Vary configuration, not just vendor** — one engine has ranked both best and worst on Arabic in
different studies, reconciled entirely by whether a language hint was supplied. Include one **hardware
arm**: record the same meeting on the single device and on a microphone array. That comparison is likely
worth more than the vendor choice and is the finding that would change procurement rather than code.

Set the pass bar before running, and blind the scoring.

## Open questions that need answers from outside

- **Does DOH Abu Dhabi require in-country data residency for meeting audio?** This flips the ranking.
- Munsit's on-prem **speech** availability is unestablished; its self-hosting page lists only a
  text-to-speech model. Ask CNTXT directly.
- Munsit's retention policy behind the `audioUrl` its API returns.
- Whether Speechmatics' `ar_en` pack ships in its on-prem container images, and its speaker ceiling.

## What nobody knows

No vendor publishes an Arabic diarization error rate — that number does not exist for any candidate. No
evaluation of Emirati-dialect performance exists for any commercial system anywhere. Every published
figure above, including the best of them, is an ordering under one harness: the same system scores 9.8
and 23.7 in two harnesses at identical settings. The only number that decides this is the one we measure
on our own audio.
