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

from lab.core.semantic.fabric.catalog import POINTER_ID_FIELDS

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



class ReferenceTools(ToolCatalogue):
    """reference-mcp — the GOVERNED CORPUS: signed, versioned artifacts, read only under a pin.

    Two verbs because there are two problems. `lookup` is exact over records — a nearly-right
    predicate or price line is worse than a failed lookup, so a miss is a legitimate answer and a
    near miss is reported separately from the records. `search` is semantic over the artifacts
    declared `vector` — prose, and record artifacts that also index, whose hits name the record —
    and refuses on a stale or differently-embedded index rather than ranking what it has (CR-12).

    There is deliberately NO WRITE tuple. Publication is an operator CLI holding the signing key and
    the publisher DSN; the server runs as a reader role that the database itself refuses writes
    from (DR-03). There is no tool a workload could be granted that mutates the corpus.
    """
    SERVER = "reference_mcp"
    catalogue = "reference_catalogue"
    pin = "reference_pin"
    #: A pin the caller already holds, rehydrated — what lets a REMOTE reader (decision-mcp,
    #: valuation-mcp, which hold no corpus credential) satisfy the port over these tools.
    pin_info = "reference_pin_info"
    lookup = "reference_lookup"
    search = "reference_search"
    record = "reference_record"
    consumers = "reference_consumers"

    READ = (catalogue, pin, pin_info, lookup, search, record)
    #: The reverse index spans RUNS, so it answers "what else consumed this version" — an audit
    #: question, not a derivation one. Granted separately, and never to a workload's own agents.
    AUDIT = (consumers,)



class VectorStores:
    """The relevance stores the gateway registers (`vector_store_registry`), one per vector-mode
    reference artifact — the store id IS the artifact id.

    A store is a GRANT unit: `object_permission.vector_stores` names stores, so one store per
    artifact lets the screening team hold the capability map and nothing else. A caller searches
    it through the gateway's OpenAI vector-store API, which reaches reference-mcp's façade over the
    same `search` the MCP tool uses — under a pin, attributed, and refused on a stale index. This
    catalogue is the ONE declaration: `scripts/register_vector_stores.py` reconciles the gateway's
    database to it on every deploy (a yaml `vector_store_registry` is deleted from memory by the
    list endpoint whenever a database is configured — verified), and a store here that the gateway
    does not register fails that step loudly rather than a run twenty minutes in.
    """
    CAPABILITY_MAP_HEALTHCARE = "capability-map-healthcare-provider-v2.0"
    CAPABILITY_MAP_INSURANCE = "capability-map-insurance-v5.0"

    #: What a person sees in the gateway UI beside the id.
    DESCRIPTION = {
        CAPABILITY_MAP_HEALTHCARE: "BA Guild Healthcare Provider capability map v2.0 (L1-L3 with "
                                   "path), read under a pin through reference-mcp",
        CAPABILITY_MAP_INSURANCE: "BA Guild Insurance capability map v5.0 (L1-L3 with path), read "
                                  "under a pin through reference-mcp",
    }
    #: The LiteLLM provider every store is served by: the OpenAI-compatible HTTP client that
    #: reference-mcp's façade satisfies.
    PROVIDER = "pg_vector"

    @classmethod
    def names(cls) -> frozenset[str]:
        return frozenset(v for k, v in vars(cls).items()
                         if not k.startswith("_") and k not in ("PROVIDER",) and isinstance(v, str))

    @classmethod
    def for_scheme(cls, scheme: str) -> str:
        """The store (= the corpus artifact) that holds a semantic scheme's capability map. The id
        is `capability-map-<scheme>` by construction, and a scheme with no store refuses here rather
        than at a search that would read as "the map has nothing on this"."""
        store = f"capability-map-{scheme}"
        if store not in cls.names():
            raise ValueError(f"no relevance store holds the capability map for scheme {scheme!r}; "
                             f"the stores are {sorted(cls.names())}")
        return store


