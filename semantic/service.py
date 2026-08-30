"""SemanticService — the one facade agents (via semantic-mcp) and the skill engine use.

  ontologies()                       what vocabularies exist
  describe(type)                     classification card for a type
  classify(text)                     candidate types for a concept description
  check(src, rel, tgt)               is this relationship permitted (exact matrix)
  validate_model(spec)               every illegal relationship + semantic warnings
  load_model(spec, model_id)         model -> RDF (with derivations) into the store
  query(sparql)                      SPARQL over vocabularies + loaded models
  ask(question, **params)            named traceability questions (SPARQL templates)
"""
import os

from .archimate import build as build_archimate
from .model_rdf import model_iri, spec_to_triples
from .ontology import Registry, SemanticStore

QUESTIONS = {
    "goals_realized_by_components_on_node": {
        "params": ["node"],
        "doc": "Which goals are (transitively) realized by application components running on node <node>?",
        "sparql": """
            PREFIX am: <urn:lab:semantic:archimate#>  PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?nodeName ?component ?goal WHERE {
              ?n a am:Node ; rdfs:label ?nodeName . FILTER(CONTAINS(LCASE(?nodeName), LCASE("%(node)s")))
              { ?n am:derivedServing ?c } UNION { ?n am:serving ?c } UNION { ?n am:derivedAssignment ?c } UNION { ?n am:assignment ?c }
              ?c a am:ApplicationComponent ; rdfs:label ?component .
              { ?c am:derivedRealization ?g } UNION { ?c am:realization ?g }
              ?g a am:Goal ; rdfs:label ?goal .
            } ORDER BY ?component ?goal"""},
    "what_serves": {
        "params": ["element"],
        "doc": "What does <element> serve, directly or through derivation?",
        "sparql": """
            PREFIX am: <urn:lab:semantic:archimate#>  PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?from ?how ?to WHERE {
              ?s rdfs:label ?from . FILTER(CONTAINS(LCASE(?from), LCASE("%(element)s")))
              { ?s am:serving ?t . BIND("serving" AS ?how) } UNION { ?s am:derivedServing ?t . BIND("derived serving" AS ?how) }
              ?t rdfs:label ?to .
            } ORDER BY ?how ?to"""},
    "services_without_interface": {
        "params": [],
        "doc": "Services that are consumed but not exposed through an interface assigned to them (strict ArchiMate: an interface is the access point of a service).",
        "sparql": """
            PREFIX am: <urn:lab:semantic:archimate#>  PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT DISTINCT ?service ?type WHERE {
              ?s a ?t ; rdfs:label ?service . FILTER(STRENDS(STR(?t), "Service"))
              ?s am:serving ?consumer .
              FILTER NOT EXISTS { ?i am:assignment ?s . ?i a ?it . FILTER(STRENDS(STR(?it), "Interface")) }
              BIND(REPLACE(STR(?t), ".*#", "") AS ?type)
            } ORDER BY ?service"""},
    "elements_by_layer_aspect": {
        "params": [],
        "doc": "Every model element with its layer and aspect from the vocabulary — the classification audit.",
        "sparql": """
            PREFIX am: <urn:lab:semantic:archimate#>  PREFIX meta: <urn:lab:semantic:meta#>  PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?layer ?aspect ?type ?element WHERE {
              ?e a ?t ; rdfs:label ?element ; meta:id ?id . ?t meta:layer ?l ; meta:aspect ?a .
              ?l rdfs:label ?layer . ?a rdfs:label ?aspect . BIND(REPLACE(STR(?t), ".*#", "") AS ?type)
            } ORDER BY ?layer ?aspect ?type ?element"""},
}


class SemanticService:
    def __init__(self):
        self.registry = Registry()
        self.registry.add(build_archimate())
        self.store = SemanticStore(self.registry)
        self.default = "archimate-3.1"

    def vocab(self, name=None):
        return self.registry.get(name or self.default)

    def ontologies(self):
        return [{"name": n, "classes": len(self.registry.get(n).classes),
                 "relations": len(self.registry.get(n).relations),
                 "permitted_pairs": len(self.registry.get(n).permitted)} for n in self.registry.names()]

    def describe(self, t, vocab=None):
        return self.vocab(vocab).describe(t)

    def classify(self, text, vocab=None, limit=5):
        return self.vocab(vocab).classify(text, limit)

    def check(self, src, rel, tgt, vocab=None):
        return self.vocab(vocab).check(src, rel, tgt)

    def validate_model(self, spec, vocab=None):
        v = self.vocab(vocab); types = {e["id"]: e["type"] for e in spec["elements"]}
        illegal, warnings = [], []
        for i, r in enumerate(spec.get("relations", [])):
            st, tt = types.get(r["src"]), types.get(r["tgt"])
            if st is None or tt is None:
                illegal.append({"relation": r, "reason": "endpoint not declared"}); continue
            c = v.check(st, r["type"], tt)
            if not c["ok"]:
                illegal.append({"id": r.get("id") or f"r{i+1}", "source": r["src"], "relation": r["type"],
                                "target": r["tgt"], "types": f"{st} -> {tt}", "allowed": c["allowed"]})
        # semantic (not matrix) warnings: interface = access point of a service
        served = {r["src"] for r in spec.get("relations", []) if r["type"] == "Serving"}
        exposed = {r["tgt"] for r in spec.get("relations", []) if r["type"] == "Assignment"
                   and types.get(r["src"], "").endswith("Interface")}
        for eid in sorted(served):
            if types.get(eid, "").endswith("Service") and eid not in exposed:
                warnings.append(f"{eid} ({types[eid]}) is consumed but no Interface is assigned to it — "
                                f"add the access point (channel / API / port) and assign it to the service")
        for r in spec.get("relations", []):
            if types.get(r["src"], "").endswith("Interface") and r["type"] == "Serving":
                warnings.append(f"{r['src']}: interfaces expose services (Assignment interface->service); "
                                f"Serving from an interface usually means the service relationship is missing")
        return {"illegal": illegal, "warnings": warnings,
                "elements": len(spec["elements"]), "relations": len(spec.get("relations", []))}

    def load_model(self, spec, model_id, vocab=None):
        v = self.vocab(vocab)
        triples = spec_to_triples(spec, v, model_id)
        n = self.store.load_model(model_iri(model_id), triples)
        derived = sum(1 for _, p, _ in triples if "derived" in str(p))
        return {"model": model_iri(model_id), "triples": n, "derived_relations": derived}

    def query(self, sparql, limit=200):
        return self.store.query(sparql, limit)

    def ask(self, question, **params):
        q = QUESTIONS.get(question)
        if not q:
            raise KeyError(f"unknown question; have {sorted(QUESTIONS)}")
        missing = [p for p in q["params"] if p not in params]
        if missing:
            raise ValueError(f"missing params {missing}")
        return {"question": q["doc"] % params if params else q["doc"], **self.query(q["sparql"] % params)}

    def questions(self):
        return {k: {"params": v["params"], "doc": v["doc"]} for k, v in QUESTIONS.items()}

    def export_ttl(self, outdir):
        os.makedirs(outdir, exist_ok=True)
        paths = []
        for name in self.registry.names():
            p = os.path.join(outdir, f"{name}.ttl"); self.registry.get(name).graph().serialize(p, format="turtle"); paths.append(p)
        return paths
