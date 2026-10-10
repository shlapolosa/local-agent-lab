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

A FEATURE'S slice — its catalogue, processes and agents — may live in its own module of this package
(`contracts/speech.py` is the first), imported below and re-exported, so callers never see the seam;
`tests/unit/platform/test_contract_slices.py` holds the re-export and registry membership invariants.

Adding a tool = one constant on its catalogue (the parity test fails until it matches the server).
Adding a process = one `ProcessSpec` in `PROCESSES` (+ its consumer group in lab.platform.workflows.GROUPS).
"""
from __future__ import annotations

import json
import mimetypes
import re

from dataclasses import dataclass, field as dc_field
from enum import StrEnum
from typing import Any, Mapping

from lab.core.ids import POINTER_ID_FIELDS      # stdlib-only: this module must import without rdflib

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
    # The third family. `image` and `document` are what a HUMAN uploads; `artifact` (json/xml/svg/
    # xlsx — lab.platform.filetypes) is what the lab itself PRODUCES, and until this existed nothing
    # could read one back. A workload could write a transcript and then not open it: the minutes run
    # failed on exactly that, asking read_document for a .segments.json.
    read_artifact = "storage_read_artifact"
    read_vsdx = "storage_read_vsdx"
    render_vsdx = "storage_render_vsdx"      # the SAME page as a picture: the vision representation
    extract_figures = "storage_extract_figures"



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
    `<process>_status`, `<process>_result`, `<process>_runs`), so registering a process is the one
    place that changes.
    The same server also carries the APPROVAL tools (`ApprovalTools` below) — a run PAUSES for a human
    approval, so the pause is part of the lifecycle this front door exposes.

    A CONTINUATION-ONLY process (`ProcessSpec.external` false) contributes only status and result: it
    has no submit tool because there is no way to start it correctly except by approving the question
    that produced its input. The catalogue must say so, not merely the server — this is the PORT, it
    is what a team grant names and what `test_contracts_match_servers` checks in both directions, so a
    name here that no server exposes is exactly the drift that test exists to catch.
    """
    SERVER = "workflow_mcp"
    #: `fields` PUBLISHES the questionnaire: the labels, types, choices and required-ness a caller
    #: must fill in. Generated like the rest, and offered only by a process that HAS a
    #: questionnaire — an agent asked to "gather the intake fields" otherwise invents its own
    #: labels, and the mapping it sends matches nothing the corpus published, with nothing
    #: anywhere reporting the mismatch.
    VERBS = ("submit", "status", "result", "runs", "fields")
    replay = "workflow_replay"                         # run a FAILED request again, from its own inputs

    # ONE grant, and it is a write: a replay starts a run. It is safe to offer even for a process
    # that refuses external submits, because it takes NO INPUTS from the caller — only the id of a
    # request this lab already validated and recorded, so there is no new attribution to smuggle. It
    # is still a write, so it is granted deliberately and never reaches a workload's own agents.
    WRITE = (replay,)

    @classmethod
    def verbs_for(cls, spec: "ProcessSpec") -> tuple[str, ...]:
        """The tools this process actually gets. One place, read by the catalogue and by the server's
        registration, so the two cannot disagree about what exists."""
        verbs = cls.VERBS if spec.external else tuple(v for v in cls.VERBS if v != "submit")
        # A process with no questionnaire does not advertise one: a tool answering "this process
        # has no questions" is worse than no tool, because a grant can name it.
        return verbs if spec.questionnaire else tuple(v for v in verbs if v != "fields")

    @classmethod
    def names(cls) -> frozenset[str]:
        return (frozenset(spec.tool(v) for spec in PROCESSES.values() for v in cls.verbs_for(spec))
                | {cls.replay} | ApprovalTools.names())


class ApprovalTools(ToolCatalogue):
    """The human-in-the-loop GOVERNANCE surface — list / read / DECIDE an approval. Registered on
    workflow-mcp (same gateway alias, hence `SERVER` below, and NOT a separate entry in `SERVERS`):
    a run pauses for an approval and `<process>_status` already hands back the `approval_id`, so one
    server = one connector for a channel that must follow a run from submit to decision.

    SEVERAL GRANTS, not one — `GRANTS` below is the list, and every tool belongs to exactly one.
    `READ` is safe for anything that shows a human what is waiting; `decide` RECORDS A HUMAN'S
    DECISION to release an EA-repository write and must reach only a channel that carries a signed-in
    user (Teams/Copilot Studio, the review app) — never a workload's own agents. The gateway enforces
    the split per team with `mcp_tool_permissions` (per-tool ACL on the same `object_permission` as
    the server grant):

        read-only  {"object_permission": {"mcp_servers": ["workflow_mcp"],
                    "mcp_tool_permissions": {"workflow_mcp": list(ApprovalTools.READ)}}}
        + decide   … + list(ApprovalTools.WRITE)
    """
    SERVER = "workflow_mcp"
    list = "approvals_list"
    get = "approvals_get"
    ask = "approvals_ask"
    decide = "approvals_decide"
    withdraw = "approvals_withdraw"

    # THE SPLIT IS THE CONTROL. READ shows a human what is waiting. RAISE asks a
    # question — a workload's own step needs this, because a workload may not import the substrate
    # and so has no other way to reach the gate. WRITE answers, and must reach only a channel
    # carrying a signed-in person. A workload gets RAISE and never WRITE: asking must never imply
    # the ability to answer your own question.
    READ = (list, get)          # the GRANTS, as tuples so `names()`'s string filter ignores them
    RAISE = (ask,)              # a workload's step, over the gateway — it publishes, never decides
    WRITE = (decide,)           # the human-gated write — granted deliberately, never by default
    # A FOURTH grant, because withdrawing is not deciding and does not have `decide`'s blast radius.
    # `WRITE` releases a repository write; `RETIRE` closes a question so that nobody can answer it —
    # an operator's power over a stale gate, not a reviewer's over its subject. Kept apart so
    # "exactly one tool records a decision" stays literally true, and so a housekeeping caller need
    # not be handed the ability to approve. Never to a workload's own agents either: an agent that
    # can retire its own gate has silenced the control as surely as one that could answer it.
    RETIRE = (withdraw,)

    #: The grants, so a caller that must reason about ALL of them — a test asserting every tool
    #: belongs to exactly one, a provisioning script building a per-tool ACL — reads them from here
    #: rather than naming them one by one and silently missing the next one added.
    GRANTS = (READ, RAISE, WRITE, RETIRE)


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
    put = "collab_put"                       # art:// ref -> a file in a folder: the ONLY write of content
    watches = "collab_watches"
    watch = "collab_watch"
    watch_renew = "collab_watch_renew"
    unwatch = "collab_unwatch"

    READ = (capabilities, sites, drives, user_drive, list, item, meetings, recordings, transcripts,
            fetch, watches)
    # WRITE is not one thing. A SUBSCRIPTION is egress to a caller-supplied url and a durable object
    # outliving the run; PUT writes lab-authored content into someone else's tenant under the
    # provider's identity. Both are writes and both are granted deliberately, but they are different
    # powers with different blast radii, so they are named separately and a grant may hold one
    # without the other — the minutes workload needs `put` and must never have a subscription.
    SUBSCRIBE = (watch, watch_renew, unwatch)
    PUT = (put,)
    WRITE = SUBSCRIBE + PUT                  # tuples, so `names()`'s string filter ignores them


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
    # The Documentation Fabric's two gates (docs/fabric/FRS.md §5): confirming which delivery context an
    # artifact belongs to (a QUESTION with candidates, like speaker-mapping), and releasing a reviewed
    # artifact for publication. Nothing dispatches on either value.
    ASSOCIATION = "association"
    DRAFT_REVIEW = "draft-review"
    # A steward is asked about the VOCABULARY rather than about an artifact: admit this term as a concept,
    # say it already exists under another name, decline it, or settle a word that means two things. Widening
    # or narrowing what every future document is classified against is not a model's decision — but it is the
    # same gate, the same audit log and the same channels, and nothing dispatches on this value either.
    CONCEPT_ADMISSION = "concept-admission"
    # A NOTICE through the same gate (FR-5.3.2): a change reached published records that reference it, and their
    # owners are told — on every channel, with no new outbound path. Acknowledging is `approve`; nothing is released.
    IMPACT_NOTICE = "impact-notice"


