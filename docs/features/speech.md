# Speech and meetings

*Feature notes split out of the root `CLAUDE.md` on 4 Oct 2026, verbatim. Shared rules (method, quality bar, invariants, cloud shape, identity, gateway, approvals, observability) stay in the root file.*

## Speech (`lab.core.speech`, served by `speech-mcp` :9600) — and the provider bake-off

The domain port is **`Transcriber`** (`lab.core.speech.port`): a `Protocol`, so an adapter is free of
us and a test double is a plain object. It states four things a provider must honour — **languages
are a plural HINT** (declaring one language is the documented way to make a switching engine worse),
the **recognised language comes back PER SEGMENT** (without it, a span rendered in the wrong language
is indistinguishable from a correct answer), **speaker labels are ANONYMOUS and per request**
(mapping a label to a human is a separate, human-gated act), and **a refusal is TYPED**.
Summarisation is deliberately absent: this port returns words and labels, and minutes are produced
by the lab's own governed model — which is what makes "the vendor does not summarise our meetings"
structural rather than a promise.

**A speaker is someone who said something.** A diarizer segments AUDIO, not speech, so it can
attribute a breath or a keyboard to a voice it thinks is new and return that segment with EMPTY
text. Measured 7 Sep 2026: a one-person meeting produced three empty `SPEAKER_01` segments, and a
human was asked at the approval gate to name a person who never spoke. `Transcript.spoken` is the
basis of every speaker-facing derivation; the empty segments STAY in `segments` (a provider's
timeline is evidence) and a silent span belonging to a speaker who DID talk still counts toward
their share — a pause inside a turn is their time. Only the label minted by silence alone is excluded.

**Adapters, one line each in `lab.substrate.container.SPEECH_PROVIDERS`** — three files per provider
(`*_map.py` pure mapper, `*_rest.py` transport, `*_repository.py` adapter), with the generic parts
shared: `http.py` (injected transport, multipart, `poll_until`), `refusal.py` (provider status -> the
domain's typed refusal), `tokenmap.py` (a word/token stream -> speaker turns, breaking a run at a
change of speaker OR of language, because that switch is the evidence). `soniox-en` is the same
provider asked for the English half of its unified token stream — a separate registry entry, not a
flag, because the verbatim record and the rendering are different artifacts.

**`enable_language_identification` is not optional on Soniox, and leaving it off cost five distinct
defects** (root-caused 12 Sep 2026 by sending the SAME 91.8-second bilingual recording twice,
differing only in that boolean). Without it the provider returns **no `language` field at all** — so
the port's per-segment language is empty, and `tokenmap`, which breaks a speaker's run at a change of
language, could not see the code-switch this lab exists to make visible. Worse, it also stopped
marking the translated Arabic as `original`, returning it under `translation_status: none` in Arabic
script with a `translation` run after it: a payload in which NOTHING says which words the rendering
replaces, and no heuristic recovers it. With the flag on, the same audio came back clean — 335
`none`/en, 53 `original`/ar, 47 `translation`/en, strictly alternating. **One missing boolean;
`request_body` now always sends it.**

**The stream has THREE kinds of token, and the `soniox-en` lane asked for the wrong one.**
`soniox_map.WANTED` names the three renderings: `original` = `none + original`, the verbatim record;
**`english` = `none + translation`, every word in English — what a person reads and what minutes are
written from**; `translation` = the rendered spans ALONE, a side-by-side column and nothing more. The
lane asked for the last, so a mostly-English meeting came back as 21 words of 219 and read like a bad
recording rather than a wrong filter. Four further rules the live payload settled, none of them in
the published schema:
- **The tokens are SUB-WORD and carry their own leading space** (`"Ass"`, `"al"`, `"amu"`, `" al"`),
  so they CONCATENATE — `group_into_segments(concat=True)`, per provider, because ElevenLabs drops
  its own `spacing` entries and needs the spaces put back. Getting it backwards is silent and still
  looks like a transcript: the space join turned "Peace be upon you" into "Pe ace be up on y ou".
  A **whitespace-only token is a word BOUNDARY** in that stream, not noise — the blank-token filter
  written for word streams deleted one and shipped "going to theright direction".
