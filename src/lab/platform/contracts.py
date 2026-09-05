"""The build-time CONTRACT between the substrate and the workloads — what a workload may rely on
without importing the substrate (CLAUDE.md tier rule: a workload reaches the substrate only over the
network, so what it compiles against lives here, in the kernel both tiers share). Pure data: no I/O,
no clients, importable by every tier.

  Tool catalogues   the tools each substrate MCP server registers, as typed constants, EXACTLY as
                    registered (`tests/governance/test_contracts_match_servers.py` enforces parity in
                    both directions), plus the gateway-qualified form the LiteLLM proxy exposes them
                    under (`<server alias>-<tool>`; aliases per config/litellm-config.yaml `mcp_servers`).
  ArtifactRef       the `art://<id>/<name>[#<page>]` reference — the only handle a workload holds on an
                    input or an artifact (the substrate's stores mint and resolve them).
  Approval contract request kinds, decision values and status names of the human-in-the-loop gate,
                    plus `ApprovalTools` — the gate as governed tools (on workflow-mcp), split into
                    a READ grant and the human-gated WRITE (`approvals_decide`).
  Workflow requests the `workflow:requests` event (statuses, field names) a host consumes.
  Process registry  every business PROCESS declared once (`PROCESSES`): how it is addressed, what a
                    caller must know about it, its typed INPUT CONTRACT and the outputs a finished run
                    publishes. workflow-mcp generates its tools from this, so registering a process is
                    one entry here — no code change in the server.

Adding a tool = one constant on its catalogue (the parity test fails until it matches the server).
Adding a process = one `ProcessSpec` in `PROCESSES` (+ its consumer group in lab.platform.workflows.GROUPS).
"""
from __future__ import annotations

import json
import mimetypes
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

_GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


# ----------------------------------------------------------------------------- tool catalogues
def gateway_name(server: str, tool: str) -> str:
    """The name the gateway exposes a server's tool under: `<server alias>-<tool>`."""
    return f"{server}-{tool}"


class ToolCatalogue:
    """Base of the per-server catalogues: `SERVER` is the gateway alias; every other public class
    attribute is a tool name as the server registers it."""

    SERVER: str = ""

    @classmethod
    def names(cls) -> frozenset[str]:
        return frozenset(v for k, v in vars(cls).items()
                         if not k.startswith("_") and k != "SERVER" and isinstance(v, str))

    @classmethod
    def gateway(cls, tool: str) -> str:
        if tool not in cls.names():
            raise ValueError(f"{tool!r} is not a {cls.SERVER} tool")
        return gateway_name(cls.SERVER, tool)


class StorageTools(ToolCatalogue):
    """storage-mcp — READ-ONLY governed access to the upload store (the only way a workload reads an input)."""
    SERVER = "storage_mcp"
    list = "storage_list"
    info = "storage_info"
    get = "storage_get"
    read_document = "storage_read_document"
    read_vsdx = "storage_read_vsdx"
    render_vsdx = "storage_render_vsdx"      # the SAME page as a picture: the vision representation
    extract_figures = "storage_extract_figures"


class SemanticTools(ToolCatalogue):
    """semantic-mcp — vocabularies as data, legality, SPARQL, reference models; `store_spec` persists any JSON by ref."""
    SERVER = "semantic_mcp"
    ontologies = "semantic_ontologies"
    describe = "semantic_describe"
    classify = "semantic_classify"
    check = "semantic_check"
    validate_model = "semantic_validate_model"
    load_model = "semantic_load_model"
    query = "semantic_query"
    schemes = "semantic_schemes"
    concepts = "semantic_concepts"
    export_archimate = "semantic_export_archimate"
    store_spec = "semantic_store_spec"
    questions = "semantic_questions"
    ask = "semantic_ask"


class EATools(ToolCatalogue):
    """The EA-repository PORT (+ the ArchiMate engine services), vendor-neutral: the tools an EA
    repository must offer a workload — read the existing architecture, stage a model for a human-gated
    write. Today's ADAPTER is `adoit-mcp` (it holds the ADOIT credentials and knows that hosted CE
    needs a spreadsheet imported by a human); swapping in another EA tool is a different server
    registering these SAME names under the SAME gateway alias — no workload change. The vendor is
    named by the SERVICE (adoit-mcp, ADOIT_MCP_URL, its credentials), never here.
    `archimate_validate` / `archimate_render` are DOMAIN (engine) services, not repository operations:
    they sit on this server only because the engine does, and belong with the modelling side if it splits."""
    SERVER = "ea_mcp"
    validate = "archimate_validate"
    render = "archimate_render"
    repositories = "ea_repositories"
    search = "ea_search"
    object = "ea_object"
    stage_import = "ea_stage_import"
    import_status = "ea_import_status"
    import_instructions = "ea_import_instructions"