class ApprovalAudience(StrEnum):
    """WHO an approval is for. Two audiences with different tempos, and until now one queue.

    An OWNER is asked about THEIR artifact — urgent and personal, "your document, now". A STEWARD is
    asked about the VOCABULARY — deliberate and periodic, "twenty terms when you have twenty
    minutes". Measured on this lab's own stream 10 Oct 2026: 101 open `concept-admission` cards
    against ~37 of everything else, so the vocabulary work buried the artifact work on every channel
    and an owner had to scroll past it to find their own card.

    This is TRIAGE, which is the one thing `kind` is documented to be for ("channels triage by it;
    nothing dispatches on it"): a channel decides which feed is its own. Nothing else reads it — no
    workflow, tool, review surface or applier branches on an audience, and the review app still sees
    the whole queue, because it is where every channel's card sends a person to decide.
    """

    OWNER = "owner"
    STEWARD = "steward"


# The kind -> audience split, declared ONCE so the steward channel and the owner channels cannot
# drift into both claiming a kind (announced twice) or neither claiming it (announced to nobody) —
# both of which fail silently.
#
# BOTH SIDES ARE WRITTEN OUT, and that is the whole value of the pair. `OWNER_KINDS =
# frozenset(ApprovalKind) - STEWARD_KINDS` was the first shape, and it makes the partition test
# TAUTOLOGICAL: a complement can never disagree with its own definition, so a new ApprovalKind would
# have become an owner's silently while a green test claimed it "cannot go unclassified". Declared,
# the partition in `tests/unit/platform/test_contracts_approval_audience.py` is a real ratchet — it
# fails on a member in neither set, which is the only reason to assert an invariant instead of a
# list. These two names ARE the declaration; the test is their only other reader by design.
STEWARD_KINDS = frozenset({ApprovalKind.CONCEPT_ADMISSION})
OWNER_KINDS = frozenset({ApprovalKind.EA_IMPORT, ApprovalKind.SPEAKER_MAPPING,
                         ApprovalKind.ASSOCIATION, ApprovalKind.DRAFT_REVIEW,
                         ApprovalKind.IMPACT_NOTICE})


def approval_audience(kind: str | None) -> ApprovalAudience:
    """The audience of one approval, from the kind the request stream carries.

    An UNKNOWN kind — the legacy `adoit-import` staged before the vendor-neutral rename, or anything
    a future producer invents — resolves to OWNER, never to nothing: those are the channels that
    always existed, so an unclassified question is announced exactly where it would have been
    announced before. The same rule the rename itself relied on; a question reaching nobody is the
    one outcome this gate must not have. It is `STEWARD_KINDS` that is consulted, not `OWNER_KINDS`,
    precisely so an unknown WIRE string falls to OWNER while an unclassified ENUM MEMBER is still
    caught by the partition test rather than quietly defaulting."""
    return ApprovalAudience.STEWARD if kind in STEWARD_KINDS else ApprovalAudience.OWNER


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
    # ONE download per ref: two keys naming the same file (a design whose `architecture_ref` fell
    # back to its `model_ref`) would render two identical buttons, which the review app refuses.
    seen: set[str] = set()
    out = []
    for k, v in payload.items():
        if k.endswith("_ref") and isinstance(v, str) and v.strip() and v not in seen:
            seen.add(v)
            out.append(ImportArtifact(ref=v, label=ImportArtifact(v, "?").filename))
    return out


class Decision(StrEnum):
    """What a human may answer; `update` = changes requested, the request stays open."""
    APPROVE = "approve"
    DECLINE = "decline"
    UPDATE = "update"


class ApprovalStatus(StrEnum):
    """A request's status: pending until it ENDS, then how it ended.

    Three of the four are a human's decision. `WITHDRAWN` is the one that is not: a question retired
    because nobody is going to answer it — a superseded test run, a pipeline replaced by a newer one.
    It exists because the alternative was recording a `decline`, which puts a person's name against a
    judgement they never made, and "who decided this" is the entire point of the audit log.
    """
    PENDING = "pending"
    APPROVE = "approve"
    DECLINE = "decline"
    UPDATE = "update"
    WITHDRAWN = "withdrawn"


