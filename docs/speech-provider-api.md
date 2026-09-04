# Speech provider API — Munsit (candidate adapter behind the `speech_mcp` port)

Reference notes for building the speech ADAPTER. The vendor is named here because this is a doc; the
PORT (`lab.core.speech`), the tool contract (`SpeechTools`) and the gateway alias (`speech_mcp`) must
stay vendor-neutral, exactly as `ea_mcp` is neutral over `adoit-mcp`.

Source: <https://docs.munsit.com/> (`/speech-to-text/transcribe`, `/speech-to-text/diarization`),
read 4 Sep 2026. Live-probed the same day.

## Base URL and auth

```
https://api.munsit.com/api/v1/
x-api-key: $MUNSIT_API_KEY        # NOT `Authorization: Bearer`
```

Two traps, both cost us a failed probe:

* the path prefix is `/api/v1`, not `/v1`. `https://api.munsit.com/v1/...` returns `40401 Not found`;
* auth is `x-api-key`. A Bearer token is rejected.

An **older surface exists** at `https://api.cntxt.tools/audio/transcribe` with Bearer auth and an
explicit `model: munsit-1` field. Treat it as legacy; build against `api.munsit.com/api/v1`.

**Verified live 4 Sep 2026:** our key authenticates. An empty POST returns `400 {"errorCode":40001,
"errorMessage":"Invalid request"}`, i.e. past auth and into validation.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/audio/transcribe` | transcription |
| POST | `/audio/diarization/transcribe` | transcription **+ speaker diarization** (what the lab needs) |
| WSS  | `/websocket/speech-to-text` | streaming |
| POST | `/diarization/{id}/sentiment-analysis` | sentiment over a prior diarization |

Diarization is **synchronous**: one request, one full result, no job id to poll. That suits a
deterministic workflow node, but it means the request is held open for the length of the transcription,
so the adapter needs a generous timeout and the workflow must not treat a slow call as a failure.

## Parameters

`multipart/form-data`, field `file`.

| Field | Values | Notes |
|---|---|---|
| `model` | `munsit` (default) · **`munsit-en-ar`** | `munsit-en-ar` is documented as **mixed Arabic-English with code-switching** |
| `hotwords` | comma-separated | custom vocabulary bias for names and brands. **Not supported with `munsit-en-ar`** |
| `return_confidence` | bool | confidence 0–1 on timestamps |
| `return_timestamps` | bool | defaults true on `munsit` |
| `return_turns` | bool | segment the transcript by speaker turn |
| `return_gender` | bool | gender per turn |
| `return_sentiment` | bool | sentiment per turn |

### The one that matters

**`model=munsit-en-ar` is the answer to the mid-sentence Arabic/English requirement**, and it is
documented only on the endpoint pages. The product landing page talks about Arabic dialects and never
mentions code-switching, so a quick look at the marketing site gives the wrong answer.

**The documented trade-off is real and worth deciding deliberately:** `hotwords` does not work with
`munsit-en-ar`. So the lab chooses between code-switching support and biasing the transcript toward
domain vocabulary (system names, project names, people's names). For meetings full of English technical
terms inside Arabic sentences, code-switching wins, but it means product and person names will be
transcribed unbiased and the minutes agent must tolerate misspellings.

## Response — diarization

```json
{
  "statusCode": 200,
  "data": {
    "transcription": { "transcription": "…", "timestamps": [ … ] },
    "diarization":   { "segments": [ {"start": 0.0, "end": 8.5, "speaker": "SPEAKER_00"} ] },
    "merged":        [ {"start": 0.0, "end": 8.5, "speaker": "SPEAKER_00", "text": "…"} ],
    "duration": 53.661375,
    "transcriptionId": "…",
    "originalTranscript": "…",
    "audioUrl": "…",
    "stats": {"fileName": "…", "fileSize": …, "mimeType": "…", "creditsConsumed": …}
  },
  "message": "Success"
}
```

`merged[]` is what the port maps to `Segment(speaker_label, start, end, text)`. Everything else is either
redundant or adapter-private.

**`audioUrl` is a privacy consideration to settle before any real meeting audio is sent.** The response
hands back a URL to the uploaded audio, which implies the vendor retains it. Establish the retention and
deletion policy, and whether a tenant can opt out, before this leaves a lab recording.

**There is no speaker-count hint parameter.** For an in-person meeting captured on one microphone, the
count cannot be supplied even when the organiser knows it. That is a limitation of this candidate and a
comparison point against others.

## Limits and formats

* **Audio under 60 minutes.** Longer recordings must be split by the adapter, which then has to stitch
  speaker labels across chunks — labels are per-request, so `SPEAKER_00` in chunk two is not necessarily
  `SPEAKER_00` in chunk one. Non-trivial; design for it or cap the input.
* No explicit byte cap documented.
* **Audio only.** Accepted: `.aac .amr .flac .m4a .m4r .mp2 .mp3 .ogg .opus .wav .webm .wma`
  (verified live: posting an `.mp4` returns `40001 Unsupported audio format ".mp4"` and lists these).

**A meeting recording is `.mp4`, so extraction is mandatory.** Verified on the real recording we hold:
brand `isom`, two tracks, H.264 video and **AAC audio**. So extracting to `.m4a` is a pure stream copy —
no re-encode, no quality loss, near-instant. This is a real node in the
pipeline and a host-tool dependency on the speech service, the same shape as the office suite the
storage service needs for rendering.

## Errors seen

| Code | Meaning |
|---|---|
| `40401` | wrong path (e.g. missing the `/api/v1` prefix) |
| `40001` | invalid request — missing file, or unsupported format (the message lists the allowed set) |

## What is still unverified

* Whether `munsit-en-ar` actually handles mid-sentence switching **on our audio**. Documented, not proven.
* Accuracy on Gulf/Emirati dialect mixed with English.
* Diarization quality on far-field single-microphone audio with several speakers, which is the lab's
  actual in-person case.
* Rate limits, credit cost per minute, and the retention policy behind `audioUrl`.

These are exactly what the bake-off in the plan is for. A short recording containing real mid-sentence
switching, with several people around one microphone, settles all of them at once.

## Independent evidence — what stands up and what does not

Checked 4 Sep 2026 as part of choosing a first adapter.

**The "#1 on Arabic ASR" claim does not stand up.** The vendor is absent from the live public Arabic
speech-recognition leaderboard it appears to reference, and the circulating comparison figures are its
**own self-submitted runs**, in a pull request that was never merged. That also explains why its quoted
error rate for a well-known open model does not match that leaderboard's published figure: the run was
not the leaderboard's.

**What is real:** a **first place in NADI 2025**, an externally judged Arabic dialect shared task,
corroborated by the organisers. That is genuine evidence of strong dialectal Arabic, and it is the best
reason to keep this candidate in contention.

**No independent hands-on evaluation could be found.** Every third-party result located was vendor
material or a press-release reprint. Absence of evidence, not evidence of absence, but it means nobody
outside the vendor has published a number we can lean on.

**Diarization is thinner than the marketing suggests:** batch only, `file` and `model` parameters only,
**no per-word speaker attribution**, no speaker-count hint, no documented maximum number of speakers, and
no published diarization error rate.

None of this rules the candidate out. It means the decision has to be a measurement on our own audio, not
a procurement exercise. See the bake-off protocol in the plan.