- **A rendering carries NO timestamps** (`start_ms: 0, end_ms: 0`) and is emitted right after the run
  it renders, so it BORROWS that run's span — the run IMMEDIATELY before, one contiguous group of the
  same status AND speaker. Without the borrow the English rendering rewinds to zero on every Arabic
  span and `Transcript.__post_init__` refuses it. Keyed on status alone, two translated turns by
  different speakers pool into one span and each rendering is laid over the other's talk — which
  raises nothing, and doubles both speakers' share of the recording.
- **A rendering never shares a segment with speech** (`Tok.kind`). Both carry the same speaker and,
  once translated, the same language, so kind is the only thing left holding them apart — and a
  segment is quoted to a human at the speaker-naming approval as words that speaker said.
- **Speech nothing rendered is KEPT** in the English transcript. Its script then shows in the digest,
  which is a visible imperfection; silently losing speech is not — and because the mode's success
  metric is "no Arabic script", losing it would read as a win.

**Measured, five lanes plus Microsoft's own transcript, one 91.8 s recording**
(`var/out/bakeoff/20260912_114824/`): reference 194 words · munsit 131 · assemblyai 198 ·
elevenlabs 203 · **soniox 216 at 7.6 % Arabic script, the only lane reporting `code_switched`** ·
**soniox-en 223 at 0.0 %**. The decisive span is the Arabic question at 52 s: Microsoft's transcript
DROPS it, munsit returns fragments ("Attia", "thing um"), ElevenLabs and AssemblyAI each keep the
English words around it and lose the Arabic half — **Soniox is the only provider that captured it**,
verbatim in Arabic and rendered in English. **So the planned governed translate step is not needed
for this provider**: it is one call, and the speaker survives onto the translated tokens, which is
what keeps a rendered transcript attributable.

**Every Soniox fixture in this repo had been typed from the published schema, and that is how three
of the defects above passed review** — the code and the tests shared the same wrong assumptions and
agreed with each other. Two things changed: `tests/fixtures/soniox_response.json` is 111 contiguous
tokens of a REAL response (contiguous because a spliced slice invents word boundaries the stream does
not have), guarded by a test that fails if a later trim removes the sub-word tokens, the `none` bulk,
the timestamp-less renderings or the whitespace boundary; and `scripts/speech_bakeoff.py` now saves
`<provider>.raw.json` per lane, in a `finally` — the payload is worth most on the run that failed to
map.

**The transliteration finding (7 Sep 2026), which drives the whole comparison.** Munsit heard
English correctly and wrote it in ARABIC LETTERS: `اكشن ايتمز` is a faithful phonetic rendering of
"action items". Verified against Microsoft's own transcript of the same recording. This is
orthographic, not semantic — every word right, every letter wrong — and it is a KNOWN general
behaviour, not a Munsit defect: the only independent benchmark of code-switched Arabic
(arXiv 2605.19069, May 2026) reports **WER overstates such gaps ~3x by scoring semantically correct
transliteration as error**, and puts ElevenLabs Scribe v2 first on all four pairs (13.2% vs 38.6%
for the next system). **So never rank speech providers on WER here.** `lab.core.speech.compare`
holds the metric that matters — **script mix**, the share of LETTERS in Arabic script, which needs no
reference transcript — plus `digest` and a timeline-aligned `side_by_side`.

**The tenant's own transcript SILENTLY DROPS a language, and that is the finding the whole exercise
was for** (measured 12 Sep 2026 on a deliberately bilingual meeting, two speakers, one describing a
building in Arabic while the other spoke English). Microsoft's Teams transcript returned **53 words:
the English turns only**. Both of the Arabic speaker's turns — the gym, the facilities, the pool, nine
floors, the room converting to two bedrooms, fully furnished — are absent, and nothing marks the
omission: it reads as a complete, fluent transcript of a shorter meeting. Its 0 % Arabic script is
ABSENCE, not translation. The same audio, same minute, through this lab:

| source | words | Arabic script | the Arabic speaker's turns |
|---|---|---|---|
| **soniox-en** | **97** | 0.0 % | **both, rendered into English** |
| elevenlabs | 87 | 25.8 % | both, verbatim in Arabic |
| assemblyai | 86 | 30.2 % | both, verbatim in Arabic |
| **Teams (the tenant)** | **53** | 0.0 % | **neither** |
| munsit | 25 | 84.5 % | partial, and attributed to the WRONG speaker |

Note what the two 0 % rows mean — one translated everything, the other lost it — which is why the
metric is never read alone: **script mix says what SCRIPT the words are in, coverage says whether the
words are there at all, and a provider can score perfectly on the first by failing the second.** The
minutes make the same point one layer up: every lane produced a plausible summary and correctly found
0 decisions and 0 actions, but only the English rendering produced CONCEPTS a person or a downstream
join can use — the verbatim lanes emitted `المسبح` and, from ElevenLabs, hybrids like `the العمارة`
that no vocabulary can match on, and munsit's summary confidently credited the wrong speaker with the
wrong half of the meeting. **A summary that reads well is not evidence of a transcript that is right;
three of the four read well.**

**Voiceprints suggest who a voice is; they never answer it (1 Oct 2026).** `speech_identify` scores
each diarized label against a gallery of stored speaker vectors and returns a SUGGESTION that the
`identify_voices` step pre-fills on the speaker card — "Recognised as X (voice match 0.52)" — for the
organiser to confirm or correct. `keep_voices` (in `transcript_to_minutes`, i.e. only after a person
answered) calls `speech_enrol`, which stores a voice ONLY where the card's **consent** toggle was ticked
and the gallery did not already know that person; consent is absent from the answer when unticked, and
absent reads as NO. The rules and their numbers live in `lab.core.speech.voiceprint` and were MEASURED
on a real three-person meeting (docs/speech-voiceprint-gallery.md): threshold **0.40** gave no wrong
name at all, including for a speaker missing from the gallery; **leave-one-out purity 0.25** drops a
segment that does not sound like the rest of its label, because labels MIX people — the approved
attribution of that meeting was right for only about half its words; 3 s of speech to suggest, 5 s to
keep. The model (ECAPA-TDNN) runs as its own `voiceprint` service in its OWN image
(`deploy/voiceprint/Dockerfile`, `ghcr.io/<repo>/voiceprint`) because PyTorch is ~1 GB and every other
role pulls the shared image; it holds the shared bearer and nothing else, is opt-in (`VOICEPRINT_ENABLED`),
and a code `release` never touches it (`topology.is_ours` matches `ghcr.io/<repo>:` only). The gallery
is `lab_voiceprints` in the substrate's own Postgres — vectors, model id and who attested consent,
never audio — reached only by speech-mcp. `speech_enrol` is `SpeechTools.WRITE`, granted to the
minutes team alone. Both steps are best effort: no model, no gallery or no grant means a card with no
suggestions, never a failed meeting.

**What a person receives is plain text in Teams' own layout, and every lane is scored against Teams
(3 Oct 2026).** Each minutes run delivers `<recording>.<lane>.transcript.txt` (title, date, duration,
then `Name   0:03` over each turn — `lab.core.meetings.render.transcript`, with `read_transcript` its
exact inverse) and `<recording>.<lane>.minutes.txt`, stored AS THEMSELVES through `semantic_store_page`
because the JSON-wrapping `semantic_store_spec` had delivered `{"text": "\u0627…"}` nobody could read. The transcript
run fetches the tenant's OWN transcript of the same OCCURRENCE (a recurring meeting keeps one id and
one transcript per day, so `_occurrence_transcript` picks by the matched recording's time) and carries
it as `reference`; `compare_with_reference` then reads every sibling lane's delivered `.transcript.txt`
beside the recording and rewrites ONE `<recording>.comparison.txt` — words, share of Teams' words,
Teams' words also found (AGREEMENT, not accuracy: Teams drops speech it cannot handle), Arabic-script
share, speakers. The last lane to finish leaves the full table; no lane waits for another. Measured on
the 29 Sep meeting: munsit agreed with 21 % of Teams' words, both Soniox lanes 92–93 % while holding
9–11 % MORE words than Teams (the Arabic it dropped). Best effort throughout.