#: A request that is CLOSED — awaiting nobody. Not the same as "a human decided": `WITHDRAWN` is in
#: here and is deliberately absent from `Decision`. Every reader of this set means closed (a channel
#: deciding what to announce, `human_decision` refusing a second answer, `await_decision` returning,
#: a tool reporting `open`), so one membership answers all of them. `update` = changes requested,
#: which leaves the request OPEN for a later answer and so is not in here.
APPROVAL_FINAL = frozenset({ApprovalStatus.APPROVE, ApprovalStatus.DECLINE, ApprovalStatus.WITHDRAWN})


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
    # Who this voice SOUNDS LIKE, from the voiceprint gallery — in the answer's own shape
    # ({"identity"|"tag": ..., "display": ..., "score": ...}) so a surface can prefill it. Empty means
    # "not recognised", and the question is asked exactly as it was before voiceprints existed.
    suggestion: dict[str, Any] = dc_field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (self.label or "").strip():
            raise ValueError("a speaker prompt needs its label — the answer is keyed on it")

    def to_dict(self) -> dict[str, Any]:
        out = {"label": self.label, "samples": list(self.samples), "seconds": self.seconds,
               "turns": self.turns}
        if self.suggestion:
            out["suggestion"] = dict(self.suggestion)
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SpeakerPrompt":
        return cls(label=str(d.get("label") or ""), samples=tuple(d.get("samples") or ()),
                   seconds=float(d.get("seconds") or 0.0), turns=int(d.get("turns") or 0),
                   suggestion=dict(d.get("suggestion") or {}))


def speaker_prompts(payload: dict[str, Any]) -> list[SpeakerPrompt]:
    """The speakers one approval asks about, in the order the payload declared them.

    The ONE reader, shared by the review app, the chat cards and the approval tools, so three
    surfaces cannot drift into three slightly different renderings of the same question. A payload
    that asks nothing yields nothing rather than raising: most approvals are not questions.
    """
    items = ((payload or {}).get("question") or {}).get("items") or []
    return [SpeakerPrompt.from_dict(i) for i in items if isinstance(i, dict)]


@dataclass(frozen=True)
class SpeakerCandidate:
    """ONE person the answerer can PICK instead of typing — who the provider says attended.

    Same producer-supplies-meaning shape as `SpeakerPrompt`: the step that resolved the meeting puts
    the candidates on the question, and every surface renders them as a choice. It exists because the
    answer needs a directory identity and a typed one fails LATE — a mistyped address survives the
    gate and only breaks during attribution, by which time the human is gone.

    A SUGGESTION, never a constraint. Attendance is not speech (one device in a room is one
    participant, and someone can attend and say nothing), so free text must stay available beside
    these; a surface that offered only this list would make the common case easy and the honest case
    impossible. An empty list is normal and means "we could not tell" — the question still works.
    """

    identity: str                       # the directory principal, exactly as the answer will carry it
    display: str = ""                   # what a person recognises; falls back to the identity

    def __post_init__(self) -> None:
        if not (self.identity or "").strip():
            raise ValueError("a speaker candidate needs the identity the answer will carry")

    @property
    def label(self) -> str:
        """What a picker shows. The identity is always visible, because two people share a display
        name far more often than they share an address, and the answer records the address."""
        d = (self.display or "").strip()
        return f"{d} <{self.identity}>" if d and d != self.identity else self.identity

    def to_dict(self) -> dict[str, Any]:
        return {"identity": self.identity, "display": self.display}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SpeakerCandidate":
        return cls(identity=str(d.get("identity") or "").strip(),
                   display=str(d.get("display") or "").strip())


def speaker_candidates(payload: dict[str, Any]) -> list[SpeakerCandidate]:
    """Who this question offers as choices, de-duplicated by identity and in declared order.

    The ONE reader, for the same reason as `speaker_prompts`. Malformed entries are skipped rather
    than raising: a candidate list is a convenience, and losing the whole question because one
    attendee record was odd would be a poor trade.
    """
    raw = ((payload or {}).get("question") or {}).get("candidates") or []
    out, seen = [], set()
    for c in raw:
        if not isinstance(c, dict):
            continue
        try:
            cand = SpeakerCandidate.from_dict(c)
        except ValueError:
            continue
        if cand.identity.lower() not in seen:
            seen.add(cand.identity.lower())
            out.append(cand)
    return out


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
    # A key present but EMPTY is not an answer. Checked here rather than left to the typed object,
    # because the point of a completeness gate is that unanswered work cannot proceed, and a blank
    # slipped through it: a card rendered with no input controls submitted {"X": {"tag": ""}}, the
    # gate accepted it, and the run it released carried a mapping that identified nobody. Still
    # GENERIC — "something was actually given" needs no idea of what was being asked.
    blank = sorted(l for l in wanted if not _answered(answer.get(l)))
    if blank:
        raise ValueError(f"the answer is blank for {blank} — a key with nothing in it is not an "
                         "answer, and approving on one would release work that identifies nobody")
    return answer


def _answered(value: Any) -> bool:
    """Is there anything in this value? A non-blank scalar, or a container holding one — nesting is
    the surface's business, so this only asks whether SOMETHING was given."""
    if value is None or isinstance(value, bool):
        return value is not None and value is not False or value is True
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_answered(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_answered(v) for v in value)
    return True                                   # a number or another scalar IS a value


SPEAKER_FIELDS = ("identity", "tag")


def answer_fields(payload: dict[str, Any]) -> tuple[str, ...]:
    """The fields an answer carries per label, as the ASKER declared them on `question.fields`.

    A surface renders what the payload declares, never what it infers: a speaker line-up is answered
    as identity-or-tag and a class to confirm as one `value`, and the two are told apart here rather
    than by whether the items happen to carry timings — which a diarizer may simply not report. An
    approval staged before the declaration existed is a speaker question, the only kind there was.
    """
    fields = ((payload or {}).get("question") or {}).get("fields") or ()
    return tuple(str(f) for f in fields) or SPEAKER_FIELDS


