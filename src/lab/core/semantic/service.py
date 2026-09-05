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
from .archimate import build as build_archimate
from .meeting import build as build_meeting
from .model_rdf import model_iri, spec_to_triples
from .ontology import Registry, SemanticStore, Vocabulary
from .reference import load_all as load_reference_models
from .skos import SKOS

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
    "concepts_under": {
        "params": ["label"],
        "doc": "Reference-model concepts under <label> (any scheme), with level and definition.",
        "sparql": """
            PREFIX skos: <http://www.w3.org/2004/02/skos/core#>  PREFIX meta: <urn:lab:semantic:meta#>
            SELECT ?scheme ?level ?concept ?definition WHERE {
              ?root skos:prefLabel ?rl . FILTER(LCASE(STR(?rl)) = LCASE("%(label)s"))
              ?c skos:broader+ ?root ; skos:prefLabel ?concept ; skos:inScheme ?s ; meta:level ?level .
              OPTIONAL { ?c skos:definition ?definition } ?s rdfs:label ?scheme .
            } ORDER BY ?scheme ?level ?concept"""},
    "shared_reference_concepts": {
        "params": [],
        "doc": "Top-level concepts that appear in more than one reference scheme (linked by skos:exactMatch).",
        "sparql": """
            PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
            SELECT ?concept ?schemeA ?schemeB WHERE {
              ?a skos:exactMatch ?b ; skos:prefLabel ?concept ; skos:inScheme ?sa . ?b skos:inScheme ?sb .
              ?sa rdfs:label ?schemeA . ?sb rdfs:label ?schemeB . FILTER(STR(?sa) < STR(?sb))
            } ORDER BY ?concept"""},
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
    def __init__(self, reference_dir=None):
        self.registry = Registry()
        self.registry.add(build_archimate())
        self.registry.add(build_meeting())      # knowledge from conversations, concept-centred
        self.schemes_ = {}
        for sc in load_reference_models(reference_dir):
            self.registry.add(sc); self.schemes_[sc.name] = sc
        self.store = SemanticStore(self.registry)
        self._link_shared_top_concepts()
        self.default = "archimate-3.1"

    # ---- reference schemes (SKOS) ----
    def _link_shared_top_concepts(self):
        """Same-label top concepts across schemes -> skos:exactMatch (both ways), in a
        dedicated mapping graph, so the schemes stay separate but queryable together."""
        from rdflib import URIRef
        g = self.store.ds.graph(URIRef("urn:lab:semantic:mappings"))
        names = sorted(self.schemes_)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                A, B = self.schemes_[a], self.schemes_[b]
                for ca in (A.concepts[c] for c in A.roots("capability")):
                    for cb in B.find(ca["label"]):
                        if cb["kind"] == "capability" and cb.get("parent") is None:
                            g.add((A.uri(ca["id"]), SKOS.exactMatch, B.uri(cb["id"])))
                            g.add((B.uri(cb["id"]), SKOS.exactMatch, A.uri(ca["id"])))

    def schemes(self):
        return [{"name": n, "title": sc.title, "source": sc.source, "counts": sc.stats()}
                for n, sc in self.schemes_.items()]

    def scheme(self, name):
        if name not in self.schemes_:
            raise KeyError(f"unknown scheme {name}; have {sorted(self.schemes_)}")
        return self.schemes_[name]

    def concepts(self, scheme, root_label=None, depth=None, kind="capability"):
        sc = self.scheme(scheme)
        root = None
        if root_label:
            hits = [c for c in sc.find(root_label) if c["kind"] == kind]
            if not hits:
                raise KeyError(f"no {kind} named '{root_label}' in {scheme}")
            root = hits[0]["id"]
        return [{k: c.get(k) for k in ("id", "label", "level", "tier", "parent", "definition")}
                for c in sc.subtree(root, depth, kind)]

    def export_archimate(self, scheme, root_label=None, depth=None, kind="capability", views="overview,branches"):
        sc = self.scheme(scheme)
        root = None
        if root_label:
            hits = [c for c in sc.find(root_label) if c["kind"] == kind]
            if not hits:
                raise KeyError(f"no {kind} named '{root_label}' in {scheme}")
            root = hits[0]["id"]
        return sc.to_archimate_spec(root, depth, kind, views)

    def vocab(self, name=None) -> Vocabulary:
        """A METAMODEL vocabulary (classes + relationship matrix). Reference schemes live in the same
        registry but are a different kind — reach them through scheme()/concepts()/export_archimate()."""
        v = self.registry.get(name or self.default)
        if not isinstance(v, Vocabulary):
            metamodels = [n for n in self.registry.names() if isinstance(self.registry.get(n), Vocabulary)]
            raise TypeError(f"{v.name} is a {v.summary()['kind']}, not a metamodel vocabulary — "
                            f"use scheme()/concepts() for reference schemes; metamodels: {metamodels}")
        return v

    def ontologies(self):
        return [self.registry.get(n).summary() for n in self.registry.names()]

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
