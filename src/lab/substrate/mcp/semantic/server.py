"""semantic-mcp — the lab's semantic layer as governed MCP tools (port 9200, /mcp).

Separate from adoit-mcp on purpose: this server is domain-general (vocabularies are data —
ArchiMate today, DOH glossaries / FHIR / TOGAF later), holds no credentials and only answers
questions, so it is granted to every team; adoit-mcp is the EA-repository facade with the
governed write path. Same engine library for both worlds: the skill imports `semantic`
directly, agents reach it through LiteLLM's MCP gateway.

Tools
  semantic_ontologies()                       vocabularies available + sizes
  semantic_describe(type, vocab)              classification card: layer, aspect, definition, examples, confusables
  semantic_classify(text, vocab)              candidate types for a concept description (agent decides)
  semantic_check(source, relation, target)    exact legality (ArchiMate Appendix B matrix) + what IS allowed
  semantic_validate_model(spec)               all illegal relationships + semantic warnings (interface exposure…)
  semantic_load_model(spec, model_id)         model -> RDF with derived relations, queryable
  semantic_query(sparql)                      SPARQL over vocabularies + loaded models
  semantic_ask(question, params)              named traceability questions; semantic_questions() lists them

The Documentation Fabric's four metadata products live HERE too (docs/fabric/notes 004/005) — a query port
is not a process, so it does not sit on workflow-mcp. Rung graphs share the store's Dataset (SPARQL sees
vocabularies + fabric together), are SHACL-checked on every write and shadowed to the artifact store
(`rung_store`); the Catalog rows are Postgres when `FABRIC_DB_URL`/`DATABASE_URL` is set, in-process otherwise.
  semantic_catalog_get|upsert|state|assert    the Catalog product (identity, custody, facets at a rung, lifecycle)
  semantic_edge_assert|retract|traverse|impact   the Traceability Graph (impact never reads S)
  semantic_vocab_link|propose                 the Vocabulary product (label match at X; candidates for a steward)
  semantic_embed|similar|search               the facade over the embedding index (proposes, never decides)
  semantic_validate_shapes · semantic_promote the fitness function, and the curator's gate (actor required)
"""
import json
import os

from lab.core.semantic.fabric.service import FabricService
from lab.core.semantic.service import SemanticService
from lab.platform import config
from lab.substrate.mcp.semantic.rung_store import RungStore
from lab.substrate.mcpserver import LabServer, span

SERVICE = "semantic-mcp"

server = LabServer(SERVICE, config.SEMANTIC_MCP_PORT)


def reference_dir(refs=config.REFERENCE_MODELS_REFS, directory=config.REFERENCE_MODELS_DIR) -> str:
    """Where the licensed reference workbooks are, materialising them first if they arrive by ref.

    They cannot be in the image. This repository is public and the BA Guild models are licensed, so
    neither the workbooks nor content derived from them can be committed — but a cloud deployment
    that lacks them answers `unknown scheme`, and every capability match silently becomes a gap.
    Measured on the first cloud run: `unknown scheme healthcare-provider-v2.0; have []`.

    So they travel the way all content in this lab travels — by `art://` reference through the
    private artifact store, which the substrate already holds a credential for and the image does
    not contain. `lab.core` still just globs a directory: the domain knows nothing about stores,
    and a workstation with the workbooks on disk is unaffected.
    """
    if not refs:
        return directory
    import tempfile
    from pathlib import Path

    store = server.container.artifacts()
    out = Path(tempfile.mkdtemp(prefix="reference-models-"))
    for ref in refs:
        # The NAME in the ref is the filename, and the loader keys the scheme on the stem — so a
        # ref must keep the workbook's own name or the scheme comes back under a different one.
        (out / ref.rsplit("/", 1)[-1]).write_bytes(store.get(ref))
    return str(out)


S = SemanticService(reference_dir=reference_dir())
# The fabric over the SAME dataset and registry: the rung graphs are named graphs beside the vocabularies, so
# `semantic_query` answers the competency questions with no second store. Composed at BOOT (`boot()`), not at
# import: the catalog and the embedder are clients, and a module that builds clients on import cannot be
# imported by a test that means to override them.
RUNGS = RungStore(artifacts=server.artifacts, redis=server.container.redis)
F: FabricService | None = None


def boot() -> dict[str, int]:
    """Compose the fabric from the container, apply the catalog's schema, restore the persisted rung graphs.
    Part of STARTING, not of importing — `__main__` calls it before `serve`, a test after its overrides."""
    global F
    catalog = server.container.catalog()
    F = FabricService(S.store.ds, catalog, S.doc_types, schemes=lambda: S.schemes_,
                      embedder=server.container.embedder(),
                      on_write=lambda names: RUNGS.save(F, names))
    if hasattr(catalog, "ensure_schema"):
        catalog.ensure_schema()
    return RUNGS.restore(F)