class DecisionTools(ToolCatalogue):
    """decision-mcp — the CAFÉ derivations that are DETERMINISTIC, as governed tools.

    They are deployed rather than run inside the workload for the reason the framework gives: they
    read governed artifacts that change under governance approval, so a change to the criticality
    taxonomy or the guardrail set must not require an application release. Conformance review
    evaluates the same predicates against the same facet vectors, so one service also stops two
    implementations of one rule set drifting apart.

    All read-only derivations. No READ/WRITE split, because there is nothing here to split.
    """
    SERVER = "decision_mcp"
    #: The corpus artifacts the derivations read, so a workload can PIN exactly them before the
    #: first call: a derivation whose pin lacks one refuses (never answers from the image), and a
    #: pin of the whole corpus would put fifty unread versions in the run's consumption trail.
    #: decision-mcp's own RULES table is held equal to this by a test.
    READS = ("guardrails", "guardrail-mapping", "family-triggers")
    readiness = "decision_readiness"          # step 14 — the four M0 gates
    feasibility = "decision_feasibility"      # step 16 — proceed / reject / integration
    exposure = "decision_exposure"            # step 18 — exposure and influence per step
    obligations = "decision_obligations"      # step 19 — the control requirement set
    composition = "decision_composition"      # step 22 — topology, families, enforcement points


class ValuationTools(ToolCatalogue):
    """valuation-mcp — the two CAFÉ derivations that are FINANCIAL, as governed tools.

    A separate server from `decision_mcp` for the reason the framework splits them: the artifacts
    behind them have a different OWNER and a different release cadence. The price sheet, the role
    rate registry and the delegation-of-authority thresholds are finance's, and re-releasing them
    must not mean redeploying the service that holds architecture governance's guardrail set.

    Read-only, like the derivations next door — nothing here writes, so there is no READ/WRITE
    split to make.
    """
    SERVER = "valuation_mcp"
    #: The finance artifact the cost derivation reads under a pin (see DecisionTools.READS).
    READS = ("component-prices",)
    cost = "valuation_cost"                   # step 23 — the cost model over the reference sheet
    benefit = "valuation_benefit"             # step 24 — the drivers, the summary, the verdict


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
    # The Documentation Fabric's four metadata products (docs/fabric/notes 004/005) on the SAME server:
    # a query port is not a process, so it does not sit on workflow-mcp. The Catalog row, the rung-graph
    # edges, the vocabulary links and the facade over the embedding index (which proposes, never decides).
    catalog_get = "semantic_catalog_get"
    catalog_upsert = "semantic_catalog_upsert"
    catalog_state = "semantic_catalog_state"
    catalog_assert = "semantic_catalog_assert"     # a classified facet at a RUNG: row column + graph triple + PROV
    # "graph" is a banned word in a tool name (it is a collaboration vendor's product), so the Traceability
    # Graph's tools speak of EDGES and TRACES.
    edge_assert = "semantic_edge_assert"
    edge_retract = "semantic_edge_retract"
    trace = "semantic_trace"
    impact = "semantic_impact"                     # reads C·X·H·D — never S (NFR-7)
    vocab_link = "semantic_vocab_link"
    vocab_propose = "semantic_vocab_propose"
    embed = "semantic_embed"
    similar = "semantic_similar"
    search = "semantic_search"
    validate_shapes = "semantic_validate_shapes"
    promote = "semantic_promote"                   # a PERSON moves an assertion up the ladder (S→H)
    # THREE GRANTS. `READ` is what every team had before the fabric and every query the products answer.
    # `PIPELINE` is what the intake and publish workloads write — at a rung, with provenance — and no
    # other team. `PROMOTE` is a curator's decision and reaches only a channel that authenticates its
    # own human (the review app, the Teams bot), never a workload: an agent that could promote its own
    # suggestion to H would make the ladder decorative. WRITE = PIPELINE + PROMOTE so the split ratchet
    # (`test_no_grant_hands_a_team_a_guarded_write_by_accident`) covers this catalogue too.
    READ = (ontologies, describe, classify, check, validate_model, load_model, query, schemes, concepts,
            export_archimate, store_spec, questions, ask,
            catalog_get, trace, impact, similar, search, validate_shapes)
    PIPELINE = (catalog_upsert, catalog_state, catalog_assert, edge_assert, edge_retract, vocab_link,
                vocab_propose, embed)
    PROMOTE = (promote,)
    WRITE = PIPELINE + PROMOTE
    GRANTS = (READ, PIPELINE, PROMOTE)


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
        return cls.VERBS if spec.external else tuple(v for v in cls.VERBS if v != "submit")

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
    APPROVAL = "approval"  # ONE approval id (`apr-<12 hex>`): the decision a continuation was released by
    # The Documentation Fabric's three (docs/fabric/FRS.md §4.4, §4.6): a POINTER is a bounded structured
    # reference INTO a system of record (never content, never a URL); an EVENT is the ULID of the
    # ArtifactChanged that started a run; a CONTEXT is the delivery container an artifact was produced
    # under, as `<kind>:<id>` from a closed set of kinds (note 001: the work item is one kind of several).
    POINTER = "pointer"
    EVENT = "event"
    CONTEXT = "context"
    ARTIFACT = "artifact"  # ONE fabric artifact IRI, urn:fabric:artifact:<ULID> — the catalog's own identity


