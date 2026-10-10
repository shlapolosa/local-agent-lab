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
import asyncio
import json
from datetime import datetime, timezone
import os

from lab.core.semantic.fabric.service import FabricService
from lab.core.semantic.service import SemanticService
from lab.core import ids
from lab.platform import config, workflows
from lab.substrate import container
from lab.platform.contracts import ARTIFACT_INTAKE
from lab.core.viz import CONCEPT
from lab.platform.filetypes import content_type_for, file_slug
from lab.platform.fabric_events import METRICS_KEY
from lab.platform.filetypes import content_type_for
from lab.substrate import fabric_publication
from lab.substrate.mcp.semantic import views, vocab_seed
from lab.substrate.mcp.semantic.rung_store import RungStore
from lab.substrate.mcpserver import LabServer, span

SERVICE = "semantic-mcp"

server = LabServer(SERVICE, config.SEMANTIC_MCP_PORT)
views.register(server)                    # the CAFÉ views, one per step (views.py)


def reference_dir(refs=config.REFERENCE_MODELS_REFS, directory=config.REFERENCE_MODELS_DIR,
                  prefix="reference-models-") -> str:
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
    out = Path(tempfile.mkdtemp(prefix=prefix))
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


def boot() -> dict[str, object]:
    """Compose the fabric from the container, apply the catalog's schema, restore the persisted rung graphs.
    Part of STARTING, not of importing — `__main__` calls it before `serve`, a test after its overrides."""
    global F
    # The domain vocabulary the fabric OWNS, seeded from its master. Here and not at import for the same reason
    # the fabric itself is: materialising it needs the artifact store, which is a client. A deployment without
    # the master keeps every other tool working and says it has no domain scheme.
    seed = vocab_seed.load(reference_dir(config.FABRIC_VOCAB_REFS, config.FABRIC_VOCAB_DIR, "fabric-vocabulary-"),
                           version=config.FABRIC_VOCAB_VERSION)
    if seed is not None:
        S.add_scheme(seed)
    catalog = server.container.catalog()
    F = FabricService(S.store.ds, catalog, S.doc_types, schemes=lambda: S.schemes_,
                      embedder=server.container.embedder(),
                      on_write=lambda names: RUNGS.save(F, names))
    if hasattr(catalog, "ensure_schema"):
        catalog.ensure_schema()
    restored = RUNGS.restore(F)
    # The seed was just rebuilt from its master, so the scheme object knows nothing a steward decided. The
    # curated graph is restored ABOVE, so replaying it here is what makes admission survive a restart —
    # without this line curation is durable and invisible, which is the worse of the two failures.
    curated = F.recurate()
    if any(curated.values()):
        print(f"[fabric] vocabulary curation replayed: {curated}", flush=True)
    return {**restored, "curation": curated}


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
    """Concepts of a scheme: the whole vocabulary, or the subtree under `root_label` (e.g. 'Patient Management')
    to `depth` levels. Kinds in a capability map: capability, value-stream, org-unit, stakeholder, information.
    Pass an EMPTY kind for every kind at once, which is what a domain ontology needs — its concepts are entities,
    references and events, and asking for one of them would silently return part of the vocabulary."""
    return S.concepts(scheme, root_label, depth, kind or None)


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
def semantic_catalog_list(after: str = "", limit: int = 100, state: str = "") -> dict:
    """One page of the catalogue in IRI order — {items:[{iri,title,document_type,state,pointer,…}], cursor,
    more}. Pass `cursor` straight back as `after` to continue; never compose one yourself.

    KEYSET, not offset: rows are added while a long walk runs, so an offset would silently skip or repeat
    records. `state` narrows to one lifecycle state and refuses one that does not exist, because a typo
    returning an empty page is the one answer an operator would act on wrongly. Metadata only, as ever."""
    rows = fabric().catalog_page(after=after, limit=limit, state=state)
    return {"items": [r.to_dict() for r in rows], "cursor": rows[-1].iri if rows else "",
            "more": len(rows) == max(1, int(limit))}