def answer_value(entry: Any) -> str:
    """The ONE value a MAPPING entry carries, for a question with one thing to say per label.

    A MAPPING answer is `{label: {field: value}}`. The inner object exists so a speaker can be an
    identity OR a tag; a question with a single answer per label — the criticality class — travels
    in the same shape so every surface and the completeness gate stay generic, and its consumer
    reads the one value through here without caring what the surface called the field. Two fields
    is not one answer, and a blank is not one either: both refuse, because the class this reads
    decides the rigour of everything downstream and a guess in either direction drops controls.
    """
    if not isinstance(entry, dict) or len(entry) != 1:
        given = sorted(entry) if isinstance(entry, dict) else type(entry).__name__
        raise ValueError(f"an answer carries exactly one value per label, got {given}")
    (field, value), = entry.items()
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"the one value for {field!r} must be a non-empty string")
    return value.strip()


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

    @property
    def starts(self) -> str:
        """The one word for what approving starts — the process name's last segment, which the
        registry's naming convention makes a noun (design, minutes, provisioning). Declared here so
        every surface's button reads the same word instead of each guessing."""
        return self.process.rsplit("_", 1)[-1]

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
    # Whatever the process's own ProcessSpec declares, and NOTHING process-shaped on this type: a
    # consumer reads `inputs["diagram"]` by name. Convenience properties for one process's fields
    # used to live here and were the exact coupling the later consumers were written to avoid.
    inputs: dict[str, Any]
    requester: str
    created_at: str
    created_ts: str
    status: WorkflowStatus = WorkflowStatus.PENDING

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
    credentials, so CONTENT is always passed by reference. The other four exist so a low-code
    trigger can start a run in ONE call — carrying who owns a recording, a reference to it at the
    provider, a human's answer, and where the result is announced — none of which is content and
    none of which is an `art://` ref.

    CONVERSATION is the newest and the narrowest: a provider's opaque id for a conversation (a Teams
    meeting chat's thread id, say). It exists because a meeting's outputs belong back in the
    meeting's own chat, and only the run that RESOLVED the meeting knows which chat that is — the run
    that writes the minutes is a continuation and never sees the meeting itself. It is an id and is
    validated as one (no whitespace, no URL, bounded): it names a destination, it grants nothing, and
    it is not somewhere prose can hide.

    CHOICE carries a decision, not data: which of several LANES a run belongs to, chosen from a set
    the lab itself declares. It is the answer to "a run must say which provider it used" that does
    NOT reopen free text — a value is a member of the list or the run is refused before it starts.

    Deliberately absent: a general "text" kind. It would admit a URL, a whole document or an injected
    prompt into a contract whose entire discipline is by-reference. When a process genuinely needs
    free text, that is the moment to argue for it.
    """
    REF = "ref"            # exactly one reference to content in the lab's own store
    REF_LIST = "ref_list"  # zero or more of those
    HANDLE = "handle"      # ONE opaque provider handle (ids only — never a URL, never a credential)
    IDENTITY = "identity"  # ONE directory principal: who a question is asked of, or who owns a thing
    MAPPING = "mapping"    # a SMALL flat object of label -> {field: value}, from a human's answer
    CONVERSATION = "conversation"   # ONE opaque provider conversation id: where a result is announced
    CHOICE = "choice"      # ONE value from a CLOSED set declared on the field
    NUMBER = "number"      # ONE number — a figure a formula reads, never prose for it to parse
    # A repeating table of TYPED rows, columns declared on the field. `MAPPING` holds one value per
    # label, and 37 % of real submissions list two or three effort roles — so a third of them could
    # not be expressed, driver 1 was understated or left open, and a driver left open means
    # `recommend()` can never return `proceed`: every case in the portfolio read the same verdict.
    TABLE = "table"
    APPROVAL = "approval"  # ONE approval id (`apr-<12 hex>`): the decision a continuation was released by
    # The Documentation Fabric's three (docs/fabric/FRS.md §4.4, §4.6): a POINTER is a bounded structured
    # reference INTO a system of record (never content, never a URL); an EVENT is the ULID of the
    # ArtifactChanged that started a run; a CONTEXT is the delivery container an artifact was produced
    # under, as `<kind>:<id>` from a closed set of kinds (note 001: the work item is one kind of several).
    POINTER = "pointer"
    EVENT = "event"
    CONTEXT = "context"
    ARTIFACT = "artifact"  # ONE fabric artifact IRI, urn:fabric:artifact:<ULID> — the catalog's own identity
    # The one FREE TEXT a run may carry, argued for on 6 Oct 2026: what people CALL a thing. An opted-in
    # meeting is otherwise known only by ids, so its minutes could not be found by the meeting's name. It
    # is a label and held to what a label is — one line, short, never a link — so it cannot become a
    # place to carry a document or an instruction. It never goes on a span (it may name people).
    TITLE = "title"


# A mapping is a human's answer, not a payload. Bounded so it can never become a way to smuggle
# arbitrary state through an input contract that is otherwise strictly by-reference.
MAX_MAPPING_ENTRIES = 64
MAX_MAPPING_BYTES = 8192
# A conversation id is an id. Teams' own is ~60 characters; the ceiling is generous for a provider
# that mints longer ones and still far too small to be a paragraph.
MAX_CONVERSATION_CHARS = 512
# A title is what a calendar shows on one line. Teams allows 255; the long tail is a pasted agenda.
MAX_TITLE_CHARS = 120


def check_title(value: Any, field: str = "title") -> str:
    """ONE line a person gave a thing as its name, whitespace collapsed. A link, a control character
    or more than `MAX_TITLE_CHARS` is refused: each is a sign the field is carrying something else."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text, got {type(value).__name__}")
    text = " ".join(value.split())
    if not text or "://" in text or any(not c.isprintable() for c in text):
        raise ValueError(f"{field} must be one line of printable text with no link, got {value!r}")
    if len(text) > MAX_TITLE_CHARS:
        raise ValueError(f"{field} is {len(text)} characters, longer than the {MAX_TITLE_CHARS} a title may be")
    return text


def fit_title(value: Any) -> str:
    """A title the contract will accept, from one it might not — clipped to length, or "" when it
    cannot be fixed (a link in it). For a caller that holds a name it did not choose: a meeting's
    long subject should cost the run its tidy name, never the run."""
    text = " ".join(value.split()) if isinstance(value, str) else ""
    if len(text) > MAX_TITLE_CHARS:
        text = text[:MAX_TITLE_CHARS - 1].rstrip() + "…"
    try:
        return check_title(text)
    except ValueError:
        return ""