class WorkflowTools(ToolCatalogue):
    """workflow-mcp — the governed front door to every business PROCESS. Its process tools are not fixed
    constants: they are GENERATED per entry in `PROCESSES` below (`<process>_submit`,
    `<process>_status`, `<process>_result`), so registering a process is the one place that changes.
    The same server also carries the APPROVAL tools (`ApprovalTools` below) — a run PAUSES for a human
    approval, so the pause is part of the lifecycle this front door exposes.

    A CONTINUATION-ONLY process (`ProcessSpec.external` false) contributes only status and result: it
    has no submit tool because there is no way to start it correctly except by approving the question
    that produced its input. The catalogue must say so, not merely the server — this is the PORT, it
    is what a team grant names and what `test_contracts_match_servers` checks in both directions, so a
    name here that no server exposes is exactly the drift that test exists to catch.
    """
    SERVER = "workflow_mcp"
    VERBS = ("submit", "status", "result")             # a tuple, so `names()`'s string filter ignores it

    @classmethod
    def verbs_for(cls, spec: "ProcessSpec") -> tuple[str, ...]:
        """The tools this process actually gets. One place, read by the catalogue and by the server's
        registration, so the two cannot disagree about what exists."""
        return cls.VERBS if spec.external else tuple(v for v in cls.VERBS if v != "submit")

    @classmethod
    def names(cls) -> frozenset[str]:
        return (frozenset(spec.tool(v) for spec in PROCESSES.values() for v in cls.verbs_for(spec))
                | ApprovalTools.names())


class ApprovalTools(ToolCatalogue):
    """The human-in-the-loop GOVERNANCE surface — list / read / DECIDE an approval. Registered on
    workflow-mcp (same gateway alias, hence `SERVER` below, and NOT a separate entry in `SERVERS`):
    a run pauses for an approval and `<process>_status` already hands back the `approval_id`, so one
    server = one connector for a channel that must follow a run from submit to decision.

    TWO GRANTS, not one. `READ` is safe for anything that shows a human what is waiting; `decide`
    RECORDS A HUMAN'S DECISION to release an EA-repository write and must reach only a channel that
    carries a signed-in user (Teams/Copilot Studio, the review app) — never a workload's own agents.
    The gateway enforces the split per team with `mcp_tool_permissions` (per-tool ACL on the same
    `object_permission` as the server grant):

        read-only  {"object_permission": {"mcp_servers": ["workflow_mcp"],
                    "mcp_tool_permissions": {"workflow_mcp": list(ApprovalTools.READ)}}}
        + decide   … + list(ApprovalTools.WRITE)
    """
    SERVER = "workflow_mcp"
    list = "approvals_list"
    get = "approvals_get"
    ask = "approvals_ask"
    decide = "approvals_decide"

    # THREE GRANTS, and the split is the control. READ shows a human what is waiting. RAISE asks a
    # question — a workload's own step needs this, because a workload may not import the substrate
    # and so has no other way to reach the gate. WRITE answers, and must reach only a channel
    # carrying a signed-in person. A workload gets RAISE and never WRITE: asking must never imply
    # the ability to answer your own question.
    READ = (list, get)          # the GRANTS, as tuples so `names()`'s string filter ignores them
    RAISE = (ask,)              # a workload's step, over the gateway — it publishes, never decides
    WRITE = (decide,)           # the human-gated write — granted deliberately, never by default


class ApiRoles:
    """Entra APP ROLES for the front door's REST ingress (`/api`) — the caller-facing half of the
    same governance the MCP ingress gets from per-tool ACLs.

    WHY ROLES AND NOT TOOL ACLs. The gateway gates MCP by server and tool name; a REST path is
    neither, so `mcp_tool_permissions` cannot see one. An app role is what an Entra app registration
    can actually be granted, it arrives in the `roles` claim of the client-credentials token the
    caller already presents, and it is what APIM's `<required-claims>` checks — so the same three
    strings survive the migration untouched.

    ONE ROLE PER POWER, and the split is the control. `SUBMIT` starts work. `READ` shows a human what
    is waiting. `DECIDE` records what they said — the power that releases a run, and the one a relay
    should have to be granted deliberately rather than inherit from being able to read. The mapping
    from operation to role is `lab.substrate.apipolicy`, kept apart from this vocabulary so the
    enforcement point can move without touching either.

    NOT a grant on WHICH process may be started: that is `ProcessSpec.external`, because it is true of
    every caller and a role check would have to be re-granted correctly forever to say the same thing.
    """

    SUBMIT = "Workflow.Submit"
    READ = "Approvals.Read"
    DECIDE = "Approvals.Decide"

    ALL: tuple[str, ...] = (SUBMIT, READ, DECIDE)


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