@server.tool()
def semantic_catalog_reclassify(iri: str) -> dict:
    """Re-read ONE catalogued artifact with today's classifier — {request_id, duplicate, pointer}.

    You name a record; you supply NOTHING else. The pointer, the producing process and the delivery
    context all come from the row the fabric itself recorded, so this cannot introduce an input the lab
    has not already validated. That is what makes it legitimate for a process whose `submit` deliberately
    does not exist (`ARTIFACT_INTAKE.external = False` — the ArtifactChanged event IS the provenance of
    everything a normal run records), and it is the same argument `workflow_replay` makes: a caller may
    ask that inputs already accepted be used again, never supply new ones.

    The run carries `reason=reclassify`, so it re-links the subjects and asks NOBODY unless the record
    gains a document type — re-reading a back catalogue must not raise a second card for every record
    whose first one is still open.

    An artifact whose pointer names nothing is refused rather than submitted: intake reads the artifact
    THROUGH its pointer, so a row without one is not a thing that can be re-read, and spending a run to
    discover that would read as a classifier fault rather than a catalogue one.
    """
    row = fabric().catalog_get(iri)
    if not row:
        raise ValueError(f"no catalogued artifact {iri!r}")
    pointer = row.get("pointer") or {}
    if not pointer.get("source") or not (pointer.get("ref") or pointer.get("handle")):
        raise ValueError(f"{iri} has no pointer that can be re-read: {pointer!r}")
    request_id, duplicate = workflows.submit(
        ARTIFACT_INTAKE.name,
        {"pointer": pointer, "event_id": ids.ulid(), "reason": "reclassify",
         "produced_by": row.get("produced_by") or "", "context": row.get("context") or ""},
        SERVICE, client=server.container.redis())
    span().set_attributes({"fabric.reclassify.iri": iri, "workflow.request_id": request_id})
    return {"request_id": request_id, "duplicate": duplicate, "pointer": pointer}


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
    """Assert a classified facet (document_type | owner | sensitivity_label | projection_url) at a provenance
    rung: the row's column AND the graph triple with its PROV record. Owner and label are refused anywhere
    but C (NFR-3)."""
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
def semantic_vocab_propose(label: str, actor: str, definition: str = "", broader: str = "",
                           scheme: str = "", concept_id: str = "", module: str = "") -> dict:
    """Park a candidate concept for a steward. Not in any scheme until a person accepts it (semantic_promote
    with the candidate's IRI and no predicate), at which point it IS admitted and findable from then on.
    `scheme` is the vocabulary it would join and `concept_id` the id it would take — the steward supplies
    whichever is missing at the gate, because a concept with no home cannot be looked up."""
    return fabric().vocab_propose(label, definition=definition, actor=actor, broader=broader,
                                  scheme=scheme, concept_id=concept_id, module=module)


@server.tool()
def semantic_vocab_retire(concept_id: str, scheme: str, resolves_to: str, actor: str, reason: str = "") -> dict:
    """Supersede a concept: it stops being offered to classifiers and keeps RESOLVING to the one that replaced
    it. Never deleted — a link made last month names the old id, and a lookup that fails on it turns a correct
    historical statement into a dangling one. `actor` is the signed-in human; blank is refused."""
    return fabric().vocab_retire(concept_id, scheme=scheme, resolves_to=resolves_to, actor=actor, reason=reason)


@server.tool()
def semantic_vocab_amend(concept_id: str, scheme: str, alt: str, actor: str, reason: str = "") -> dict:
    """Teach a concept the vocabulary ALREADY holds another name, so the next document using that term is
    linked instead of proposing the same candidate again. The steward's answer to "this term has no concept"
    when it does, under a different name — admitting a second would be the duplicate this prevents."""
    return fabric().vocab_amend(concept_id, scheme=scheme, alt=alt, actor=actor, reason=reason)


