"""The DOCUMENTATION FABRIC feature's slice of the contract: the semantic layer's tools, the change event every
source adapter emits, the intake and publish processes, and the agents that run them. Re-exported by
`lab.platform.contracts` for the callers that predate the split; a NEW name here is imported from this module.

Imported by the package `__init__` AFTER the kernel types it builds on AND after `PRODUCING_PROCESSES`, which
the intake process offers as its choices — so import it only through `lab.platform.contracts`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from lab.core.ids import POINTER_ID_FIELDS
from lab.platform import contracts as _kernel   # read at CALL time: the kernel's registries are assembled after this import
from lab.platform.contracts import (ARTIFACT_CHANGES, POINTER_SOURCES, PRODUCING_PROCESSES, AgentSpec, InputField,
                                    InputKind, ProcessSpec, ToolCatalogue, check_context, check_event_id,
                                    check_pointer)


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
    store_page = "semantic_store_page"   # raw text by ref (Markdown/HTML) — what `store_spec` cannot do without wrapping it
    questions = "semantic_questions"
    ask = "semantic_ask"
    # The Documentation Fabric's four metadata products (docs/fabric/notes 004/005) on the SAME server:
    # a query port is not a process, so it does not sit on workflow-mcp. The Catalog row, the rung-graph
    # edges, the vocabulary links and the facade over the embedding index (which proposes, never decides).
    catalog_get = "semantic_catalog_get"
    # Walking the catalogue, which nothing could do: the port had `get` by iri, `by_pointer`, ranked
    # `similar` and `unindexed(model)` — a scan keyed on an embedding model, the wrong question for
    # anything but re-indexing. An OPERATOR's verb: it enumerates the estate, so it is granted to the
    # curator and never to a workload agent, which has an iri or a pointer whenever it has business
    # with a record.
    catalog_list = "semantic_catalog_list"
    # Re-read ONE catalogued artifact with today's classifier. The caller names a record and supplies
    # NOTHING else: the pointer, the producer and the context all come from the row the fabric itself
    # recorded, which is what makes this legitimate for a process whose `submit` deliberately does not
    # exist (`ARTIFACT_INTAKE.external = False` — the event IS the provenance). Exactly the argument
    # `workflow_replay` makes: a caller may ask that inputs already accepted be used again, never
    # supply new ones. It lives HERE rather than on the workflow front door because resolving a record
    # needs the catalogue, and a cross-server call to fetch it would be the worse trade.
    catalog_reclassify = "semantic_catalog_reclassify"
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
    vocab_retire = "semantic_vocab_retire"         # a steward supersedes a concept; it still RESOLVES
    vocab_amend = "semantic_vocab_amend"           # a term is another way of saying one already held
    vocab_conflicts = "semantic_vocab_conflicts"   # words with two meanings, awaiting a steward
    vocab_candidates = "semantic_vocab_candidates" # terms with no meaning yet, awaiting a steward
    vocab_master = "semantic_vocab_master"         # the vocabulary as its master, staged for an operator
    embed = "semantic_embed"
    reindex = "semantic_reindex"
    similar = "semantic_similar"
    search = "semantic_search"
    recommend = "semantic_recommend"               # published only, with owners: "before you create" (BR-4)
    metrics = "semantic_metrics"                   # the published measurements (BR-8), numbers only
    derive = "semantic_derive"                     # rebuild rung D (two rules) — the publish workload, after a baseline
    topology = "semantic_topology"                 # what one record is about, drawn from the graph as it stands
    view_corpus = "semantic_view_corpus"           # ...and the whole catalogue in one picture, narrowable
    validate_shapes = "semantic_validate_shapes"
    promote = "semantic_promote"                   # a PERSON moves an assertion up the ladder (S→H)
    vocab_decline = "semantic_vocab_decline"       # ...and a PERSON'S NO about a term, recorded so it sticks
    # The CAFÉ views, one per step the CAFÉ bundle places one at — each read under the caller's pin
    # and stored as an HTML page, by ref (they replaced the ArchiMate/draw.io views, 29 Sep 2026).
    view_capabilities = "semantic_view_capabilities"     # step 5: the capability map, impact-filled
    view_realisations = "semantic_view_realisations"     # step 6: the realisation view, route marked
    view_ontology = "semantic_view_ontology"             # step 9: the ontology match
    view_workflow = "semantic_view_workflow"             # step 10: BPMN whose tasks are L3s
    view_architecture = "semantic_view_architecture"     # step 22: logical + physical, scope only
    VIEWS = (view_capabilities, view_realisations, view_ontology, view_workflow, view_architecture)
    # SIX GRANTS. `READ` is what every team had before the fabric and every query the products answer.
    # `PIPELINE` is what the intake and publish workloads write — per artifact, at a rung, with provenance —
    # and the curator. `PROMOTE` is a curator's decision and reaches only a channel that authenticates its
    # own human (the review app, the Teams bot), never a workload: an agent that could promote its own
    # suggestion to H would make the ladder decorative. `REINDEX` is an OPERATOR's whole-catalog sweep
    # (one gateway embed per row) after an embedder switch — the curator's, never prompt-reachable from a
    # workload agent. WRITE = PIPELINE + PROMOTE + REINDEX so the split ratchet
    # (`test_no_grant_hands_a_team_a_guarded_write_by_accident`) covers this catalogue too.
    READ = (ontologies, describe, classify, check, validate_model, load_model, query, schemes, concepts,
            export_archimate, store_spec, store_page, questions, ask,
            catalog_get, trace, impact, similar, search, recommend, metrics, validate_shapes,
            topology, view_corpus, vocab_conflicts, vocab_candidates, vocab_master) + VIEWS
    PIPELINE = (catalog_upsert, catalog_state, catalog_assert, edge_assert, edge_retract, vocab_link,
                vocab_propose, embed, derive)
    # A steward's decisions about the VOCABULARY itself, not about one artifact: admitting a concept
    # (`promote` with no predicate) and superseding one. Same grant, same reason — an agent that could
    # narrow the vocabulary it is classified against would be marking its own homework.
    PROMOTE = (promote, vocab_retire, vocab_amend, vocab_decline)
    REINDEX = (reindex,)
    # Enumerating the estate is an OPERATOR's verb, kept out of READ deliberately: a workload agent has an
    # iri or a pointer whenever it has business with a record, and a bot relaying one person's question has
    # no need for the list of everything. Granted to the curator alone, like REINDEX and for the same reason.
    WALK = (catalog_list,)
    # An OPERATOR's sweep over the estate, like REINDEX: it starts runs, so it is never a workload's.
    RECLASSIFY = (catalog_reclassify,)
    WRITE = PIPELINE + PROMOTE + REINDEX
    GRANTS = (READ, PIPELINE, PROMOTE, REINDEX, WALK, RECLASSIFY)


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
                   "The ULID of the ArtifactChanged event this run answers — the run's provenance. A "
                   "`reason=reclassify` run answers no event (nothing changed), so it mints a fresh ULID "
                   "identifying that re-read; `reason` is what says which of the two this is."),
        InputField("context", InputKind.CONTEXT,
                   "The delivery container the artifact was produced under, as <kind>:<id> "
                   "(usecase, meeting, submission, workitem). Known for anything a lab run produced; "
                   "absent for a document a person edited, which the run must then associate.",
                   required=False),
        InputField("produced_by", InputKind.CHOICE,
                   "Which lab process produced the artifact, when one did. Its declared document "
                   "type is then a FACT (rung C), not a suggestion.", required=False,
                   choices=PRODUCING_PROCESSES),
        InputField("reason", InputKind.CHOICE,
                   "Why this run exists. Absent means an artifact CHANGED, which is the ordinary case and "
                   "ends in a person's review card. 'reclassify' means the artifact did not change and the "
                   "fabric is re-reading it with better evidence: it re-links the subjects and asks nobody, "
                   "unless the document TYPE moves, which is a facet a person confirms.",
                   required=False, choices=("reclassify",)),
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
        if self.produced_by and self.produced_by not in _kernel.PROCESSES:   # every process, not this slice's
            raise ValueError(f"produced_by names unknown process {self.produced_by!r}")
        if self.context:
            object.__setattr__(self, "context", check_context(self.context, "context"))
        if self.fabric_tag is not None and not isinstance(self.fabric_tag, dict):
            raise ValueError("fabric_tag must be an object or null")

    @property
    def pointer_key(self) -> str:
        """`<source>:<item id>` — what makes two events for the same item the same event."""
        ident = next(self.pointer[k] for k in POINTER_ID_FIELDS if self.pointer.get(k))
        return f"{self.pointer['source']}:{ident}"

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


#: The fabric's agents, in the order `AGENTS` lists them.
AGENTS: tuple[AgentSpec, ...] = (
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

# WHAT THIS SLICE CONTRIBUTES — the kernel's PROCESSES, AGENTS and SERVERS are assembled from these.
PROCESSES: tuple[ProcessSpec, ...] = (ARTIFACT_INTAKE, ARTIFACT_PUBLISH)
CATALOGUES: tuple[type[ToolCatalogue], ...] = (SemanticTools,)

__all__ = ["SemanticTools", "ARTIFACT_INTAKE", "ARTIFACT_PUBLISH", "ArtifactChanged", "PROCESSES", "AGENTS",
           "CATALOGUES"]