def fabric() -> FabricService:
    if F is None:
        raise RuntimeError("the fabric is not booted — semantic-mcp calls boot() before serving")
    return F


@server.tool()
def semantic_ontologies() -> list:
    """Vocabularies available in the semantic layer and their sizes."""
    return S.ontologies()


@server.tool()
def semantic_describe(type: str, vocab: str = "archimate-3.1") -> dict:
    """Classification card for an element type: layer, aspect (active/behaviour/passive),
    definition, examples, and what it is commonly confused with."""
    return S.describe(type, vocab)


@server.tool()
def semantic_classify(text: str, vocab: str = "archimate-3.1", limit: int = 5) -> list:
    """Candidate element types for a concept described in words (e.g. 'REST API exposed by
    the backend'). Deterministic keyword scoring — the agent makes the final call using the
    definitions returned."""
    return S.classify(text, vocab, limit)


@server.tool()
def semantic_check(source: str, relation: str, target: str, vocab: str = "archimate-3.1") -> dict:
    """Is `relation` permitted from element type `source` to `target`? Exact answer from the
    ArchiMate relationship matrix, plus the full list of what is allowed for that pair."""
    return S.check(source, relation, target, vocab)


@server.tool()
def semantic_validate_model(spec: dict | None = None, vocab: str = "archimate-3.1",
                            spec_ref: str | None = None) -> dict:
    """Validate a model spec (same JSON as archimate_render): every illegal relationship with
    the allowed alternatives, plus semantic warnings such as services consumed without an
    interface assigned to them. Pass the spec by value (`spec`) or by artifact reference
    (`spec_ref`, art://…) — the reference keeps the tool argument small for agent callers."""
    spec = server.spec(spec, spec_ref=spec_ref)
    r = S.validate_model(spec, vocab)
    span().set_attributes({"semantic.illegal": len(r["illegal"]), "semantic.warnings": len(r["warnings"])})
    return r


@server.tool()
def semantic_load_model(spec: dict | None = None, model_id: str = "", vocab: str = "archimate-3.1",
                        spec_ref: str | None = None) -> dict:
    """Load a model into the semantic store as RDF (with derived relationships) so it can be queried
    with semantic_query / semantic_ask.

    Pass the spec by value (`spec`) or by artifact reference (`spec_ref`, art://…), exactly as
    semantic_validate_model does. The reference is what a WORKLOAD must use: it holds no store
    credentials, so a spec it produced is already an art:// ref and cannot be passed any other way.

    NOTE the store is IN-MEMORY and per process: what is loaded here is queryable for the life of
    this server and does not survive a restart or reach a second replica. Keep the durable copy as
    an artifact (semantic_store_spec) and reload it when it is needed."""
    spec = server.spec(spec, spec_ref=spec_ref)
    if not model_id:
        raise ValueError("model_id is required — it names the graph this model is loaded into")
    r = S.load_model(spec, model_id, vocab)
    span().set_attributes({"semantic.triples": r["triples"], "semantic.derived": r["derived_relations"]})
    return r


@server.tool()
def semantic_query(sparql: str, limit: int = 200) -> dict:
    """Run SPARQL across the vocabularies and every loaded model. Prefixes:
    am: <urn:lab:semantic:archimate#>  meta: <urn:lab:semantic:meta#>. Derived relations
    are am:derivedRealization / am:derivedServing / am:derivedAssignment / ..."""
    return S.query(sparql, limit)


@server.tool()
def semantic_schemes() -> list:
    """Reference models loaded as SKOS concept schemes (capability maps, value streams,
    organisation / stakeholder / information maps) with per-kind, per-level counts."""
    return S.schemes()


@server.tool()
def semantic_concepts(scheme: str, root_label: str | None = None, depth: int | None = None,
                      kind: str = "capability") -> list:
    """Concepts of a reference scheme: the whole map, or the subtree under `root_label`
    (e.g. 'Patient Management') to `depth` levels. kinds: capability, value-stream, org-unit,
    stakeholder, information."""
    return S.concepts(scheme, root_label, depth, kind)