class CollabTools(ToolCatalogue):
    """The COLLABORATION port — the files people keep and the meetings they hold. Vendor-neutral by
    construction: a Microsoft Graph adapter (`graph-mcp`) satisfies it today, and a Google Workspace
    or Box + Zoom adapter could satisfy the SAME tools tomorrow with no caller change. The vendor
    lives in the SERVICE (`graph-mcp`, `GRAPH_*` credentials), never here — the `ea_mcp` / `adoit-mcp`
    precedent, enforced by `test_no_tool_or_alias_names_a_vendor`.

    Content is never returned inline: a listing mints an opaque handle (`lab.core.collab.ContentHandle`)
    and `collab_fetch` streams the bytes into the UPLOAD store, returning an `art://` ref the workload
    reads through storage-mcp. A recording is gigabytes; an agent's context is not.

    TWO GRANTS, like ApprovalTools. `READ` queries and fetches. `WRITE` manages change-notification
    subscriptions — which is egress to a CALLER-SUPPLIED url and a durable object that outlives the
    run, so it must never reach a workload's own agents:

        read-only  {"object_permission": {"mcp_servers": ["collab_mcp"],
                    "mcp_tool_permissions": {"collab_mcp": list(CollabTools.READ)}}}
        + watch    … + list(CollabTools.WRITE)
    """
    SERVER = "collab_mcp"
    capabilities = "collab_capabilities"     # what THIS tenant/credential actually allows, and why not
    sites = "collab_sites"
    drives = "collab_drives"
    user_drive = "collab_user_drive"         # a PERSON's own drive: content no team ever filed
    list = "collab_list"
    item = "collab_item"
    meetings = "collab_meetings"
    recordings = "collab_recordings"
    transcripts = "collab_transcripts"
    fetch = "collab_fetch"                   # handle -> art:// ref, streamed into the upload store
    watches = "collab_watches"
    watch = "collab_watch"
    watch_renew = "collab_watch_renew"
    unwatch = "collab_unwatch"

    READ = (capabilities, sites, drives, user_drive, list, item, meetings, recordings, transcripts,
            fetch, watches)
    WRITE = (watch, watch_renew, unwatch)    # tuples, so `names()`'s string filter ignores them


# ----------------------------------------------------------------------------- artifact references
_SCHEME = "art://"


def split_fragment(src: str) -> tuple[str, str | None]:
    """(base, page) for any source — a path or an `art://` ref. A `#<page>` fragment selects ONE page of a
    multi-page .vsdx (`malaffi.vsdx#Shafafiya`, `art://<id>/malaffi.vsdx#Shafafiya`). The ONE parser:
    `lab.platform.docparse` re-exports this, so a ref and a path are split identically."""
    base, _, frag = (src or "").partition("#")
    return base, (frag.strip() or None)


@dataclass(frozen=True)
class ArtifactRef:
    """`art://<id>/<name>[#<page>]` — an artifact or input in a substrate store, by reference. The
    optional `#<page>` fragment selects ONE page of a multi-page .vsdx (`split_fragment` above — the
    same parser `lab.platform.docparse` uses for paths). `str(ref)` round-trips the parsed text."""

    id: str
    name: str
    page: str | None = None

    @staticmethod
    def is_ref(src: Any) -> bool:
        """The cheap syntactic check (a path is not a ref)."""
        return isinstance(src, str) and src.startswith(_SCHEME)

    @classmethod
    def parse(cls, ref: str) -> "ArtifactRef":
        if not cls.is_ref(ref):
            raise ValueError(f"not an artifact ref: {ref!r}")
        base, page = split_fragment(ref[len(_SCHEME):])
        aid, _, name = base.partition("/")
        if not aid or not name:
            raise ValueError(f"malformed artifact ref (want art://<id>/<name>): {ref!r}")
        return cls(aid, name, page)

    @property
    def base(self) -> str:
        """The ref without its page fragment — what is loaded/stored."""
        return f"{_SCHEME}{self.id}/{self.name}"

    def __str__(self) -> str:
        return self.base + (f"#{self.page}" if self.page else "")


# ----------------------------------------------------------------------------- approval gate
class ApprovalKind(StrEnum):
    """What a human is being asked to release. VENDOR-NEUTRAL, like the port itself: an approval is
    "a write into the EA repository", never "an ADOIT import" — the adapter behind the port may be
    any EA tool and nothing downstream (the review app, Teams, Telegram, the CLI, approvals_list)
    dispatches on the vendor.

    COMPAT: approvals staged before this rename carry `kind: "adoit-import"`. Nothing DISPATCHES on
    kind — `approvals.pending()` is kind-agnostic and the review app lists, opens and decides by
    request id — so those requests keep working untouched; only an explicit `approvals_list(kind=…)`
    filter, which is triage and not a boundary, will not match them (omit the filter to see them).
    The value is deliberately NOT aliased back to the old string: a vendor word in the contract is
    exactly what `tests/governance/test_contracts_match_servers.py` exists to prevent."""

    EA_IMPORT = "ea-import"
    # A human is not releasing a write here — they are ANSWERING a question the run could not
    # answer itself: which anonymous speaker is which person. Same gate, same audit log, same
    # channels; nothing dispatches on this value, which is what keeps that true.
    SPEAKER_MAPPING = "speaker-mapping"


