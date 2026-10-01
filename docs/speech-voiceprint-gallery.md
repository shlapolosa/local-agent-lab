# A persistent voiceprint gallery — analysis

**Status:** analysed 29 Sep, measured 30 Sep, **built 1 Oct 2026** (branch `feat/voiceprint-gallery`) — see §9.
**Question:** can the meeting pipeline keep a store of voiceprints it always checks, so that a known
voice is named automatically instead of arriving as `SPEAKER_nn`, and an unknown one is sent to a
person to tag and then remembered?

**Short answer:** yes, and it fits the pipeline that already exists. But a voiceprint is biometric
data, so the legal design has to come before the code, and one existing defect (tool arguments on
public traces, §7) has to be fixed before any of it carries real people.

---

## 1. Where it fits

Today: `transcribe → speaker digest → ask the organiser → [approve] → minutes`.
The gallery adds one step before the question and one after the answer:

```
transcribe → identify (NEW) → digest → ask organiser → [approve] → enrol (NEW) → minutes
               │                                                    │
               └─ match each SPEAKER_nn against the gallery          └─ keep voiceprints only for
                  → pre-fill the card with a name and a score           people who consented
```

- The human gate is unchanged. A match arrives as a **pre-filled suggestion with a score** — the same
  shape as the existing `SpeakerCandidate` picker (the attendee list), with evidence attached. The
  organiser still confirms. Skipping the question for a high-confidence match is a policy decision to
  take after measurement, not a starting point.
- **It repairs over-splitting for free.** When a diarizer splits one voice in two — munsit on 28 Sep
  gave the Arabic and the English halves of one speaker different labels — both labels match the same
  voiceprint and can be merged without asking.

## 2. Who computes the voiceprint

| Option | Verdict |
|---|---|
| The speech vendors (Soniox, Munsit) | Speaker labels are anonymous and **per request**; neither offers enrolment. The gallery has to be ours. |
| Azure AI Speaker Recognition | **Retired** by Microsoft (Sept 2025). No Azure-native API. |
| Teams in-room voice enrolment | Microsoft offers tenant-managed voice profiles for Teams Rooms, with a consent policy. It attributes speech only inside **Teams' own** transcript — which on 29 Sep dropped the Arabic sentence entirely. A hybrid (Teams for *who*, Soniox for *what*) is possible but depends on Teams Rooms hardware. **To verify.** |
| **Our own speaker-embedding model** (ECAPA-TDNN or WeSpeaker; open source, ~20 MB, CPU) | **Recommended.** Runs inside `speech-mcp`, which already holds the audio and ffmpeg. Precedent: the substrate already runs its own model (the `embedder`). |

Mechanics: slice each label's segments out of the audio (timestamps are already in `segments_ref`),
drop overlapping speech and turns shorter than ~2 s, and compute one embedding per label — a vector of
~192–256 numbers. Embeddings are largely language-independent, which matters for code-switching, but
they degrade on far-field single-microphone audio, so people should be enrolled from the same kind of
room recording they will be matched in.

## 3. Storing voiceprints

- **Store the vector, never the audio.** Several embeddings per person (one per meeting or acoustic
  condition) plus a centroid.
- **Per row:** the person's directory **object id** (not their UPN), the **model id and version** (a
  vector compares only with vectors from the same model — upgrading the model means re-enrolling),
  source meeting, date, and a **consent record id**.
- **Where:** Postgres + pgvector — the technology the reference corpus already uses. Azure Postgres
  Flexible in **UAE North** already exists, so in-country residency is solved for prod. Railway is dev
  and must not hold real people's voiceprints.
- **Access:** a dedicated schema and database role, readable only by the identify step. Workloads
  never hold the credential (already an invariant). Enrol and forget are **WRITE** tools with their own
  grant, split the way `ApprovalTools` splits read from decide.
- **Never on a span, never as a tool argument** — see §7.
- **Architecture:** a domain port in `lab.core.speech` — `VoiceprintGallery` with `match`, `enrol`,
  `forget`, `list_for` — and a pgvector adapter in the substrate, so Azure AI Search or a vendor
  gallery would be a one-line registry swap.

## 4. Matching

- **Cosine similarity** against each person's embeddings; best match per label, then assign
  **jointly** across the meeting: one person cannot be two labels speaking at the same moment, but can
  be two labels that never overlap (the over-split case).
- **Tune the threshold against false accepts, not for recall.** A missed match costs the organiser one
  question. A wrong match attributes words and decisions to the wrong person, and that travels into
  the minutes and the semantic layer. Calibrate on our own recordings, never on published benchmarks.
- **Three bands:** above the high threshold → pre-fill (later perhaps auto-fill); between the
  thresholds → suggest with the score shown; below → ask, as today.
- **Minimum speech per label**, of the order of 10–20 s net. On 29 Sep Nabeel spoke ~7 s — too little
  to match reliably. Below the minimum, the label goes straight to the human.
- **Record the method on the edge.** The semantic model already carries attribution as
  `Participant → Person` with a confidence; adding `method = voiceprint | human` means no query can
  mistake a machine match for a human confirmation.

## 5. Legal — the shape, not advice; needs a real legal review

- **A voiceprint is biometric data.** Under the UAE PDPL biometric data is *sensitive personal data*,
  which points to **explicit consent**, a **DPIA**, purpose limitation, a retention limit and a working
  right to erasure. In a DOH context also check DOH's own data and cybersecurity standards; the UAE
  ICT-in-health law is mainly about health data, but keep the same residency posture.