# A mapping is a human's answer, not a payload. Bounded so it can never become a way to smuggle
# arbitrary state through an input contract that is otherwise strictly by-reference.
MAX_MAPPING_ENTRIES = 64
MAX_MAPPING_BYTES = 8192
# A conversation id is an id. Teams' own is ~60 characters; the ceiling is generous for a provider
# that mints longer ones and still far too small to be a paragraph.
MAX_CONVERSATION_CHARS = 512
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
    choices: tuple[str, ...] = ()          # CHOICE only: the closed set of accepted values

    def __post_init__(self) -> None:
        # A CHOICE with no members would accept nothing (and read as an oversight); a CHOICE that
        # skipped this check would accept anything, which is the free-text field this kind exists
        # to avoid. Either way the failure belongs at construction, not at the first submit.
        if (self.kind is InputKind.CHOICE) != bool(self.choices):
            raise ValueError(f"{self.name}: CHOICE declares its choices, and nothing else takes them")

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
        if self.kind is InputKind.CHOICE:
            return self._choice(value)
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
    ),
    outputs=("trace_id", "transcript_ref", "minutes_ref", "model_id", "keywords", "summary",
             "provider",
             # what reached the collaboration platform, where to announce it, and why not when it
             # did not — delivery is best effort, so its outcome is reported rather than raised
             "delivered", "chat_id", "delivery"),
    # Continuation-only. `speaker_map` is a HUMAN'S answer to the approval the transcript run raised;
    # a caller who could submit this directly would supply their own attribution and bypass the one
    # gate the meeting pipeline has. The continuation runner starts it in-process, so this refusal
    # costs the legitimate path nothing.
    external=False,
)

# ---------------------------------------------------------------- the use-case intake pipeline
#
# FOUR processes, split at exactly the human gates that ALWAYS fire — steps 12, 26a and 26b. Step
# 16's gate is conditional (it routes a REJECTION to an architect; a proceed does not wait) and
# step 24's fires only when a benefit figure is missing, so neither is a boundary: a conditional
# boundary would need the ordinary path to self-submit the next process from inside a workload.
#
# Why not one 27-step run that blocks on its approvals. `lab.workloads.consumer` reads with count=1
# and states that concurrency is REPLICAS, so a run blocked for a multi-day review pins its replica
# and every other submission queues behind it. Worse, `close_stale_runs` marks any request the
# consumer took and never acked as FAILED on restart — and CD redeploys every service on every push
# to main, so a blocked three-day run would be destroyed by an unrelated commit. Continuations give
# NFR-04's multi-day open run for free: the durable state is the request hash, the art:// refs and
# the approval, none of which lives in a process's memory.