@server.tool()
def semantic_export_archimate(scheme: str, root_label: str | None = None, depth: int | None = None,
                              kind: str = "capability", views: str = "overview,branches",
                              out_path: str | None = None, by_ref: bool = True) -> dict:
    """Project a reference scheme (or subtree) to an ArchiMate model spec — Capability /
    ValueStream elements with Composition, plus an L1 overview view and one nested view per
    top concept. Feed the result to the EA-repository server's archimate_render + ea_stage_import:
    that is the governed way to write reference capabilities into the EA repository.
    By default the spec is stored as an artifact and only counts + spec_ref (art://…) are
    returned — the gateway meters tool payloads as tokens and ea-mcp accepts spec_ref from
    any host. by_ref=False returns the payload inline (small subtrees); out_path also writes a
    local copy (dev)."""
    spec = S.export_archimate(scheme, root_label, depth, kind, views)
    span().set_attributes({"semantic.scheme": scheme, "semantic.elements": len(spec["elements"])})
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        json.dump(spec, open(out_path, "w"), indent=0)
    if by_ref:
        ref = server.artifacts().put(f'{spec["id"]}.spec.json', json.dumps(spec).encode(), "application/json")
        return {"spec_ref": ref, "spec_path": out_path, "name": spec["name"], "id": spec["id"],
                "elements": len(spec["elements"]), "relations": len(spec["relations"]),
                "views": len(spec["views"])}
    return spec


@server.tool()
def semantic_store_spec(spec: dict | str, name: str = "model.spec.json") -> dict:
    """Store a model spec (the archimate_render / semantic_validate_model JSON) in the artifact
    store and return its art:// reference plus counts. Lets a workload keep its intermediate
    spec BY REFERENCE without holding store credentials itself — the deterministic workflow
    node calls this through the gateway. Writes only to the artifact store (never to the EA
    repository), so it needs no human approval."""
    spec = server.spec(spec)
    ref = server.artifacts().put(name, json.dumps(spec).encode(), "application/json")
    span().set_attributes({"semantic.spec_ref": ref, "semantic.elements": len(spec.get("elements", [])),
                           "semantic.relations": len(spec.get("relations", []))})
    return {"spec_ref": ref, "name": name, "elements": len(spec.get("elements", [])),
            "relations": len(spec.get("relations", [])), "views": len(spec.get("views", []))}


@server.tool()
def semantic_questions() -> dict:
    """Named traceability questions available to semantic_ask, with their parameters."""
    return S.questions()


@server.tool()
def semantic_ask(question: str, params: dict | None = None) -> dict:
    """Ask a named question, e.g. semantic_ask('goals_realized_by_components_on_node',
    {'node': 'M1'}) -> which goals are transitively realized by components on that node."""
    span().set_attribute("semantic.question", question)
    return S.ask(question, **(params or {}))


# ------------------------------------------------------------------------------ the Documentation Fabric

@server.tool()
def semantic_catalog_get(iri: str = "", pointer: dict | None = None) -> dict | None:
    """The Catalog row for an artifact — by IRI, or by POINTER ({source, handle|ref|…}) — plus its graph
    links by rung (delivery, references, subjects, facets), or null. Identity and custody only — never content."""
    return fabric().catalog_get(iri, pointer=pointer)


@server.tool()
def semantic_catalog_upsert(pointer: dict, iri: str = "", title: str = "", produced_by: str = "",
                            context: str = "", source_kind: str = "") -> dict:
    """Identify an artifact: mint its IRI (or find it by pointer) and mirror the row into rung C. A lab
    process's output (`produced_by`) gets its document type as a FACT and its delivery edge from the run's
    `context` (`<kind>:<id>`). Idempotent on the pointer."""
    r = fabric().catalog_upsert(pointer, iri=iri, title=title, produced_by=produced_by, context=context, source_kind=source_kind)
    span().set_attributes({"fabric.iri": r["iri"], "fabric.produced_by": produced_by or ""})
    return r


@server.tool()
def semantic_catalog_state(iri: str, state: str, baseline_version: str | None = None,
                           unassociated: bool | None = None) -> dict:
    """Move an artifact's lifecycle (pending | in-review | published | withdrawn), optionally recording the
    baseline version and whether it is unassociated with any delivery context."""
    return fabric().catalog_state(iri, state, baseline_version=baseline_version, unassociated=unassociated)


@server.tool()
def semantic_catalog_assert(iri: str, field: str, value: str, rung: str, method: str, actor: str = "",
                            confidence: float | None = None) -> dict:
    """Assert a classified facet (document_type | owner | sensitivity_label) at a provenance rung: the row's
    column AND the graph triple with its PROV record. Owner and label are refused anywhere but C (NFR-3)."""
    return fabric().catalog_assert(iri, field, value, rung=rung, method=method, actor=actor, confidence=confidence)