@dataclass(frozen=True)
class ImportArtifact:
    """ONE file a human must carry into the EA repository, described BY THE ADAPTER that made it.

    This is how a repository's import files stay OPAQUE to everything upstream. The adapter knows what
    it produced and why (an ADOIT:CE object spreadsheet matched by name, a views XML, a change-set
    bundle, or — on a repository that writes over its own API — nothing at all); the approval carries
    that as a list of {ref, label, note}, and a channel showing it to a human RENDERS the label and
    the note and offers the ref as a download. No reviewer surface has to know what a spreadsheet is.

    The adapter supplies MEANING only: `filename` and `mime` are derived from the ref, so an adapter
    cannot mislabel its own artifact; `media_type` overrides the guess when an extension is ambiguous."""

    ref: str                   # art://<id>/<name> (or, in local dev, a path)
    label: str                 # what the human sees on the download — the adapter's words
    note: str = ""             # one line of guidance shown beside it (how this file is imported)
    media_type: str = ""       # override for the MIME guessed from the filename

    def __post_init__(self) -> None:
        if not (self.ref or "").strip() or not (self.label or "").strip():
            raise ValueError("an import artifact needs both a ref and a label")

    @property
    def filename(self) -> str:
        """The name to save it under: the last path segment of the ref, without any `#page` fragment."""
        return split_fragment(self.ref)[0].rstrip("/").rsplit("/", 1)[-1]

    @property
    def mime(self) -> str:
        return self.media_type or mimetypes.guess_type(self.filename)[0] or "application/octet-stream"

    def to_dict(self) -> dict[str, str]:
        return {"ref": self.ref, "label": self.label, "note": self.note, "media_type": self.media_type}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ImportArtifact":
        return cls(ref=d["ref"], label=d["label"], note=d.get("note", "") or "",
                   media_type=d.get("media_type", "") or "")


def import_artifacts(payload: dict[str, Any]) -> list[ImportArtifact]:
    """The files a human must import for one approval, in the adapter's own order — the ONE reader of
    an approval payload's artifact list, shared by the review app and the approval MCP tools.

    LEGACY payloads (staged before the neutral shape: a flat `xml_ref` + `xlsx_ref` + …) still render:
    every `*_ref` string in the payload becomes a download labelled by its own filename. That rule is
    GENERIC — it names no vendor and knows no file type — so an old request stays fully usable by a
    reviewer without this module, or the review app, learning what any of those files were."""
    declared = payload.get("import_artifacts")
    if declared is not None:
        return [ImportArtifact.from_dict(d) for d in declared]
    return [ImportArtifact(ref=v, label=ImportArtifact(v, "?").filename)
            for k, v in payload.items() if k.endswith("_ref") and isinstance(v, str) and v.strip()]


class Decision(StrEnum):
    """What a human may answer; `update` = changes requested, the request stays open."""
    APPROVE = "approve"
    DECLINE = "decline"
    UPDATE = "update"


class ApprovalStatus(StrEnum):
    """A request's status: pending until a decision, then the decision itself."""
    PENDING = "pending"
    APPROVE = "approve"
    DECLINE = "decline"
    UPDATE = "update"


APPROVAL_FINAL = frozenset({ApprovalStatus.APPROVE, ApprovalStatus.DECLINE})   # `update` = changes requested, still open


# ----------------------------------------------------------------------------- asking a human a question
# An approval already carries a rich question OUTWARD: its payload is schema-free JSON, so a speaker
# list needs nothing new to travel. What is missing is the way BACK — a decision carries only the
# decision, an actor and a comment, which is enough to RELEASE a staged write and not enough to
# ANSWER one. These types close that gap while keeping the gate itself generic.


@dataclass(frozen=True)
class SpeakerPrompt:
    """ONE anonymous speaker a human is asked to identify, described by the step that HEARD it.

    The `ImportArtifact` pattern in the other direction: the producer supplies the meaning (how long
    this voice spoke, how often, and a few verbatim utterances), every channel renders it, and none
    of them interpret it. Samples are what actually let a person tell voices apart; duration and turn
    count are what let them tell a main participant from someone who said "yes" twice.
    """

    label: str
    samples: tuple[str, ...] = ()
    seconds: float = 0.0
    turns: int = 0

    def __post_init__(self) -> None:
        if not (self.label or "").strip():
            raise ValueError("a speaker prompt needs its label — the answer is keyed on it")

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "samples": list(self.samples), "seconds": self.seconds,
                "turns": self.turns}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SpeakerPrompt":
        return cls(label=str(d.get("label") or ""), samples=tuple(d.get("samples") or ()),
                   seconds=float(d.get("seconds") or 0.0), turns=int(d.get("turns") or 0))