USE_CASE_SCREENING = ProcessSpec(
    name="use_case_screening",
    group="wf-usecase-screening",
    title="Screen a submitted AI use case and derive its criticality class",
    description=(
        "Take a business team's AI use case as prose and run the first half of the CAFÉ assessment "
        "over it: frame the problem and name one accountable owner, decompose it into active, "
        "behavioural and passive elements, match those to business capabilities and to what already "
        "realises them, derive quality attributes from existing service commitments, check every "
        "business object against the ontology, sequence the work into an explicit workflow graph, "
        "contract its grounding sources, and derive the criticality class. "
        "Ends by asking an architect to confirm that class — the class governs the rigour of a "
        "system somebody else will build, and under-classification propagates. Approving it starts "
        "the design run; nothing else can."),
    inputs=(
        InputField("submission", InputKind.REF,
                   "ONE art://<id>/<name> reference to the submitted use case as prose — a .md, "
                   ".docx or .pdf saying what the problem is, who has it, and what changes if it "
                   "works. Upload it first; a workload reads it through the governed store and "
                   "never from the channel it arrived on.", required=False),
        InputField("submission_handle", InputKind.HANDLE,
                   "Alternative to `submission` for a channel that has the document in the "
                   "collaboration platform rather than in the upload store: the run fetches it "
                   "into the store as its first step. Supply exactly one of the two.",
                   required=False),
        InputField("attachments", InputKind.REF_LIST,
                   "Optional supporting documents — the current process description, a vendor "
                   "quote, an existing analysis. Evidence, not new scope.", required=False),
        InputField("submitter", InputKind.IDENTITY,
                   "The business owner submitting it. Recorded as the accountable person on the "
                   "record and told the outcome — and told only after an architect has seen a "
                   "rejection, never before."),
        InputField("intake", InputKind.MAPPING,
                   "The structured intake fields the business case needs, which prose cannot carry "
                   "reliably: the effort table (role, headcount, frequency per week, current and "
                   "expected minutes), the quality baseline (volume, error rate, expected "
                   "reduction, error class), the sensitivity flags, the budget bucket or vendor "
                   "quote, and the urgency. Missing entries do not block the run — they become "
                   "requires-input markers that the business case carries to the approver as gate "
                   "conditions rather than estimating around.", required=False),
        InputField("conversation", InputKind.CONVERSATION,
                   "Optional id of the conversation the submission came from, so the outcome can "
                   "be announced where it was asked for.", required=False),
    ),
    outputs=("trace_id", "approval_id", "review_app", "submission_ref", "screening_ref",
             "criticality_band", "summary"),
)

USE_CASE_DESIGN = ProcessSpec(
    name="use_case_design",
    group="wf-usecase-design",
    title="Rule on feasibility, then derive the obligations, architecture, cost and business case",
    description=(
        "Continues a screened use case once an architect has confirmed its criticality class. "
        "Declares the outcome assertions, computes the readiness verdict and the determinism "
        "classification, and rules on feasibility. A rejection or an integration finding HALTS the "
        "run here — steps 17 to 25 are not attempted and no partial design package is produced — "
        "and goes to an architect before the submitter hears it. Otherwise it derives the facet "
        "vectors, the exposure and influence classes, the control requirement set, the build "
        "surface, the component selection and the composed architecture, then costs it and builds "
        "the business case, ending at the architect's conformance decision. "
        "Cannot be started directly: its criticality class is a human's answer, and a caller able "
        "to start it would supply its own."),
    inputs=(
        InputField("submission_ref", InputKind.REF,
                   "The validated submission record the screening run persisted."),
        InputField("screening_ref", InputKind.REF,
                   "The screening run's derived output — the elements, capability coverage, "
                   "realisations, quality attributes, ontology findings, workflow graph and "
                   "source contracts, as one artifact."),
        InputField("criticality", InputKind.MAPPING,
                   "The architect's answer at step 12: the confirmed criticality class, and a "
                   "justification where it differs from the derived one. An override is a "
                   "calibration signal for the framework, so it is recorded rather than replaced."),
        InputField("submitter", InputKind.IDENTITY,
                   "Carried from the submission so the outcome reaches the person who asked.",
                   required=False),
        InputField("conversation", InputKind.CONVERSATION,
                   "Carried from the submission, for announcing the outcome.", required=False),
    ),
    outputs=("trace_id", "approval_id", "review_app", "verdict", "halted",
             "readiness", "governance_tier", "risk_ref", "obligations_ref", "architecture_ref",
             "cost_ref", "business_case_ref", "recommendation", "delivery_ref", "summary"),
    external=False,
)