**The bake-off**: `scripts/speech_bakeoff.py <recording> [--reference teams.vtt] [--repeat N]` runs
one recording through every CONFIGURED provider and writes per-provider transcripts, a side-by-side
comparison and `digests.json` into `var/out/bakeoff/<stamp>/`. A provider with no API key is SKIPPED
by name with the setting it wants, so one credential still produces a usable run. `--reference` adds
Microsoft's own `.vtt` as a column — for a Teams meeting it is the honest yardstick and it costs
nothing. **`--repeat` is earned, not cautious**: three runs on IDENTICAL bytes returned 38, 55 and 38
words, so a single run cannot tell a provider's behaviour from one sample of it.

**Lanes run in PARALLEL by replica, not by thread.** A consumer group hands each stream entry to
exactly one consumer, so N replicas of a workload process N lanes at once with no locking and no
change to the workflow — and that is the shape Container Apps scales, which is the point of the
lab. `WORKLOADS["meeting"]["replicas"]` creates one service per replica, the FIRST keeping the plain
name (renaming it would orphan its variables and logs), each with its own `WF_CONSUMER`: two
consumers sharing a name share a pending list, and XAUTOCLAIM could no longer tell whose in-flight
work is whose. `up`, `down` and `status` all iterate replicas — stopping only the first would leave
the others consuming the stream, which looks like "I stopped the workload" and is not.
Failure is isolated per lane at every stage (submit, run, continuation, delivery, notification), but
a lane that HANGS rather than fails still blocks whatever is queued behind it for the provider
timeout (900 s) — which is what replicas buy down, and why `meeting` runs two.

**Data residency is a property of the DEPLOYMENT MODE, not the vendor** (UAE Federal Law No. 2/2019
Art. 13 forbids processing UAE health data abroad; AED 500-700k). All four candidates can run inside
the boundary, but only Munsit (CNTXT AI, Dubai) has a UAE/KSA **sovereign SaaS** — everyone else buys
residency with GPU infrastructure (ElevenLabs, Soniox and AssemblyAI all sell on-prem; Meta Seamless
self-hosts but is CC BY-NC and does not diarize). **Azure OpenAI in UAE North is NOT an answer**: it
provisions in-region but routes inference to West Europe / France Central, so a "governed gateway
text step" there would itself be an export.

**A recording is matched to its meeting DIRECTIONALLY, because the gap IS the meeting's length.**
  A drive file is created when recording STARTS and the provider's recording object when it STOPS, so
  the object always arrives later, by however long the meeting ran. `_match` compared the two with a
  SYMMETRIC 60 s tolerance, which therefore refused every meeting longer than a minute — measured
  live 12 Sep 2026: file 14:01:38Z, recording object 14:02:54Z, 77 seconds apart, while the
  next-nearest candidate was three days away. The right meeting lost by 17 seconds against a rival
  3,300x worse. Widening the window would only have moved the cliff; the fix is direction — an object
  that stopped BEFORE this file existed cannot be this file's, which is also what separates
  back-to-back meetings — with the soonest-stopping winner inside a generous four-hour window.
  **One failed match cost TWO things and looked like three bugs**: `_owning_meeting` returns the
  participants AND the `chat_id`, so the speaker picker was empty AND the minutes were never announced
  in the meeting's chat. It read like a Graph failure and was not: calling the same tools by hand with
  the workload's own credential returned two meetings, eleven recordings, participants and chat_id.
  The lookup succeeded and the arithmetic discarded the answer. **Only the exception path logged**, so
  "asked and matched nothing" was indistinguishable from "never asked" and from "the meeting had no
  attendees"; both outcomes now print, with the candidates considered and whether a chat_id came back.
  The old tests passed throughout because their fixture used a FIVE-SECOND gap — a recording that
  stopped five seconds after it started, which is not a meeting.

  **A speaker question may carry CANDIDATES** — `contracts.SpeakerCandidate` /
  `speaker_candidates`, resolved by the transcript workload from the meeting that OWNS the recording
  (matched by HANDLE, never by parsing a provider filename). Every surface offers them as a pick
  BESIDE free text and never instead of it: attending is not speaking, one device in a room is one
  participant, and a picker-only form would make the honest case impossible. Best effort —
  `collab_meetings`/`collab_recordings` are NOT in the workload's `REQUIRED_TOOLS`, so a deployment
  without the grant degrades to no picker instead of being refused by preflight. A typed identity
  always beats a pick.

