"""The SPEECH feature's slice of the contract: the speech port's tools, the two meeting processes and
the agents that run them. Re-exported by `lab.platform.contracts`, which is where every caller imports
them from; this module exists so the speech feature edits its own file instead of the shared one.

Imported by the package `__init__` AFTER the kernel types it builds on are defined — so import it only
through `lab.platform.contracts` (Python runs that `__init__` first either way).
"""
from __future__ import annotations

from lab.platform import config
from lab.platform.contracts import AgentSpec, InputField, InputKind, ProcessSpec, ToolCatalogue


class SpeechTools(ToolCatalogue):
    """The SPEECH port — recorded talk becoming attributable words. Vendor-neutral by construction:
    the alias is `speech_mcp` and the tools are `speech_*`; the provider is named only by the SERVICE
    (`speech-mcp` and its credential) and by the adapter the container resolves. The `ea_mcp` /
    `adoit-mcp` precedent, enforced by `test_no_tool_or_alias_names_a_vendor`.

    THE PORT RETURNS WORDS AND SPEAKER LABELS. It does not summarise, and that absence is structural:
    minutes, decisions and keywords are produced by the lab's own governed model through the gateway,
    so "the vendor does not summarise our meetings" is a property of the contract rather than a
    promise in a document.

    CONTENT BY REFERENCE, DIGEST INLINE. `transcribe` takes an `art://` reference and returns another
    one for the full segment timeline, plus the small things a caller actually needs in hand: the
    anonymous speaker digest, the duration, whether more than one language was recognised, and what
    the provider would not honour. An hour of speech is not an argument; a speaker list is.

    SPEAKER LABELS ARE ANONYMOUS AND PER REQUEST. `SPEAKER_00` means nothing beyond one call and is
    not stable across two, so mapping a label to a human is a separate, human-gated act — and
    re-linking labels across a split recording belongs to whoever split it.
    """
    SERVER = "speech_mcp"
    capabilities = "speech_capabilities"   # what THIS provider/plan actually serves, and why not
    transcribe = "speech_transcribe"
    # VOICEPRINTS. `identify` says which anonymous label sounds like someone the lab has met before —
    # a SUGGESTION the organiser confirms, never an answer. `enrol` KEEPS a voice, which is storing
    # biometric data, so it is its own grant: only the step that runs after a human answered (and
    # ticked consent) may hold it. Both take references and return names or counts — a vector never
    # crosses the gateway.
    identify = "speech_identify"
    enrol = "speech_enrol"

    READ = (capabilities, transcribe, identify)
    WRITE = (enrol,)


# The speech providers a run may name as its LANE. Declared HERE, in the contract, because it is a
# value an outside caller passes and every producer validates against — while the ADAPTERS live in
# `lab.substrate.container.SPEECH_PROVIDERS`, where their credentials are. The two are kept in step
# in BOTH directions by tests/governance/test_speech_provider_parity.py: a name here with no adapter
# is a run that will be accepted and then fail, and an adapter with no name here is one nobody can
# ask for. Naming a vendor is legitimate here for the same reason `adoit-mcp` may: this is the
# SERVICE, not a tool or an alias.
SPEECH_PROVIDERS: tuple[str, ...] = ("munsit", "elevenlabs", "assemblyai", "soniox", "soniox-en")

# The prose is shared because the field means the same thing in both processes, and a lane whose two
# halves described themselves differently would be the first place a reader would lose the thread.
_LANE = ("Which speech provider's LANE this run belongs to. Omit it to use the deployment's "
         "configured provider — a lab running one provider never passes it. Passing it runs this "
         "recording through that provider specifically, so several providers can each produce their "
         "own transcript, their own speaker question and their own minutes from the same meeting, "
         "without overwriting one another.")

MEETING_TO_TRANSCRIPT = ProcessSpec(
    name="meeting_to_transcript",
    group="wf-meeting-transcript",
    title="Meeting recording to a diarized transcript, with speaker attribution requested",
    description=(
        "Fetch ONE meeting recording from the collaboration platform into the lab's governed upload "
        "store, transcribe and separate the speakers, and ask the meeting's organiser — once, for "
        "every speaker at the same time — to say who each anonymous SPEAKER_nn label actually is: a "
        "directory identity, or a free tag for anyone outside the organisation. "
        "The run FINISHES when the question is asked. It returns an approval_id, and approving that "
        "approval automatically starts the run that writes the minutes. "
        "Transcription takes several minutes for an hour of audio, so it is asynchronous: submit "
        "returns a request_id immediately."),
    inputs=(
        InputField("owner", InputKind.IDENTITY,
                   "The meeting ORGANISER's directory identity — their user principal name (e.g. "
                   "maria@contoso.com) or their directory object id. This is the person who will be "
                   "asked to identify the speakers, so it must be someone who was actually in the "
                   "meeting. Not a display name, and not whoever triggered the flow."),
        InputField("recording", InputKind.HANDLE,
                   "The recording to transcribe: ONE collab://<kind>/<scope>/<id> handle exactly as "
                   "collab_recordings or collab_list handed it out. Never a download URL, never a "
                   "file path, and never the bytes — the run fetches it into the lab's own store "
                   "through the governed gateway. Video is fine; its audio is extracted."),
        InputField("provider", InputKind.CHOICE, _LANE, required=False,
                   choices=SPEECH_PROVIDERS),
        InputField("chat_id", InputKind.CONVERSATION,
                   "Optional id of the meeting's own conversation, when the caller already knows it "
                   "— the meeting app does, because it was added to that conversation. It is where the "
                   "finished minutes are announced. Omitted, the run looks the meeting up itself.",
                   required=False),
    ),
    outputs=("trace_id", "approval_id", "review_app", "recording_ref", "transcript_ref",
             "speakers", "candidates", "summary", "provider"),
)