USE_CASE_INVESTMENT = ProcessSpec(
    name="use_case_investment",
    group="wf-usecase-investment",
    title="Route the conformance-approved design to the authority that can fund it",
    description=(
        "Continues a design an architect has approved on conformance. Assembles the investment "
        "package — the financial summary, the recommendation and every open gate condition — and "
        "routes it to the delegated authority the investment value calls for. "
        "Conformance approval is not funding approval: a conformant design can be deferred on "
        "value and a valuable one returned on conformance, so the two decisions are taken by "
        "different people against different questions and recorded separately."),
    inputs=(
        InputField("design_ref", InputKind.REF,
                   "The design package the conformance decision approved."),
        InputField("conformance", InputKind.MAPPING,
                   "The architect's answer at step 26a: the conformance decision and any conditions "
                   "attached to it."),
        InputField("submitter", InputKind.IDENTITY, "Carried through.", required=False),
        InputField("conversation", InputKind.CONVERSATION, "Carried through.", required=False),
    ),
    outputs=("trace_id", "approval_id", "review_app", "investment_ref", "recommendation",
             "authority", "summary"),
    external=False,
)

USE_CASE_PROVISIONING = ProcessSpec(
    name="use_case_provisioning",
    group="wf-usecase-provisioning",
    title="Create the work items and catalog entries an approved investment authorised",
    description=(
        "Continues an investment the delegated authority approved. Creates the work item tree and "
        "the portal catalog entries in the target systems — idempotently and reversibly, so "
        "re-running an approved package creates nothing new. "
        "Nothing is created before that approval, and no earlier process is even granted a write "
        "tool: the control is a grant, not a branch somebody could take the wrong way."),
    inputs=(
        InputField("investment_ref", InputKind.REF,
                   "The investment package the funding decision approved."),
        InputField("authorisation", InputKind.MAPPING,
                   "The delegated authority's answer at step 26b: the funding decision, the "
                   "authority that took it, and any conditions."),
        InputField("submitter", InputKind.IDENTITY, "Carried through.", required=False),
    ),
    outputs=("trace_id", "provisioned", "work_items_ref", "catalog_ref", "import_artifacts",
             # The staging key, declared as an output because it is what makes a re-run checkable
             # from OUTSIDE: two runs of one approved package answer with the same key.
             "idempotency", "summary"),
    external=False,
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
    AgentSpec(name="meeting-agent", prefix="MEETING_AGENT",
              description="Fetches a meeting recording and has it transcribed and diarized.",
              skills=("transcription",),                       # tool-only: every step deterministic
              processes=("meeting_to_transcript",)),
    AgentSpec(name="minutes-agent", prefix="MINUTES_AGENT",
              description="Turns an attributed transcript into gated minutes and a concept model.",
              skills=("minutes",), model="kimi-k3",
              processes=("transcript_to_minutes",)),
    AgentSpec(name="usecase-agent", prefix="USECASE_AGENT",
              description="Screens a submitted use case and designs it.",
              skills=("use_case_screening", "use_case_design"), model="kimi-k3",
              processes=("use_case_screening", "use_case_design")),
    AgentSpec(name="usecase-delivery-agent", prefix="USECASE_DELIVERY",
              description="Values a designed use case and provisions its delivery artifacts.",
              skills=("use_case_investment", "use_case_provisioning"), model="kimi-k3",
              processes=("use_case_investment", "use_case_provisioning")),

    # The ten CAFE bounded contexts. One registration, one key, one card each — because spend
    # attributes per identity, so "the risk officer costs four times what the cost engineer does" is
    # a fact somebody can read rather than infer, and a wrong answer is attributable to the context
    # that gave it rather than to "the use-case workload". `processes` here mirrors which steps each
    # context OWNS in `lab.workloads.usecase.steps`; the parity test is what keeps the two agreeing,
    # since this tier may not import a workload to derive it.
    AgentSpec(name="usecase-business-analyst", prefix="USECASE_BA",
              description="Frames a submitted use case and maps the workflow it implies.",
              skills=("use_case_framing",), model="kimi-k3", processes=("use_case_screening",)),
    AgentSpec(name="usecase-business-architect", prefix="USECASE_BUSARCH",
              description="Identifies the business elements a use case touches and maps its coverage.",
              skills=("capability_mapping",), model="kimi-k3", processes=("use_case_screening",)),
    AgentSpec(name="usecase-application-architect", prefix="USECASE_APPARCH",
              description="Matches a use case to the applications that would realise it.",
              skills=("realisation_matching",), model="kimi-k3", processes=("use_case_screening",)),
    AgentSpec(name="usecase-risk-officer", prefix="USECASE_RISK",
              description="Bands a use case for criticality and states its exposure facets.",
              skills=("criticality_banding",), model="kimi-k3",
              processes=("use_case_screening", "use_case_design")),
    AgentSpec(name="usecase-product-owner", prefix="USECASE_PO",
              description="States the quality attributes, assertions and delivery artifacts a use case needs.",
              skills=("quality_attributes",), model="kimi-k3",
              processes=("use_case_screening", "use_case_design")),
    AgentSpec(name="usecase-data-architect", prefix="USECASE_DATA",
              description="States the ontology delta a use case implies and the contracts of its sources.",
              skills=("ontology_delta",), model="kimi-k3", processes=("use_case_screening",)),
    AgentSpec(name="usecase-solution-architect", prefix="USECASE_SOLARCH",
              description="Decides what must be deterministic and selects the components.",
              skills=("component_selection",), model="kimi-k3", processes=("use_case_design",)),
    AgentSpec(name="usecase-technology-architect", prefix="USECASE_TECHARCH",
              description="States the build surface a designed use case requires.",
              skills=("build_surface",), model="kimi-k3", processes=("use_case_design",)),
    AgentSpec(name="usecase-cost-engineer", prefix="USECASE_COST",
              description="States the cost inputs a use case's investment case is valued on.",
              skills=("cost_inputs",), model="kimi-k3", processes=("use_case_design",)),
    AgentSpec(name="usecase-value-analyst", prefix="USECASE_VALUE",
              description="States the benefit inputs a use case's investment case is valued on.",
              skills=("benefit_inputs",), model="kimi-k3", processes=("use_case_design",)),

    # The Documentation Fabric (docs/fabric/POC.md). Two identities, because the classifier SUGGESTS
    # (rung S) and the synthesiser WRITES tagged drafts — different powers, so different keys, so a
    # draft is attributable to the identity that wrote it.
    AgentSpec(name="classifier-agent", prefix="CLASSIFIER_AGENT",
              description="Suggests an artifact's document type and the vocabulary concepts it is about; never resolves owner or label.",
              skills=("fabric_classification",), model="kimi-k3", processes=("artifact_intake",)),
    AgentSpec(name="synthesis-agent", prefix="SYNTHESIS_AGENT",
              description="Drafts decision records from approved minutes into the fabric's tagged drafts; writes nothing else.",
              skills=("fabric_decision_record",), model="kimi-k3", processes=("artifact_intake",)),
    AgentSpec(name="publish-agent", prefix="PUBLISH_AGENT",
              description="Baselines and re-indexes a record whose review a person approved; reads the decision, writes no content.",
              skills=("fabric_publish",), processes=("artifact_publish",)),   # tool-only: every step deterministic
)