def speaker_prompts(payload: dict[str, Any]) -> list[SpeakerPrompt]:
    """The speakers one approval asks about, in the order the payload declared them.

    The ONE reader, shared by the review app, the chat cards and the approval tools, so three
    surfaces cannot drift into three slightly different renderings of the same question. A payload
    that asks nothing yields nothing rather than raising: most approvals are not questions.
    """
    items = ((payload or {}).get("question") or {}).get("items") or []
    return [SpeakerPrompt.from_dict(i) for i in items if isinstance(i, dict)]


@dataclass(frozen=True)
class SpeakerIdentity:
    """One human's answer for one speaker: a directory identity, or else a free tag.

    Exactly one of the two, because not everyone in a meeting room is in the directory and pretending
    otherwise would either lose the external participants or invent identities for them. Both at once
    is ambiguous and refused.
    """

    label: str
    identity: str = ""          # a directory principal — preferred, and resolvable later
    tag: str = ""               # else free text: an external, a guest, "the vendor's architect"

    def __post_init__(self) -> None:
        if not (self.label or "").strip():
            raise ValueError("a speaker answer needs the label it answers for")
        if bool(self.identity.strip()) == bool(self.tag.strip()):
            raise ValueError(f"{self.label}: give exactly one of identity or tag, not both or neither")

    @property
    def display(self) -> str:
        """What the attributed transcript says — never the raw address.

        The gateway's guardrail pseudonymises addresses in every request body, so a transcript full
        of them reaches a model as placeholders and degrades silently the moment the model
        paraphrases one instead of repeating it verbatim. The address stays in the audit log and the
        structured artifact; what the model reads is a name.
        """
        return self.tag.strip() or self.identity.split("@")[0].strip()

    def to_dict(self) -> dict[str, str]:
        return {"identity": self.identity} if self.identity.strip() else {"tag": self.tag}


@dataclass(frozen=True)
class SpeakerMap:
    """Every speaker in one transcript, answered together — the user's choice of ONE decision for all."""

    entries: tuple[SpeakerIdentity, ...] = ()

    def to_answer(self) -> dict[str, dict[str, str]]:
        return {e.label: e.to_dict() for e in self.entries}

    @classmethod
    def from_answer(cls, answer: dict[str, Any]) -> "SpeakerMap":
        return cls(tuple(SpeakerIdentity(label=k, identity=str((v or {}).get("identity") or ""),
                                         tag=str((v or {}).get("tag") or ""))
                         for k, v in (answer or {}).items()))

    def of(self, label: str) -> SpeakerIdentity:
        for e in self.entries:
            if e.label == label:
                return e
        raise KeyError(f"{label} was never mapped — every label the transcript uses must be answered")


def check_answer(payload: dict[str, Any], answer: dict[str, Any] | None) -> dict[str, Any] | None:
    """The answer this approval asked for, or ValueError naming exactly what is wrong.

    GENERIC BY DESIGN, and that is the point. A payload declares `answer_labels` (the keys that must
    each be answered exactly once) and `answer_required`; nothing here knows what a speaker is, so
    the approval KIND never becomes a dispatch and the gate stays one implementation for every
    channel. The per-value shape is the typed object's business, built by whichever surface collects
    the answer.

    An approval that asks nothing accepts no answer — otherwise any channel could smuggle arbitrary
    state onto any request.
    """
    wanted = list((payload or {}).get("answer_labels") or [])
    if not wanted:
        if answer:
            raise ValueError("this approval asks no question, so it takes no answer")
        return None
    if not answer:
        if (payload or {}).get("answer_required", True):
            raise ValueError(f"this approval needs an answer for {wanted}")
        return None
    given = set(answer)
    missing, unknown = sorted(set(wanted) - given), sorted(given - set(wanted))
    if missing:
        raise ValueError(f"the answer is incomplete — nothing given for {missing}")
    if unknown:
        raise ValueError(f"the answer names {unknown}, which this approval did not ask about")
    return answer


# ----------------------------------------------------------------------------- what approving releases
@dataclass(frozen=True)
class Continuation:
    """The run one approval releases when a human approves it.

    Declared on the approval PAYLOAD rather than in the process registry, because a static "A is
    followed by B" edge cannot carry the run-specific inputs of THIS run — the reference to the
    transcript this particular meeting produced. The payload is the only place that knows both the
    question and what answering it completes.

    Validated at construction: a typo in the process name or the bound input would otherwise be
    discovered hours later, when a human approves and nothing whatsoever happens.
    """

    process: str
    inputs: dict[str, Any]
    answer_input: str = ""      # the input field the human's answer binds to ("" = answer discarded)
    requester: str = ""

    def __post_init__(self) -> None:
        spec = PROCESSES.get(self.process)
        if spec is None:
            raise ValueError(f"continuation names unknown process {self.process!r} — "
                             f"one of {sorted(PROCESSES)}")
        if self.answer_input and self.answer_input not in {f.name for f in spec.inputs}:
            raise ValueError(f"{self.answer_input!r} is not an input of {self.process} — "
                             f"one of {sorted(f.name for f in spec.inputs)}")

    def to_dict(self) -> dict[str, Any]:
        return {"process": self.process, "inputs": dict(self.inputs),
                "answer_input": self.answer_input, "requester": self.requester}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Continuation":
        return cls(process=str(d.get("process") or ""), inputs=dict(d.get("inputs") or {}),
                   answer_input=str(d.get("answer_input") or ""),
                   requester=str(d.get("requester") or ""))


