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
"""
import json
import os

from lab.core.semantic.service import SemanticService
from lab.platform import config
from lab.substrate.mcpserver import LabServer, span

SERVICE = "semantic-mcp"

server = LabServer(SERVICE, config.SEMANTIC_MCP_PORT)
S = SemanticService(reference_dir=config.REFERENCE_MODELS_DIR)   # licensed workbooks: var/reference-sources or REFERENCE_MODELS_DIR


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
def semantic_load_model(spec: dict, model_id: str, vocab: str = "archimate-3.1") -> dict:
    """Load a model into the semantic store as RDF (with derived relationships) so it can
    be queried with semantic_query / semantic_ask."""
    return S.load_model(spec, model_id, vocab)


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
    top concept. Feed the result to adoit-mcp's archimate_render + adoit_request_import: that
    is the governed way to write reference capabilities into ADOIT.
    By default the spec is stored as an artifact and only counts + spec_ref (art://…) are
    returned — the gateway meters tool payloads as tokens and adoit-mcp accepts spec_ref from
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


if __name__ == "__main__":
    server.serve()