#: Every process whose outputs the fabric ingests — the specs themselves, so a producer added above is a
#: producer here (a test holds this equal to PROCESSES minus the fabric's own two).
PRODUCING_PROCESSES: tuple[str, ...] = tuple(p.name for p in (VISIO_TO_ARCHIMATE, MEETING_TO_TRANSCRIPT,
                                                              TRANSCRIPT_TO_MINUTES, USE_CASE_SCREENING,
                                                              USE_CASE_DESIGN, USE_CASE_INVESTMENT,
                                                              USE_CASE_PROVISIONING))

ARTIFACT_INTAKE = ProcessSpec(
    name="artifact_intake",
    group="wf-fabric",
    title="One changed artifact becomes a catalogued, classified, linked and reviewed record",
    description=(
        "The Documentation Fabric's standing pipeline for ONE artifact that changed in a system of "
        "record: mint or find its identity, classify it (type suggested; owner and label looked up), "
        "link it to its delivery context and to what it references, record what it affects, draft "
        "decision records where the artifact is minutes, check overlap, and ask the owner to review. "
        "It writes only metadata and tagged drafts. "
        "Started ONLY by the fabric's own ingress from an ArtifactChanged event: an outside caller "
        "cannot start it, because the event IS the provenance of everything the run records."),
    inputs=(
        InputField("pointer", InputKind.POINTER,
                   "The item that changed, as a pointer into its system of record: {source: 'collab', "
                   "handle, version} for a file behind the collaboration port, {source: 'lab', ref} for "
                   "an artifact a lab run wrote. Never content, never a URL."),
        InputField("event_id", InputKind.EVENT,
                   "The ULID of the ArtifactChanged event this run answers — the run's provenance."),
        InputField("context", InputKind.CONTEXT,
                   "The delivery container the artifact was produced under, as <kind>:<id> "
                   "(usecase, meeting, submission, workitem). Known for anything a lab run produced; "
                   "absent for a document a person edited, which the run must then associate.",
                   required=False),
        InputField("produced_by", InputKind.CHOICE,
                   "Which lab process produced the artifact, when one did. Its declared document "
                   "type is then a FACT (rung C), not a suggestion.", required=False,
                   choices=PRODUCING_PROCESSES),
    ),
    outputs=("trace_id", "artifact_iri", "approval_id", "draft_refs", "rung_counts"),
    external=False,
)