# A pointer names ONE item in ONE system of record. Bounded like a mapping, for the same reason.
# Sources are the lab's PORTS, never vendors: "collab" (files and meetings behind collab_mcp), "work"
# (work items behind the delivery-context port), "ea" (the EA repository behind ea_mcp), "lab" (an
# artifact a lab run wrote to its own store). A pointer into collab IS the content handle.
POINTER_SOURCES = ("collab", "work", "ea", "lab")
# POINTER_ID_FIELDS lives with the catalog row that keys on it (lab.core.semantic.fabric.catalog); one home.
MAX_POINTER_BYTES = 1024
# A delivery context is `<kind>:<id>`; the kinds are the delivery containers the lab knows.
CONTEXT_KINDS = ("usecase", "meeting", "submission", "workitem")
MAX_CONTEXT_CHARS = 256
ARTIFACT_CHANGES = ("created", "updated", "deleted", "moved", "relabelled")


def check_pointer(value: Any, field: str = "pointer") -> dict[str, str]:
    """A bounded, structured reference into a system of record — never content, never a URL.

    Shared by the input contract and by `ArtifactChanged`, so an event and a run refuse the same
    shapes. A JSON string is accepted because the stream carries fields as strings."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as e:
            raise ValueError(f"{field} must be a pointer object, got a string that is not JSON") from e
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{field} must be a pointer object {{source, <id fields>}}, got {type(value).__name__}")
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_POINTER_BYTES:
        raise ValueError(f"{field} is larger than the {MAX_POINTER_BYTES} bytes a pointer may be")
    source = value.get("source")
    if source not in POINTER_SOURCES:
        raise ValueError(f"{field}.source must be one of {list(POINTER_SOURCES)}, not {source!r}")
    if not any(value.get(k) for k in POINTER_ID_FIELDS):
        raise ValueError(f"{field} names no item: one of {list(POINTER_ID_FIELDS)} is required")
    out: dict[str, str] = {}
    for k, v in value.items():
        if not isinstance(k, str) or not isinstance(v, (str, int)) or isinstance(v, bool):
            raise ValueError(f"{field}.{k} must be a string or integer")
        text = str(v).strip()
        if "://" in text and k not in ("ref", "handle"):
            raise ValueError(f"{field}.{k} looks like a URL — a pointer carries ids, never locations")
        if k == "ref" and not ArtifactRef.is_ref(text):
            raise ValueError(f"{field}.ref must be an art:// reference")
        if k == "handle":
            from lab.core.collab.model import ContentHandle      # platform may import core
            text = str(ContentHandle.parse(text))                 # ids only, never a URL
        out[k] = text
    return out


_APPROVAL_ID = re.compile(r"^apr-[0-9a-f]{12}$")


def check_approval_id(value: Any, field: str = "approval_id") -> str:
    """An approval id as `lab.substrate.approvals.request` mints them — an opaque id, never a URL."""
    text = value.strip() if isinstance(value, str) else ""
    if not _APPROVAL_ID.match(text):
        raise ValueError(f"{field} must be an approval id (apr-<12 hex>), got {value!r}")
    return text


def check_event_id(value: Any, field: str = "event_id") -> str:
    from lab.core import ids                       # platform may import core

    text = value.strip() if isinstance(value, str) else ""
    if not ids.is_ulid(text):
        raise ValueError(f"{field} must be a ULID (26 Crockford base32 characters), got {value!r}")
    return text


def check_context(value: Any, field: str = "context") -> str:
    """`<kind>:<id>` — the delivery container an artifact was produced under. An id, checked like a
    conversation id: no whitespace, no URL, bounded; the kind from the closed set."""
    text = value.strip() if isinstance(value, str) else ""
    kind, sep, ident = text.partition(":")
    if not sep or kind not in CONTEXT_KINDS or not ident:
        raise ValueError(f"{field} must be <kind>:<id> with kind in {list(CONTEXT_KINDS)}, got {value!r}")
    if any(c.isspace() for c in ident) or "://" in ident:
        raise ValueError(f"{field} must be an opaque id, got {value!r}")
    if len(text) > MAX_CONTEXT_CHARS:
        raise ValueError(f"{field} is longer than the {MAX_CONTEXT_CHARS} characters an id may be")
    return text


ARTIFACT_IRI_PREFIX = "urn:fabric:artifact:"


def check_artifact_iri(value: Any, field: str = "artifact_iri") -> str:
    """The catalog's identity for an artifact — opaque, minted by the fabric, never a path or a URL."""
    from lab.core import ids

    text = value.strip() if isinstance(value, str) else ""
    if not text.startswith(ARTIFACT_IRI_PREFIX) or not ids.is_ulid(text[len(ARTIFACT_IRI_PREFIX):]):
        raise ValueError(f"{field} must be {ARTIFACT_IRI_PREFIX}<ULID>, got {value!r}")
    return text


#: How many rows a TABLE may carry. Bounded for the reason MAPPING is bounded: an input that can
#: grow without limit is a way to smuggle arbitrary state through a governed door. Twelve is well
#: past the widest real answer measured (three effort roles).
MAX_TABLE_ROWS = 12