def continuation_of(payload: dict[str, Any]) -> Continuation | None:
    """The run one approval releases, or None — the ONE reader, shared by the continuation runner and
    any surface that wants to show a reviewer what approving will actually start.

    A malformed continuation raises rather than being ignored: ignoring it means an approved run
    simply never starts, with nothing anywhere to chase.
    """
    raw = (payload or {}).get("continuation")
    return Continuation.from_dict(raw) if isinstance(raw, dict) and raw else None


# ----------------------------------------------------------------------------- workflow requests
class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


WORKFLOW_FINISHED = frozenset({WorkflowStatus.DONE, WorkflowStatus.FAILED})
WORKFLOW_OPEN = frozenset({WorkflowStatus.PENDING, WorkflowStatus.RUNNING})


@dataclass(frozen=True)
class WorkflowRequest:
    """One `workflow:requests` event / `workflow:req:<id>` hash as published by a producer (the
    review app's Submit, the CLI). Progress fields the consumer writes back (trace_id, approval_id,
    error, …) are not part of the request contract and are ignored on `from_fields`."""

    request_id: str
    process: str
    inputs: dict[str, Any]            # {"diagram": art://…, "requirements": [art://…]} for visio_to_archimate
    requester: str
    created_at: str
    created_ts: str
    status: WorkflowStatus = WorkflowStatus.PENDING

    @property
    def diagram(self) -> str:
        return self.inputs["diagram"]

    @property
    def requirements(self) -> list[str]:
        return list(self.inputs.get("requirements") or [])

    def to_fields(self) -> dict[str, str]:
        """The Redis hash / stream entry (every value a string; `inputs` JSON-encoded)."""
        return {"request_id": self.request_id, "process": self.process, "inputs": json.dumps(self.inputs),
                "requester": self.requester, "status": self.status.value,
                "created_at": self.created_at, "created_ts": self.created_ts}

    @classmethod
    def from_fields(cls, fields: dict[str, str]) -> "WorkflowRequest":
        return cls(request_id=fields["request_id"], process=fields["process"], inputs=json.loads(fields["inputs"]),
                   requester=fields["requester"], created_at=fields["created_at"], created_ts=fields["created_ts"],
                   status=WorkflowStatus(fields["status"]))


# ----------------------------------------------------------------------------- process registry
class InputKind(StrEnum):
    """How one input field is carried.

    The first two are `art://` references (or, for local dev, a path): a workload holds no store
    credentials, so CONTENT is always passed by reference. The other three exist so a low-code
    trigger can start a run in ONE call — carrying who owns a recording, a reference to it at the
    provider, and a human's answer — none of which is content and none of which is an `art://` ref.

    Deliberately absent: a general "text" kind. It would admit a URL, a whole document or an injected
    prompt into a contract whose entire discipline is by-reference. When a process genuinely needs
    free text, that is the moment to argue for it.
    """
    REF = "ref"            # exactly one reference to content in the lab's own store
    REF_LIST = "ref_list"  # zero or more of those
    HANDLE = "handle"      # ONE opaque provider handle (ids only — never a URL, never a credential)
    IDENTITY = "identity"  # ONE directory principal: who a question is asked of, or who owns a thing
    MAPPING = "mapping"    # a SMALL flat object of label -> {field: value}, from a human's answer


# A mapping is a human's answer, not a payload. Bounded so it can never become a way to smuggle
# arbitrary state through an input contract that is otherwise strictly by-reference.
MAX_MAPPING_ENTRIES = 64
MAX_MAPPING_BYTES = 8192