@server.tool()
def semantic_edge_assert(subject: str, predicate: str, object: str, rung: str, method: str, actor: str = "",
                          confidence: float | None = None, supersede: bool = False) -> dict:
    """Enter one edge at a rung (S needs a confidence; D is computed, never asserted). SHACL-checked: a
    content property never enters. `supersede` retracts the subject's previous value of that predicate."""
    return fabric().graph_assert(subject, predicate, object, rung=rung, method=method, actor=actor,
                          confidence=confidence, supersede=supersede)


@server.tool()
def semantic_edge_retract(subject: str, predicate: str, object: str, actor: str, reason: str) -> dict:
    """Supersede an edge (PROV invalidation — never deleted). `actor` names the person or the rule."""
    return {"retracted": fabric().graph_retract(subject, predicate, object, actor=actor, reason=reason)}


@server.tool()
def semantic_trace(start: str, predicates: list[str], rungs: list[str], depth: int = 3,
                            inbound: bool = True) -> list:
    """Breadth-first over the chosen rung graphs from `start`, joined with the catalog. The rungs you choose
    ARE the trust policy of the answer; each hit carries the weakest rung on its path."""
    return fabric().graph_traverse(start, predicates, rungs=rungs, depth=depth, inbound=inbound)


@server.tool()
def semantic_impact(iri: str, depth: int = 3) -> list:
    """What a change to this artifact may have invalidated: everything reaching it over the delivery and
    reference axes on TRUSTED rungs (C·X·H·D — never S, NFR-7), joined with the catalog."""
    hits = fabric().graph_impact(iri, depth=depth)
    span().set_attribute("fabric.impact", len(hits))
    return hits


@server.tool()
def semantic_vocab_link(iri: str, terms: list[str], schemes: list[str] | None = None) -> dict:
    """Link an artifact to every reference concept whose preferred label a term matches exactly (rung X,
    method label-match). Misses are returned for semantic_vocab_propose."""
    return fabric().vocab_link(iri, terms, schemes=schemes)


@server.tool()
def semantic_vocab_propose(label: str, actor: str, definition: str = "", broader: str = "") -> dict:
    """Park a candidate concept for a steward. Not in any scheme until a person accepts it (semantic_promote
    with the candidate's IRI and no predicate)."""
    return fabric().vocab_propose(label, definition=definition, actor=actor, broader=broader)


@server.tool()
def semantic_embed(iri: str, text: str) -> dict:
    """Index an artifact by its DESCRIPTIVE text (title · type · subjects) through the gateway embedder.
    Never a body: the index proposes neighbours, it stores no content."""
    return fabric().embed(iri, text)


@server.tool()
def semantic_reindex() -> dict:
    """Embed every catalog row the current embedder's space lacks, from its facets (title · type · subjects).
    What a switched embedder costs: one call. Counts only."""
    return fabric().reindex()


@server.tool()
def semantic_similar(iri: str = "", text: str = "", limit: int = 5) -> list:
    """Nearest indexed artifacts to an indexed artifact (`iri`) or to a text, joined with the catalog and
    scored — a PROPOSAL for overlap/association, never a decision. The RAW index, withdrawn records included;
    `semantic_search` is the filtered facade."""
    return fabric().similar(iri=iri, text=text, limit=limit)


@server.tool()
def semantic_search(text: str, limit: int = 10, document_type: str = "", state: str = "") -> list:
    """The facade: similarity over the index filtered by catalog facets (document type, lifecycle state).
    Withdrawn records are hidden unless `state="withdrawn"` is asked for."""
    return fabric().search(text, limit=limit, document_type=document_type, state=state)


@server.tool()
def semantic_validate_shapes() -> dict:
    """Run the fabric's SHACL shapes over its graphs now (metadata-only, owner provenance, assertion
    completeness) — the fitness function, on demand."""
    r = fabric().validate()
    return {"conforms": r.conforms, "messages": list(r.messages)}


@server.tool()
def semantic_promote(subject: str, actor: str, method: str, predicate: str = "", object: str = "",
                     to: str = "H") -> dict:
    """A PERSON moves an assertion up the ladder (default to H): with a predicate and object, that edge;
    with the subject alone, a candidate concept is accepted. `actor` is the signed-in human — blank is refused."""
    r = fabric().promote(subject, predicate, object or None, actor=actor, method=method, to=to)
    span().set_attributes({"fabric.promoted_to": to, "fabric.from": str(r.get("from", ""))})
    return r


if __name__ == "__main__":
    boot()
    server.serve()