@dataclass(frozen=True)
class Column:
    """One column of a TABLE input — its name, its kind, and whether a row may omit it.

    The kinds are the scalar ones (`NUMBER`, `CHOICE`, `IDENTITY`, …): a column is a value a
    formula or a domain object reads, so nesting a table inside a table would be a shape no
    consumer here has.
    """
    name: str
    kind: "InputKind"
    required: bool = False
    choices: tuple[str, ...] = ()
    description: str = ""

    def field(self, table: str) -> "InputField":
        """This column as a one-value field, so a cell is coerced by exactly the rules a top-level
        input of that kind is — rather than by a second implementation that can disagree."""
        return InputField(f"{table}.{self.name}", self.kind, self.description,
                          required=self.required, choices=self.choices)


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
    #: The corpus ARTIFACT that publishes this field's questions — their labels, types, choices and
    #: which are required. Empty means the field carries no questionnaire.
    #:
    #: The artifact id rather than a flag, and declared HERE rather than in each surface, because
    #: the questions must be discoverable and the discovery must be derived: `<process>_fields`
    #: serves them to an agent, the review app renders them as a form, the CSV template is the same
    #: list, and adding or removing a question is a corpus publish that changes all three at once.
    #: NOT inferred from `MAPPING`: a mapping can equally be an answer a human already gave — a
    #: speaker map is not a set of questions, and offering to "read its questions" would invite
    #: somebody to fill in another person's attribution.
    questions: str = ""
    choices: tuple[str, ...] = ()          # CHOICE only: the closed set of accepted values
    columns: tuple[Column, ...] = ()       # TABLE only: the typed columns one row may carry

    def __post_init__(self) -> None:
        # A CHOICE with no members would accept nothing (and read as an oversight); a CHOICE that
        # skipped this check would accept anything, which is the free-text field this kind exists
        # to avoid. Either way the failure belongs at construction, not at the first submit.
        if (self.kind is InputKind.CHOICE) != bool(self.choices):
            raise ValueError(f"{self.name}: CHOICE declares its choices, and nothing else takes them")
        if (self.kind is InputKind.TABLE) != bool(self.columns):
            raise ValueError(f"{self.name}: a TABLE declares its columns, and nothing else takes "
                             f"them — a table whose shape nobody stated is a free-text blob")

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
        if self.kind is InputKind.CONVERSATION:
            return self._conversation(value)
        if self.kind is InputKind.TITLE:
            return check_title(value, self.name)
        if self.kind is InputKind.CHOICE:
            return self._choice(value)
        if self.kind is InputKind.NUMBER:
            return self._number(value)
        if self.kind is InputKind.TABLE:
            return self._table(value)
        if self.kind is InputKind.POINTER:
            return check_pointer(value, self.name)
        if self.kind is InputKind.EVENT:
            return check_event_id(value, self.name)
        if self.kind is InputKind.APPROVAL:
            return check_approval_id(value, self.name)
        if self.kind is InputKind.CONTEXT:
            return check_context(value, self.name)
        if self.kind is InputKind.ARTIFACT:
            return check_artifact_iri(value, self.name)
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

    def _conversation(self, value: Any) -> str:
        """One opaque provider conversation id — where this run's result is announced.

        Checked the way `_identity` checks a principal, and for the same reason: this is a
        DESTINATION, so it has to resolve at the provider. A URL is refused (somewhere the lab was
        told to post is not the same thing as a conversation the provider knows), whitespace is
        refused (an id has none), and the length is bounded so a field meant to hold
        `19:meeting_...@thread.v2` cannot become a place to carry prose.
        """
        text = value.strip() if isinstance(value, str) else ""
        if not text or any(c.isspace() for c in text) or "://" in text:
            raise ValueError(f"{self.name} must be an opaque conversation id, got {value!r}")
        if len(text) > MAX_CONVERSATION_CHARS:
            raise ValueError(f"{self.name} is {len(text)} characters, longer than the "
                             f"{MAX_CONVERSATION_CHARS} an id may be")
        return text

    def _number(self, value: Any) -> float:
        """ONE number. A figure a formula reads, so it arrives as a number rather than as prose for
        the formula to parse — the scraping that replaces this reads a latency SLA as a volume."""
        if isinstance(value, bool):        # bool is an int in Python, and "yes" is not a figure
            raise ValueError(f"{self.name}: {value!r} is a yes/no, not a number")
        try:
            return float(str(value).strip().replace(",", ""))
        except (TypeError, ValueError):
            raise ValueError(f"{self.name}: {value!r} is not a number") from None

    def _table(self, value: Any) -> list[dict]:
        """A repeating table of typed rows, each coerced by its column's own kind.

        A column nobody declared is REFUSED rather than carried: an undeclared column is a value
        somebody believes was captured and nothing reads. A required column missing is refused by
        name, for the same reason — `requires_input` and a wrong number are the distinction the
        whole valuation rests on.
        """
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{self.name}: a table is a list of rows, got {type(value).__name__}")
        if len(value) > MAX_TABLE_ROWS:
            raise ValueError(f"{self.name}: {len(value)} rows; at most {MAX_TABLE_ROWS} — an input "
                             f"that can grow without limit is a way to smuggle arbitrary state")
        known = {c.name: c for c in self.columns}
        out = []
        for n, row in enumerate(value, start=1):
            if not isinstance(row, Mapping):
                raise ValueError(f"{self.name} row {n}: a row is an object, "
                                 f"got {type(row).__name__}")
            extra = sorted(set(row) - set(known))
            if extra:
                raise ValueError(f"{self.name} row {n}: {extra} are not columns of this table — "
                                 f"have {sorted(known)}")
            got: dict = {}
            for name, column in known.items():
                coerced = column.field(self.name).coerce(row.get(name))
                if coerced is not None:
                    got[name] = coerced
            out.append(got)
        return out

    def _choice(self, value: Any) -> str:
        """One member of the closed set, normalised. The refusal NAMES the members, because a closed
        set nobody can see is just a rejection with no remedy."""
        if not isinstance(value, str) or isinstance(value, bool):
            raise ValueError(f"{self.name} is one of {list(self.choices)}, not a "
                             f"{type(value).__name__}")
        got = value.strip().lower()
        if got not in self.choices:
            raise ValueError(f"{self.name} must be one of {list(self.choices)}, not {value!r}")
        return got

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
    # Which of those outputs are MANAGED ARTIFACTS — the products the fabric ingests (BRS principle 8: a
    # transcript, a recording, a person's submission record are working files that stay where they are as
    # pointers; what gets owned, reviewed and published is what was MADE from them). A process with no
    # products is never a producer. Measured 12 Sep 2026: ingesting every `*_ref` a run left behind turned 35
    # recordings and per-lane segment files into review cards nobody should decide.
    products: tuple[str, ...] = ()
    # Which INPUT names the SUBJECT a run worked on, in preference order (the recording a meeting's minutes came
    # from; the submission a screening judged). A product's identity is process + subject + output, so a re-run
    # over the same subject is a new version of one record. A run with no such input keeps its ref as identity.
    identity: tuple[str, ...] = ()
    # May an OUTSIDE caller START this process? Some processes are a CONTINUATION of another — they
    # exist to run after a human answered a question, and starting one directly would skip the gate
    # that gave it its input. That is a property of the PROCESS, not a permission on a caller, so it
    # is declared here and refused on every external surface at once. Note the asymmetry: submit is
    # refused, status/result are not — a caller may always observe a run it caused indirectly.
    external: bool = True
    # Groups of inputs of which EXACTLY ONE must be supplied — alternatives, not options. No single
    # field can say this: each member is individually optional, so `required` cannot express it and
    # the rule used to live inside the workload's first executor. That meant an invalid submission
    # passed `validate`, queued, got a request_id and a TRACE, started a run and died at step 1 —
    # measured 18 Sep 2026, where a person received a trace id instead of a form error. Declared
    # here, it is refused by EVERY surface at once (MCP tool, REST front door, the review app), for
    # the same reason `external` is: a rule about the process belongs to the process.
    @property
    def questionnaire(self) -> str | None:
        """The input that carries a QUESTIONNAIRE — a set of published questions a caller answers.

        Declared on the field, not inferred from its KIND: `transcript_to_minutes` takes a
        `speaker_map` mapping that is an ANSWER a human already gave, not a set of questions to
        ask — and offering to "read its questions" would be an invitation to fill in somebody's
        attribution. One flag, read here, so renaming the field is one edit and a new process that
        declares one gets its `fields` tool for free.
        """
        for field in self.inputs:
            if field.questions:
                return field.name
        return None

    #: Fields that are ALTERNATIVES: at most one of them. Two documents describing one submission
    #: is an ambiguity nobody can resolve, so it is refused — but supplying NEITHER is a separate
    #: question, and conflating the two is what made a conversational intake unsubmittable.
    one_of: tuple[tuple[str, ...], ...] = ()

    #: Fields of which at least one must arrive — what the process cannot proceed without, stated
    #: as the SET that satisfies it rather than as a single required field. A completed
    #: questionnaire and an uploaded document are both a submission; demanding the document meant
    #: an agent could walk a user through every question and then not be allowed to submit them.
    at_least_one: tuple[tuple[str, ...], ...] = ()

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
        # Checked AFTER coercion, so a field present but empty counts as absent — the same reading
        # every other rule here takes, and the one a person filling a form expects.
        for group in self.one_of:
            given = [n for n in group if out.get(n)]
            if len(given) > 1:
                raise ValueError(
                    f"{self.name}: supply at most one of "
                    + " or ".join(f"`{n}`" for n in group)
                    + "; got both")
        for group in self.at_least_one:
            if not any(out.get(n) for n in group):
                raise ValueError(
                    f"{self.name}: supply at least one of "
                    + " or ".join(f"`{n}`" for n in group) + "; got none")
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
    products=('xml_ref',),
    identity=("diagram",),
)