@dataclass(frozen=True)
class InputField:
    """One field of a process's input contract: its name, kind, prose (the JSON-schema description an
    agent reads) and whether it is required. `coerce` is the validator, and it is now the ONE
    validator every producer shares: the front door's MCP tools, its REST routes, the review app's
    Submit page and the CLI all reach it through `workflows.submit`, so no surface can accept what
    another would refuse."""

    name: str
    kind: InputKind
    description: str
    required: bool = True

    def coerce(self, value: Any) -> Any:
        """The normalised value, or ValueError naming the field. `None`/absent is legal only when the
        field is optional (a REF_LIST then normalises to [])."""
        # `{}` is absence too, and it slips past the checks above — an empty mapping is a human who
        # answered nothing, not a human who answered "nothing".
        if value is None or value == "" or value == [] or value == {}:
            if self.required:
                raise ValueError(f"{self.name} is required")
            return [] if self.kind is InputKind.REF_LIST else None
        if self.kind is InputKind.HANDLE:
            return self._handle(value)
        if self.kind is InputKind.IDENTITY:
            return self._identity(value)
        if self.kind is InputKind.MAPPING:
            return self._mapping(value)
        if self.kind is InputKind.REF:
            return self._one(value)
        if isinstance(value, str) or not isinstance(value, (list, tuple)):
            raise ValueError(f"{self.name} must be a list of references, got {type(value).__name__}")
        return [self._one(v) for v in value]

    def _one(self, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{self.name} must be a non-empty reference string")
        value = value.strip()
        if ArtifactRef.is_ref(value):
            ArtifactRef.parse(value)          # raises ValueError on a malformed ref
        elif "://" in value:                  # a URL is never an input: uploads live in the lab's store
            raise ValueError(f"{self.name}: {value!r} is not an art:// reference (upload the file first)")
        return value


    def _handle(self, value: Any) -> str:
        """One opaque provider handle. Parsed by the domain's own type, which already refuses
        anything that looks like a URL or a credential — the same guarantee `_one` gives for refs,
        for free, and in one place rather than re-implemented here."""
        from lab.core.collab.model import ContentHandle       # platform may import core

        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{self.name} must be a non-empty handle string")
        try:
            return str(ContentHandle.parse(value.strip()))
        except ValueError as e:
            raise ValueError(f"{self.name}: {e}") from e

    def _identity(self, value: Any) -> str:
        """One directory principal — a user principal name, an address, or a directory object id.

        Not a display name: this is who a question gets asked of, so it has to resolve. Refusing
        "Maria Perez" here costs a moment; discovering it when nobody can be asked costs a run.
        """
        text = value.strip() if isinstance(value, str) else ""
        if not text or any(c.isspace() for c in text) or "://" in text:
            raise ValueError(f"{self.name} must be a directory principal "
                             f"(a user principal name or an object id), got {value!r}")
        local, at, domain = text.partition("@")
        if at and local and "." in domain:
            return text
        if _GUID.fullmatch(text):
            return text
        raise ValueError(f"{self.name}: {text!r} is not a principal — expected "
                         "name@domain or a directory object id, not a display name")

    def _mapping(self, value: Any) -> dict[str, dict[str, str]]:
        """A small flat object of label -> {field: value}: a human's answer, carried into the next run.

        Bounded, and flat by construction. An input contract that is otherwise strictly
        by-reference must not grow a hole through which a document, a URL or a prompt can travel.
        """
        if not isinstance(value, dict):
            raise ValueError(f"{self.name} must be an object of label -> answer, "
                             f"got {type(value).__name__}")
        if len(value) > MAX_MAPPING_ENTRIES:
            raise ValueError(f"{self.name} has {len(value)} entries, more than the "
                             f"{MAX_MAPPING_ENTRIES} an answer may carry")
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_MAPPING_BYTES:
            raise ValueError(f"{self.name} is larger than the {MAX_MAPPING_BYTES} bytes an answer "
                             "may carry — an answer is a mapping, not a payload")
        out: dict[str, dict[str, str]] = {}
        for key, entry in value.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError(f"{self.name} has an entry with no label")
            if not isinstance(entry, dict) or not entry:
                raise ValueError(f"{self.name}[{key}] must be a non-empty object of field -> value")
            for field, v in entry.items():
                if not isinstance(field, str) or not isinstance(v, str) or not v.strip():
                    raise ValueError(f"{self.name}[{key}].{field} must be a non-empty string")
            out[key.strip()] = {f: v.strip() for f, v in entry.items()}
        return out


@dataclass(frozen=True)
class ProcessSpec:
    """One business process, declared ONCE: how it is addressed (name + the Redis consumer group of the
    host that runs it), what a human/agent needs to know about it, its typed input contract, and the
    fields its finished run publishes. Every external surface (workflow-mcp today; REST/A2A later) is
    generated from this — adding a process is one entry in `PROCESSES`, not a code change."""

    name: str                          # the `process` field of a workflow:requests event
    group: str                         # the consumer group of the host that runs it (lab.platform.workflows.GROUPS)
    title: str
    description: str                   # what it does, for a tool description an agent reads unaided
    inputs: tuple[InputField, ...]
    outputs: tuple[str, ...] = ()      # request-hash fields a finished run publishes
    # May an OUTSIDE caller START this process? Some processes are a CONTINUATION of another — they
    # exist to run after a human answered a question, and starting one directly would skip the gate
    # that gave it its input. That is a property of the PROCESS, not a permission on a caller, so it
    # is declared here and refused on every external surface at once. Note the asymmetry: submit is
    # refused, status/result are not — a caller may always observe a run it caused indirectly.
    external: bool = True

    def tool(self, verb: str) -> str:
        """The name of one of this process's generated tools (`<process>_<verb>`)."""
        if verb not in WorkflowTools.VERBS:
            raise ValueError(f"{verb!r} is not one of {WorkflowTools.VERBS}")
        return f"{self.name}_{verb}"

    def field(self, name: str) -> InputField:
        for f in self.inputs:
            if f.name == name:
                return f
        raise ValueError(f"{self.name} has no input {name!r}")

    def validate(self, values: dict[str, Any]) -> dict[str, Any]:
        """The `inputs` payload of a workflow:requests event, or ValueError. Unknown keys are refused
        (a typo must not be silently dropped); optional fields absent from `values` stay absent."""
        unknown = sorted(set(values) - {f.name for f in self.inputs})
        if unknown:
            raise ValueError(f"{self.name}: unknown input(s) {unknown}; expected "
                             f"{[f.name for f in self.inputs]}")
        out: dict[str, Any] = {}
        for f in self.inputs:
            v = f.coerce(values.get(f.name))
            if v is not None:
                out[f.name] = v
        return out


VISIO_TO_ARCHIMATE = ProcessSpec(
    name="visio_to_archimate",
    group="wf-visio",
    title="Visio/diagram to ArchiMate model",
    description=(
        "Turn a system diagram — a Microsoft Visio .vsdx or a diagram image — plus any requirements "
        "documents into a validated ArchiMate 3.1 model of that system, matched against the existing "
        "architecture in the EA repository and staged for human approval before import. "
        "A run takes 10-20 minutes, so it is asynchronous: submit returns a request_id immediately."),
    inputs=(
        InputField("diagram", InputKind.REF,
                   "The diagram to read: ONE art://<id>/<name> reference to a .vsdx file or a diagram "
                   "image (.png/.jpg) already uploaded to the lab's upload store. Append #<page> to "
                   "read a single page of a multi-page .vsdx."),
        InputField("requirements", InputKind.REF_LIST,
                   "Optional art:// references to requirements documents (.docx/.pdf/.md/.txt) that "
                   "describe the same system; they are used as evidence about the diagram, never as a "
                   "source of elements the diagram does not show.", required=False),
    ),
    # `import_artifacts` is the repository-agnostic replacement for the old `xlsx_ref`: whatever THIS
    # EA repository needs a human to import, as [{ref, label, note, media_type}] — possibly empty.
    outputs=("trace_id", "approval_id", "review_app", "xml_ref", "import_artifacts", "summary"),
)

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
    ),
    outputs=("trace_id", "approval_id", "review_app", "recording_ref", "transcript_ref",
             "speakers", "summary"),
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
    ),
    outputs=("trace_id", "transcript_ref", "minutes_ref", "model_id", "keywords", "summary"),
    # Continuation-only. `speaker_map` is a HUMAN'S answer to the approval the transcript run raised;
    # a caller who could submit this directly would supply their own attribution and bypass the one
    # gate the meeting pipeline has. The continuation runner starts it in-process, so this refusal
    # costs the legitimate path nothing.
    external=False,
)