TRANSCRIPT_TO_MINUTES = ProcessSpec(
    name="transcript_to_minutes",
    group="wf-meeting-minutes",
    title="Attributed transcript to minutes and keywords in the semantic layer",
    description=(
        "Rewrite a diarized transcript with the real speakers a human identified, then write the "
        "meeting's minutes — what it was about, what was decided, and who owes what — and load them "
        "into the semantic layer so later runs can ask what was decided about a thing and what a "
        "person committed to. The minutes are written by the lab's OWN governed model, never by the "
        "transcription vendor. "
        "Started ONLY by approving the speaker-mapping question of a meeting_to_transcript run: the "
        "attributed speakers are the answer a human gave, so there is no way to start this process "
        "correctly without going through that gate."),
    inputs=(
        InputField("transcript", InputKind.REF,
                   "ONE art://<id>/<name> reference to the DIARIZED segments a meeting_to_transcript "
                   "run produced (its `transcript_ref`): the utterances with their anonymous "
                   "SPEAKER_nn labels and timings."),
        InputField("speaker_map", InputKind.MAPPING,
                   "The organiser's answer: every SPEAKER_nn label in the transcript mapped to "
                   'exactly one of {"identity": "<user principal name>"} for someone in the '
                   'directory, or {"tag": "<free text>"} for anyone outside it. Every label the '
                   "transcript uses must appear exactly once — an unattributed speaker fails the run "
                   "rather than reaching the minutes as SPEAKER_03."),
        InputField("owner", InputKind.IDENTITY,
                   "The meeting organiser, recorded as the owner of the resulting minutes.",
                   required=False),
        InputField("chat_id", InputKind.CONVERSATION,
                   "Optional id of the meeting's own conversation, as the collaboration provider "
                   "reports it. Where the finished minutes are ANNOUNCED — the outputs are written "
                   "beside the recording either way, and this is what lets somebody be told. Only "
                   "the meeting_to_transcript run that resolved the meeting knows it, so it is "
                   "carried across the approval rather than looked up again; a run without it "
                   "delivers its files and stays quiet.", required=False),
        InputField("recording", InputKind.HANDLE,
                   "Optional collab://recording/<meeting>/<id> handle of the recording this "
                   "transcript came from. Its SCOPE is the meeting, so passing it is what lets the "
                   "minutes name the meeting they are about — and therefore what lets them be put "
                   "back beside it. Omitted, the run still writes minutes; it simply cannot say "
                   "which meeting they belong to.", required=False),
        InputField("provider", InputKind.CHOICE, _LANE, required=False,
                   choices=SPEECH_PROVIDERS),
        InputField("audio", InputKind.REF,
                   "Optional art://<id>/<name> reference to the RECORDING the transcript was made "
                   "from. It is what lets a voice the organiser named — and ticked consent for — be "
                   "kept as a voiceprint, so the next meeting can suggest who it is. Omitted, the "
                   "minutes are written exactly as before and no voice is kept.", required=False),
        InputField("reference", InputKind.REF,
                   "Optional art://<id>/<name> reference to the TENANT'S OWN transcript of the same "
                   "meeting occurrence (a WebVTT file). Each provider lane's transcript is scored against "
                   "it and the scores are written beside the recording. Omitted, nothing is compared.",
                   required=False),
    ),
    outputs=("trace_id", "transcript_ref", "minutes_ref", "model_id", "keywords", "summary",
             "provider",
             # how many voices this run kept, and why not when it kept none — best effort, like delivery
             "voiceprints",
             # the lanes compared against the tenant's own transcript so far, or why not
             "comparison",
             # what reached the collaboration platform, where to announce it, and why not when it
             # did not — delivery is best effort, so its outcome is reported rather than raised
             "delivered", "chat_id", "delivery"),
    products=('minutes_ref',),
    identity=("recording", "transcript"),
    # Continuation-only. `speaker_map` is a HUMAN'S answer to the approval the transcript run raised;
    # a caller who could submit this directly would supply their own attribution and bypass the one
    # gate the meeting pipeline has. The continuation runner starts it in-process, so this refusal
    # costs the legitimate path nothing.
    external=False,
)


#: The meeting pipeline's agents, in the order `AGENTS` lists them.
AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec(name="meeting-agent", prefix="MEETING_AGENT",
              description="Fetches a meeting recording and has it transcribed and diarized.",
              skills=("transcription",),                       # tool-only: every step deterministic
              processes=("meeting_to_transcript",)),
    AgentSpec(name="minutes-agent", prefix="MINUTES_AGENT",
              description="Turns an attributed transcript into gated minutes and a concept model.",
              skills=("minutes",), model=config.MINUTES_AGENT_MODEL,
              processes=("transcript_to_minutes",)),
)

# WHAT THIS SLICE CONTRIBUTES — the kernel's PROCESSES, AGENTS and SERVERS are assembled from these, so
# a new process, agent or catalogue here is an edit to this file alone.
PROCESSES: tuple[ProcessSpec, ...] = (MEETING_TO_TRANSCRIPT, TRANSCRIPT_TO_MINUTES)
CATALOGUES: tuple[type[ToolCatalogue], ...] = (SpeechTools,)

__all__ = ["SpeechTools", "SPEECH_PROVIDERS", "MEETING_TO_TRANSCRIPT", "TRANSCRIPT_TO_MINUTES",
           "PROCESSES", "AGENTS", "CATALOGUES"]