# ----------------------------------------------------------------------------- the agents themselves
# The third leg of the identity claim. A virtual key says what an agent may SPEND and reach; an Entra
# app registration says who it IS to the tenant; and an A2A card is what makes either discoverable to
# anyone who did not write the code. The first two have existed for months and the third never did —
# `GET /v1/agents` returned an empty list, so the registry pane showed nothing and "one key to one
# registration to one card" was a claim the deployment could not support.
#
# Declared here, beside PROCESSES, for the reason PROCESSES is here: both tiers read it, and a
# registry that lives in a provisioning script is a registry no test can check.


@dataclass(frozen=True)
class AgentSpec:
    """One agent, declared ONCE: who it is, which identity it authenticates as, and what it does.

    `prefix` is the environment prefix `lab.workloads.identity.agent_headers` already uses — the same
    stem behind `<PREFIX>_CLIENT_ID` / `_CLIENT_SECRET` / `_KEY`. Naming it here rather than inventing
    a second identifier is what lets a test assert that every agent this lab RUNS is an agent it also
    PUBLISHES, and vice versa.

    `processes` is PLURAL because the mapping already is: `usecase-agent` serves screening and design,
    `usecase-delivery-agent` serves investment and provisioning. A singular field would have been
    wrong on the day it was written.

    `model` is "" for a tool-only identity. `meeting-agent` authenticates the transcription workload's
    tool calls and holds no model at all — every step of that process is deterministic — and a card
    must be able to say so rather than invent one.
    """

    name: str                            # the card name AND the agent_name a registry reconciles on
    prefix: str                          # the env prefix `agent_headers` reads
    description: str                     # DECLARED, never scraped: these cards are published publicly
    skills: tuple[str, ...]
    model: str = ""                      # "" = a tool-only identity, deliberately
    processes: tuple[str, ...] = ()      # the ProcessSpec names it serves; may be several

    def card(self, gateway_url: str, tenant_id: str = "", audience: str = "",
             *, client_id: str = "") -> dict:
        """This agent as an A2A AgentCard.

        PURE — no tenant is contacted and no credential is read; everything arrives as an argument, so
        the card a test renders is the card CI publishes.

        The `url` is the gateway's MCP front door and NOT `/a2a/<id>/message/send`. Nothing is
        listening there: this lab's agents are in-process workflow nodes and the workflow mediates
        between them deliberately, so advertising a callable endpoint would advertise a failure. The
        shared front door is also what keeps the card honest for an agent serving several processes —
        one address, the same whichever one it is acting in.

        The Entra registration travels as `securitySchemes`, A2A's own field, in the OAuth2
        client-credentials shape `agent_headers` actually authenticates with — which is also what
        APIM's `validate-jwt` checks, so this block migrates unchanged. Only the client ID, which is
        an identifier; the client SECRET and the virtual key are credentials and appear nowhere on a
        card. Omitted entirely when no registration exists, because ten of these identities are
        provisioned only when an operator runs the script against a live tenant, and discovery must
        degrade the way `identity.credential_for` already does rather than refuse.
        """
        card: dict[str, Any] = {
            "protocolVersion": A2A_PROTOCOL_VERSION,
            "name": self.name,
            "description": self.description,
            "url": gateway_url.rstrip("/") + "/mcp",
            "version": AGENT_CARD_VERSION,
            "provider": {"organization": AGENT_ORGANISATION, "url": gateway_url.rstrip("/")},
            "capabilities": {"streaming": False, "pushNotifications": False,
                             "stateTransitionHistory": False},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [{"id": s, "name": s.replace("_", " "),
                        "description": self.description,
                        "tags": list(self.processes)} for s in self.skills],
        }
        if client_id and tenant_id and audience:
            scope = f"{audience}/.default"
            card["securitySchemes"] = {"entra": {
                "type": "oauth2",
                "description": f"Entra client credentials for {self.name} ({client_id}).",
                "flows": {"clientCredentials": {
                    "tokenUrl": f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
                    "scopes": {scope: "Call the governed gateway as this agent."}}}}}
            card["security"] = [{"entra": [scope]}]
        return card