@server.tool()
def semantic_vocab_master(scheme: str, owner: str = "ea@doh", version: str = "") -> dict:
    """Render the vocabulary as its human-readable MASTER and store it by reference — what an operator then
    signs and publishes into the governed corpus.

    Returns {artifact_id: {ref, name, rows, command}}. It stages; it does not publish, and it cannot: the
    signing seed is off every service by design and the corpus reader holds SELECT only. The `command` is the
    exact line to run. The master is the SOURCE — the publisher hashes this text and derives its records from
    parsing it, so `derived_from = master_sha256` is mechanical rather than a promise."""
    sc = S.scheme(scheme)
    return asyncio.run(fabric_publication.stage(sc, call=_local_store, owner=owner, version=version))


async def _local_store(calls):
    """The staging transport, in-process: this server already holds the artifact store, so a master does not
    make a round trip through the gateway to come back to the process that rendered it."""
    return [{"ref": server.artifacts().put(a["name"], a["text"].encode("utf-8"), "text/markdown"),
             "name": a["name"]} for _, a in calls]


@server.tool()
def semantic_vocab_candidates() -> list:
    """Terms a run met that the vocabulary has no concept for and nobody has accepted or declined yet — what
    a steward is asked to admit, place under another name, or decline."""
    return fabric().vocab_candidates()


@server.tool()
def semantic_vocab_conflicts() -> list:
    """Words this vocabulary gives more than one meaning, which no document could therefore be linked to.
    A steward settles each by retiring one meaning or renaming it; until then the link is not made, because
    linking to both is worse than linking to neither."""
    return fabric().vocab_conflicts()


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
def semantic_derive() -> dict:
    """Rebuild the DERIVED rung (D) from the trusted rungs: an artifact is related to the context of what it
    references; a record synthesised from minutes inherits their context. Counts only; impact reads D."""
    return fabric().derive()


@server.tool()
def semantic_metrics() -> dict:
    """The fabric's published measurements (BR-8), as last computed by the reconciler's tick: auto-association
    ratio, drafts approved without rewrite, impact notices acknowledged, duplicate rate, labelled and owned
    share — each with its numerator and denominator. Numbers, never content."""
    raw = server.container.redis().get(METRICS_KEY)
    if not raw:
        return {"note": "not computed yet — the reconciler computes on its sweep tick"}
    m = json.loads(raw)
    try:                                   # how old the numbers are, so a reader never mistakes a stale page for now
        computed = datetime.fromisoformat(m["computed_at"])
        m["age_seconds"] = max(0, int((datetime.now(timezone.utc) - computed).total_seconds()))
    except (KeyError, ValueError):
        m["age_seconds"] = None
    return m


@server.tool()
def semantic_recommend(text: str, limit: int = 5) -> list:
    """Before you create a document: the PUBLISHED records already on this topic, each with its owner and source
    pointer — reuse or ask instead of writing a twin. Never content."""
    return fabric().recommend(text, limit=limit)


@server.tool()
def semantic_store_page(text: str, name: str) -> dict:
    """Store a text document (Markdown, HTML) in the artifact store AS ITSELF and return its art:// ref.

    The sibling of `semantic_store_spec`, and not the same tool: a spec is JSON and is stored as JSON, while a
    page must arrive at its reader byte for byte — `{"text": "# Title"}` written into a wiki is a file nobody
    can read. The content type comes from the NAME, so a caller cannot mislabel its own file."""
    if not str(text or "").strip():
        raise ValueError("a page has content")
    filename = str(name or "").strip().rsplit("/", 1)[-1]
    if "." not in filename:
        raise ValueError(f"a page's name carries its extension, which is what types it: {name!r}")
    ref = server.artifacts().put(filename, text.encode("utf-8"), content_type_for(filename, "text/plain"))
    span().set_attributes({"semantic.page_ref": ref, "semantic.page_bytes": len(text.encode("utf-8"))})
    return {"ref": ref, "name": filename, "bytes": len(text.encode("utf-8"))}