- **The organiser naming someone is not that person's consent.** Consent must come from the **person
  being enrolled**. So enrolment is its own step: after the organiser tags Ahmed, *Ahmed* receives a
  card — "may we keep your voiceprint to recognise you in future meetings?" — and only his yes writes
  his vector. No yes: he is tagged for this meeting only and nothing is stored.
- **Employee consent is weak unless refusing costs nothing.** Here the fallback — being asked every
  time — already exists, so opting out genuinely costs nothing. State that in the DPIA.
- **Matching touches everyone's voice**, enrolled or not: an embedding must be computed to know there
  is no match. Those vectors are **transient** — in memory for the run, never persisted — and attendees
  are told in the meeting notice.
- **External and free-tagged people are never enrolled.** No directory identity, no consent path.
- **No retroactive enrolment.** Every past approval pairs a label with a person, and seeding the
  gallery from them is tempting. Those people never consented.
- **Revocation:** "forget me" deletes every vector for that person, is logged, and has an owner.
  Retention could mirror Microsoft's approach for Teams voice profiles: delete after N months without
  a match.

## 6. Risks

Wrong attribution is the main harm. Others: voice drift (illness, microphone, room); a model upgrade
invalidating the gallery; two similar-sounding colleagues in a small room; and matches that read as
certain when the audio was poor.

## 7. A prerequisite found while writing this

**MCP tool-call arguments are copied onto the gateway's OTel span (`mcp_tool_call_metadata` on
`litellm_request`), and the lab's Jaeger is public and unauthenticated.** Measured on 29 Sep for the
07:23–07:37Z meeting run (counts only; no content was read):

| Tool call | Spans | Exposed in its arguments |
|---|---|---|
| `approvals_ask` | 3 | verbatim utterance samples + organiser UPN |
| `semantic_store_spec` | 13 | the full minutes; 11 name two non-lab attendees |
| `semantic_validate_model` | 3 | the mapped meeting model, naming the attendees |
| `collab_meetings` | 3 | organiser UPN |
| `speech_transcribe`, `collab_put` | — | references only — clean |

By-reference holds wherever it was applied. It was not applied to the approval question (samples
inline) or to the minutes (a workload has no other way to write a store). For the gallery this is a
hard rule: **no vector, identity or sample may ever be a tool argument**, and the gallery cannot carry
real people until tool-argument span metadata is off at the gateway, Jaeger is behind auth, or both.

## 8. Sequencing

1. **Measure before building** — the provider bake-off's discipline. Offline embeddings over existing
   recordings: do the three voices of 29 Sep separate cleanly on a laptop microphone? Even this
   processes biometrics, so it needs the recorded people's consent first.
2. **Suggest-only** in the pipeline: match, pre-fill with the score, the human confirms, enrol on the
   person's own consent.
3. **Auto-fill** above the threshold — only when measured false-accept rates justify it.

## Open questions

- Is in-room Teams hardware on the roadmap? It changes the build-versus-buy answer.
- Who owns the gallery — its DPIA, its erasure requests, its retention?
- Are free tags ever worth a per-meeting (never persisted) voiceprint, to keep one external person
  consistent across a long recording?


## 9. What was built (1 Oct 2026)

**Measured first** (30 Sep, ECAPA-TDNN, the 29 Sep three-person meeting + the organiser alone on
28 Sep; aggregates only): same-person lines median similarity 0.39, different-person 0.14; at a 0.40
threshold **no line was ever given the wrong person**, including when the speaker was absent from the
gallery; pooling ≥5 s per decision named 7/7 correctly; Nabeel's Arabic sentence scored 0.71 against
his English-only voiceprint. The pipeline's own approved attribution of that meeting was right for only
~51–54 % of its words — diarization labels MIX people, which no per-label answer on a card can fix.
The production code path reproduces the POC's vectors exactly (cosine 1.0000 on all 23 segments).

| Piece | Where |
|---|---|
| The rules (threshold 0.40, leave-one-out purity 0.25, 3 s to suggest, 5 s to keep, consent) | `lab.core.speech.voiceprint` (pure) |
| `consent` on a speaker answer — absent means **no** | `lab.core.meetings.model.Speaker` |
| The model as a service, in its **own image** (`ghcr.io/<repo>/voiceprint`), opt-in `VOICEPRINT_ENABLED` | `lab.substrate.voiceprint.service`, `deploy/voiceprint/Dockerfile` |
| The gallery: `lab_voiceprints` in the substrate Postgres — vectors, model, who attested consent; never audio | `lab.substrate.voiceprint.gallery` |
| `speech_identify` (suggest) and `speech_enrol` (keep; its own WRITE grant) | `speech-mcp` |
| Suggestion pre-filled on the question; recording passed on for enrolment | `meeting_to_transcript` → `identify_voices` |
| Voices kept after the approval, only where consent was ticked and the gallery did not already know them | `transcript_to_minutes` → `keep_voices` |
| Card: "Recognised as X (voice match s)", prefill, consent toggle | `config/clients/power-automate/flow.template.json`, `scripts/power_automate_voiceprint_card.py --live` |
| Review app: the same prefill and checkbox | `lab.substrate.review.app._answer_form` |
| Seeding from verified segments, through the production tool | `scripts/seed_voiceprints.py` |

**Still true from §7**: suggested names travel in the approval payload and the enrol arguments, and the
gateway copies tool arguments onto a public trace span. Fix that before real meetings rely on this.