## The opt-in Teams meeting app (`lab.substrate.meetingapp`, service `meeting-app` :3978) — the trigger since 6 Oct 2026

**A meeting is processed only if its organiser ADDED "Meeting Notes" to it.** That replaced the Power Automate
folder watcher (`teams-recordings`), which submitted every recording in the organiser's OneDrive; the watcher and
the dev `meeting-minutes-notify` flow are STOPPED (`scripts/meeting_app_cutover.py`, `--rollback` restarts them).

**The path:** adding the app installs its bot in the meeting chat (registered in Redis: chat ↔ organiser ↔ Graph
meeting id) → ONE app-wide Graph subscription (`installedToOnlineMeetings/getAllRecordings`, resource-specific
consent, owned by the meeting app's identity) announces each recording → the app submits `meeting_to_transcript`
per lane with the recording handle AND the chat → speaker questions are posted in the meeting chat (a neutral card
for everyone; only the ORGANISER's client refreshes it into the form) → the organiser's answer is recorded in-process
through `approvals.human_decision` → the minutes run KEEPS its documents in the lab (no OneDrive write) → the app posts
the minutes card, records the files per recording and rebuilds ONE comparison across that recording's lanes → the
**Meeting Notes tab** lists and serves them to members of that chat only (Teams SSO token + roster check, every request).

**Graph access is option A**: the app's resource-specific grant PROVES a meeting opted in (`graph_repository.
_opted_in_path`, re-proved every `PROOF_TTL`), and graph-mcp's reader fetches the recording bytes, because Microsoft
cannot download a recording by RSC alone (401, unchanged by an application access policy — measured 5 Oct 2026).
Option B (grant `Lab-Collab-Read` per organiser instead of tenant-wide) is the hardening step.

**Provisioning** (`scripts/provision_meeting_app.py <host>`, `scripts/package_teams_app.py <host>`): one Entra app is
the bot, the RSC principal and the Teams SSO resource; it holds NO front-door role and NO virtual key (it works
in-process). The SSO setup is not optional — Teams silently fetches a token for `webApplicationInfo.resource` when the
app is added, and without an identifier URI, an `access_as_user` scope and the two Teams clients pre-authorised the add
fails with a generic error. Publish the package through Graph (`POST /appCatalogs/teamsApps`); the Teams upload dialog
reports schema violations as "UnknownError".

**Measured defects this design now carries fixes for** (6 Oct 2026): `refresh.userIds` must be the Teams id `29:…`;
microsoft-teams-apps 2.1.0 rejects `trigger:"automatic"` (middleware drops it; version pinned); a `::` bind is
IPv6-only (dual-stack sockets); Graph recording ids exceed the 200-character idempotency key (digest); the card's
answer names identity OR tag, never an empty one; Teams DESKTOP can hold stale app state after a catalogue
delete/republish — the web client is the differential test, clearing the desktop cache the fix.