PROCESSES: dict[str, ProcessSpec] = {p.name: p for p in (VISIO_TO_ARCHIMATE, MEETING_TO_TRANSCRIPT,
                                                         TRANSCRIPT_TO_MINUTES)}


# ----------------------------------------------------------------------------- the registry of servers
# Last, because WorkflowTools' tool names are derived from PROCESSES above.
SERVERS: dict[str, type[ToolCatalogue]] = {c.SERVER: c for c in (StorageTools, SemanticTools, EATools,
                                                                 WorkflowTools, CollabTools,
                                                                 SpeechTools)}
ALL_TOOLS: frozenset[str] = frozenset(n for c in SERVERS.values() for n in c.names())


__all__ = ["gateway_name", "ToolCatalogue", "StorageTools", "SemanticTools", "EATools", "WorkflowTools",
           "ApprovalTools", "ApiRoles", "CollabTools", "SpeechTools", "SERVERS", "ALL_TOOLS",
           "split_fragment", "ArtifactRef", "ApprovalKind", "ImportArtifact", "import_artifacts",
           "Decision", "ApprovalStatus", "APPROVAL_FINAL",
           "SpeakerPrompt", "speaker_prompts", "SpeakerIdentity", "SpeakerMap", "check_answer",
           "Continuation", "continuation_of",
           "WorkflowStatus", "WORKFLOW_FINISHED", "WORKFLOW_OPEN", "WorkflowRequest",
           "InputKind", "InputField", "ProcessSpec", "PROCESSES", "VISIO_TO_ARCHIMATE",
           "MEETING_TO_TRANSCRIPT", "TRANSCRIPT_TO_MINUTES"]