@server.tool()
def semantic_topology(iri: str, ontology_ring: bool = True, proposed: list[str] | None = None) -> dict:
    """Draw what this record is about and what that connects it to, AS THE GRAPH STANDS NOW, and store the
    drawing — returns {ref, name, media_type, suffix, nodes, edges, concepts, statuses, title}.

    The drawing is named in the RENDERER's own terms (`suffix`, `media_type`) and never as HTML: which adapter
    draws is configuration (`FABRIC_RENDERER`), so a caller that assumed a page would break the day a raster or
    an interactive one is configured — the one change the renderer registry exists to make free.

    Every call rebuilds the view from the catalogue and the vocabulary, so a picture is never older than the
    knowledge; there is no stored layout to go stale. The colour of each box is the RUNG the link was made at,
    so the drawing answers how the fabric knows what it claims and not merely what it claims. `proposed` are
    terms the record used that the vocabulary has no concept for — drawn as gaps, because a gap a person can
    see is one a steward can close. Reading only: it writes an artifact, never the graph."""
    view = fabric().topology(iri, ontology_ring=ontology_ring, proposed=proposed or [],
                             as_of=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    out = server.container.renderer().render(view)
    name = f"{file_slug(view.title)}.topology{out.suffix}"
    ref = server.artifacts().put(name, out.content, out.media_type)
    span().set_attributes({"fabric.topology.nodes": len(view.nodes), "fabric.topology.edges": len(view.edges)})
    return {"ref": ref, "name": name, "media_type": out.media_type, "suffix": out.suffix,
            "nodes": len(view.nodes), "edges": len(view.edges), "title": view.title,
            "concepts": [n.label for n in view.nodes if n.kind == CONCEPT], "statuses": list(view.statuses)}


@server.tool()
def semantic_view_corpus(state: str = "", limit: int = 2000) -> dict:
    """Draw the WHOLE catalogue — every record that is about something, the concepts they share, and the
    vocabulary's own edges between those — and store the drawing. Returns the same shape as
    `semantic_topology` plus `records`/`silent`.

    The question it answers is the one no per-record picture can: what is our knowledge ABOUT, and what is
    it silent on. Resolved in process, deliberately — a caller walking the catalogue over the gateway pays
    a round trip per record and trips its own rate limit at about sixty.

    `state` narrows to one lifecycle state (an unknown one is refused, so a typo never reads as "nothing
    matched"); `limit` caps records READ. What is DRAWN is the view's decision: a record about nothing has
    no edge, so it is counted in the subtitle rather than left on the rim saying nothing. Reading only."""
    view = fabric().corpus_view(state=state, limit=limit,
                                as_of=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    # Its OWN adapter (`FABRIC_CORPUS_RENDERER`), not the one a record's view uses: a focusless picture
    # drawn in rings puts every node on one circle. Still chosen by configuration, never imported here.
    out = container.graph_renderer(config.FABRIC_CORPUS_RENDERER).render(view)
    name = f"{file_slug(view.title)}{out.suffix}"
    ref = server.artifacts().put(name, out.content, out.media_type)
    concepts = [n.label for n in view.nodes if n.kind == CONCEPT]
    span().set_attributes({"fabric.corpus.nodes": len(view.nodes), "fabric.corpus.edges": len(view.edges),
                           "fabric.corpus.concepts": len(concepts)})
    return {"ref": ref, "name": name, "media_type": out.media_type, "suffix": out.suffix,
            "nodes": len(view.nodes), "edges": len(view.edges), "records": len(view.nodes) - len(concepts),
            "concepts": concepts, "statuses": list(view.statuses), "title": view.title,
            "subtitle": view.subtitle}


@server.tool()
def semantic_vocab_decline(candidate: str, actor: str, reason: str = "") -> dict:
    """Record a STEWARD'S NO about a candidate term, so nobody is asked about it again.

    The decline used to live only on the approval, while the reconciler's "already asked" memory is a set in
    the PROCESS — so every restart re-asked every still-open candidate with a fresh approval id. Measured
    10 Oct 2026: the open concept-admission cards went from 71 to 101 in one afternoon while a steward
    decided nothing. A person's answer has to outlive the process that heard it.

    `actor` is the person, never an agent name — this is a decision about what the fabric will mean for every
    document classified from now on. The term may be met again; it will not be asked about again."""
    out = fabric().vocab_decline(candidate, actor=actor, reason=reason)
    span().set_attributes({"fabric.candidate": candidate})
    return out


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