#: The A2A spec version these cards declare, and the lab's own version for them. Both are stated
#: rather than derived: a card is a published artifact, and a reader needs to know which spec it obeys.
A2A_PROTOCOL_VERSION = "0.3.0"
# FEATURE SLICES. Each declares PROCESSES / AGENTS / CATALOGUES and the registries below splice them in,
# so a slice grows without touching this file. Imported HERE, not at the top: a slice builds on
# ToolCatalogue, ProcessSpec, InputField and AgentSpec, all defined above.
# The named imports are RE-EXPORTS for callers that predate the split; a NEW public name is imported
# from its slice (`from lab.platform.contracts.speech import X`), never added here.
from lab.platform.contracts import reference as _reference, speech as _speech, usecase as _usecase  # noqa: E402
from lab.platform.contracts.reference import ReferenceTools, VectorStores  # noqa: E402
from lab.platform.contracts.speech import (  # noqa: E402
    MEETING_TO_TRANSCRIPT, SPEECH_PROVIDERS, TRANSCRIPT_TO_MINUTES, SpeechTools,
)
from lab.platform.contracts.usecase import (  # noqa: E402
    USE_CASE_DESIGN, USE_CASE_INVESTMENT, USE_CASE_PROVISIONING, USE_CASE_SCREENING, DecisionTools,
    ValuationTools,
)

#: Every process whose PRODUCTS the fabric ingests — derived from the specs' `products`, so declaring what a
#: process makes is the one place that also makes it a producer (a governance test names the non-producers).
PRODUCING_PROCESSES: tuple[str, ...] = tuple(p.name for p in (VISIO_TO_ARCHIMATE, *_speech.PROCESSES,
                                                              *_usecase.PROCESSES) if p.products)

# The FABRIC slice comes last: its intake process offers PRODUCING_PROCESSES (above) as its choices.
from lab.platform.contracts import fabric as _fabric  # noqa: E402
from lab.platform.contracts.fabric import (  # noqa: E402
    ARTIFACT_INTAKE, ARTIFACT_PUBLISH, ArtifactChanged, SemanticTools,
)

AGENT_CARD_VERSION = "1.0.0"
AGENT_ORGANISATION = "local-agent-lab"


#: Every agent the lab runs. Adding one is a line here and a line in its provisioning script — kept
#: honest in both directions by tests/governance/test_agent_registry_parity.py.
AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec(name="ea-modeling-agent", prefix="EA_AGENT",
              description="Models enterprise architecture and stages it for a human to import.",
              skills=("archimate_modelling",), model="gpt-oss-120b"),
    AgentSpec(name="ba-agent", prefix="BA_AGENT",
              description="Reads a diagram and its requirements into a described system.",
              skills=("diagram_reading",), model="kimi-k3",
              processes=("visio_to_archimate",)),
    AgentSpec(name="architect-agent", prefix="ARCHITECT_AGENT",
              description="Turns a described system into a legal ArchiMate model.",
              skills=("archimate_modelling",), model="kimi-k3",
              processes=("visio_to_archimate",)),
    *_speech.AGENTS,
    *_usecase.AGENTS,

    *_fabric.AGENTS,
)


PROCESSES: dict[str, ProcessSpec] = {p.name: p for p in (VISIO_TO_ARCHIMATE, *_speech.PROCESSES,
                                                         *_usecase.PROCESSES,
                                                         *_fabric.PROCESSES)}


# ----------------------------------------------------------------------------- the registry of servers
# Last, because WorkflowTools' tool names are derived from PROCESSES above.
SERVERS: dict[str, type[ToolCatalogue]] = {c.SERVER: c for c in (StorageTools, *_fabric.CATALOGUES, EATools,
                                                                 WorkflowTools, CollabTools,
                                                                 *_speech.CATALOGUES, *_reference.CATALOGUES,
                                                                 *_usecase.CATALOGUES)}
ALL_TOOLS: frozenset[str] = frozenset(n for c in SERVERS.values() for n in c.names())


__all__ = ["gateway_name", "ToolCatalogue", "StorageTools", "SemanticTools", "EATools", "WorkflowTools",
           "ApprovalTools", "ApiRoles", "CollabTools", "SpeechTools", "ReferenceTools", "DecisionTools", "ValuationTools",
           "VectorStores", "SERVERS", "ALL_TOOLS",
           "split_fragment", "ArtifactRef", "ApprovalKind", "ImportArtifact", "import_artifacts",
           "Decision", "ApprovalStatus", "APPROVAL_FINAL",
           "ApprovalAudience", "STEWARD_KINDS", "OWNER_KINDS", "approval_audience",
           "ARTIFACT_INTAKE", "ARTIFACT_PUBLISH",
           "ArtifactChanged", "check_pointer", "check_event_id", "check_approval_id", "check_context", "check_title", "fit_title",
           "check_artifact_iri", "POINTER_SOURCES",
           "CONTEXT_KINDS", "ARTIFACT_CHANGES",
           "SpeakerPrompt", "speaker_prompts", "SpeakerCandidate", "speaker_candidates", "check_answer",
           "answer_value", "answer_fields", "SPEAKER_FIELDS",
           "Continuation", "continuation_of",
           "WorkflowStatus", "WORKFLOW_FINISHED", "WORKFLOW_OPEN", "WorkflowRequest",
           "InputKind", "InputField", "ProcessSpec", "PROCESSES", "VISIO_TO_ARCHIMATE",
           "MEETING_TO_TRANSCRIPT", "TRANSCRIPT_TO_MINUTES", "SPEECH_PROVIDERS",
           "USE_CASE_SCREENING", "USE_CASE_DESIGN", "USE_CASE_INVESTMENT", "USE_CASE_PROVISIONING",
           "AgentSpec", "AGENTS", "A2A_PROTOCOL_VERSION", "AGENT_CARD_VERSION", "AGENT_ORGANISATION"]