ARTIFACT_PUBLISH = ProcessSpec(
    name="artifact_publish",
    group="wf-artifact-publish",
    title="A reviewed artifact is baselined, its assertions promoted, and its projection regenerated",
    description=(
        "The continuation an approved draft-review releases: record the baseline (which source "
        "version was approved, by whom, when), promote the suggested assertions the owner confirmed "
        "to human-confirmed, refresh the artifact's embedding, and publish the finished-run event "
        "the projector turns into a wiki page. "
        "Started ONLY by approving the draft-review question an artifact_intake run raised."),
    inputs=(
        InputField("artifact_iri", InputKind.ARTIFACT,
                   "The catalog IRI of the artifact the owner approved, urn:fabric:artifact:<ULID>."),
        InputField("approval_id", InputKind.APPROVAL, "The approval whose decision released this run."),
    ),
    outputs=("trace_id", "baseline", "promoted", "projection_ref"),
    external=False,
)

PROCESSES: dict[str, ProcessSpec] = {p.name: p for p in (VISIO_TO_ARCHIMATE, MEETING_TO_TRANSCRIPT,
                                                         TRANSCRIPT_TO_MINUTES,
                                                         USE_CASE_SCREENING, USE_CASE_DESIGN,
                                                         USE_CASE_INVESTMENT,
                                                         USE_CASE_PROVISIONING,
                                                         ARTIFACT_INTAKE, ARTIFACT_PUBLISH)}


@dataclass(frozen=True)
class ArtifactChanged:
    """Port 1 of every source adapter (docs/fabric/notes/2026-09-11-ports-adapters-events.md): ONE
    change to ONE item in a system of record, in the ontology's terms, on a durable stream. The
    fabric consumes this and knows nothing of webhooks. `pointer_key` is the idempotency key; a
    `fabric_tag` marks a write the fabric itself made, which the ingress drops (the loop guard)."""

    event_id: str
    pointer: dict[str, str]
    source_kind: str
    change: str
    actor_oid: str
    occurred_at: str
    fabric_tag: dict[str, str] | None = None
    produced_by: str = ""          # the lab process that wrote the item, when one did
    context: str = ""              # the delivery context, when the producer knew it

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", check_event_id(self.event_id, "event_id"))
        object.__setattr__(self, "pointer", check_pointer(self.pointer, "pointer"))
        if self.source_kind not in POINTER_SOURCES:
            raise ValueError(f"source_kind must be one of {list(POINTER_SOURCES)}, not {self.source_kind!r}")
        if self.change not in ARTIFACT_CHANGES:
            raise ValueError(f"change must be one of {list(ARTIFACT_CHANGES)}, not {self.change!r}")
        if not isinstance(self.actor_oid, str) or not self.occurred_at:
            raise ValueError("actor_oid and occurred_at are required")
        if self.produced_by and self.produced_by not in PROCESSES:
            raise ValueError(f"produced_by names unknown process {self.produced_by!r}")
        if self.context:
            object.__setattr__(self, "context", check_context(self.context, "context"))
        if self.fabric_tag is not None and not isinstance(self.fabric_tag, dict):
            raise ValueError("fabric_tag must be an object or null")

    @property
    def pointer_key(self) -> str:
        """`<source>:<item id>` — what makes two events for the same item the same event."""
        from lab.core.semantic.fabric.catalog import pointer_key
        return pointer_key(self.pointer)

    @property
    def is_fabric_originated(self) -> bool:
        return bool(self.fabric_tag)

    def to_fields(self) -> dict[str, str]:
        """Redis stream fields: every value a string; JSON where the value is structured."""
        return {"event_id": self.event_id, "pointer": json.dumps(self.pointer, sort_keys=True),
                "source_kind": self.source_kind, "change": self.change, "actor_oid": self.actor_oid,
                "occurred_at": self.occurred_at, "fabric_tag": json.dumps(self.fabric_tag or {}),
                "produced_by": self.produced_by, "context": self.context}

    @classmethod
    def from_fields(cls, f: dict[str, Any]) -> "ArtifactChanged":
        tag = json.loads(f.get("fabric_tag") or "{}") if isinstance(f.get("fabric_tag"), str) else (f.get("fabric_tag") or {})
        return cls(event_id=str(f.get("event_id", "")), pointer=f.get("pointer", ""),
                   source_kind=str(f.get("source_kind", "")), change=str(f.get("change", "")),
                   actor_oid=str(f.get("actor_oid", "")), occurred_at=str(f.get("occurred_at", "")),
                   fabric_tag=(tag or None), produced_by=str(f.get("produced_by") or ""),
                   context=str(f.get("context") or ""))


# ----------------------------------------------------------------------------- the registry of servers
# Last, because WorkflowTools' tool names are derived from PROCESSES above.
SERVERS: dict[str, type[ToolCatalogue]] = {c.SERVER: c for c in (StorageTools, SemanticTools, EATools,
                                                                 WorkflowTools, CollabTools,
                                                                 SpeechTools, ReferenceTools,
                                                                 DecisionTools,
                                                                 ValuationTools)}
ALL_TOOLS: frozenset[str] = frozenset(n for c in SERVERS.values() for n in c.names())


__all__ = ["gateway_name", "ToolCatalogue", "StorageTools", "SemanticTools", "EATools", "WorkflowTools",
           "ApprovalTools", "ApiRoles", "CollabTools", "SpeechTools", "ReferenceTools", "DecisionTools", "ValuationTools",
           "VectorStores", "SERVERS", "ALL_TOOLS",
           "split_fragment", "ArtifactRef", "ApprovalKind", "ImportArtifact", "import_artifacts",
           "Decision", "ApprovalStatus", "APPROVAL_FINAL", "ARTIFACT_INTAKE", "ARTIFACT_PUBLISH",
           "ArtifactChanged", "check_pointer", "check_event_id", "check_approval_id", "check_context",
           "check_artifact_iri", "POINTER_SOURCES",
           "CONTEXT_KINDS", "ARTIFACT_CHANGES",
           "SpeakerPrompt", "speaker_prompts", "SpeakerCandidate", "speaker_candidates", "check_answer",
           "answer_value", "answer_fields", "SPEAKER_FIELDS",
           "Continuation", "continuation_of",
           "WorkflowStatus", "WORKFLOW_FINISHED", "WORKFLOW_OPEN", "WorkflowRequest",
           "InputKind", "InputField", "ProcessSpec", "PROCESSES", "VISIO_TO_ARCHIMATE",
           "MEETING_TO_TRANSCRIPT", "TRANSCRIPT_TO_MINUTES",
           "AgentSpec", "AGENTS", "A2A_PROTOCOL_VERSION", "AGENT_CARD_VERSION", "AGENT_ORGANISATION"]
