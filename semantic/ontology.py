"""Generic ontology core: a Vocabulary is data (classes with a taxonomy, relation types,
permitted source→target→relation triples, definitions) rendered into an RDF graph; the
Registry holds many; the SemanticStore holds vocabularies + instance models as named
graphs and answers SPARQL over all of them.

Why RDF rather than a bespoke graph: standards semantics (rdfs:subClassOf hierarchies for
classification, owl:ObjectProperty for relation types), a query language agents already
know (SPARQL), and interoperability with enterprise ontology tooling later — with no
server to run today.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rdflib import OWL, RDF, RDFS, BNode, Dataset, Graph, Literal, Namespace, URIRef

META = Namespace("urn:lab:semantic:meta#")   # cross-vocabulary meta terms (layer, aspect, permits…)


@dataclass
class Vocabulary:
    name: str                      # registry key, e.g. "archimate-3.1"
    base: str                      # IRI base, e.g. "urn:lab:semantic:archimate#"
    classes: dict = field(default_factory=dict)      # Type -> {layer, aspect, definition, examples, parents:[...]}
    relations: dict = field(default_factory=dict)    # relType -> {definition, direction}
    permitted: dict = field(default_factory=dict)    # (srcType, tgtType) -> set(relType)
    facets: dict = field(default_factory=dict)       # facet name -> {value -> definition} (e.g. layer, aspect)
    rules: list = field(default_factory=list)        # prose modelling rules (agent guidance)

    @property
    def ns(self) -> Namespace:
        return Namespace(self.base)

    def cls(self, t: str) -> URIRef:
        return self.ns[t]

    def rel(self, r: str) -> URIRef:
        return self.ns[r[0].lower() + r[1:]]

    # ---- questions agents ask, answered from data ----
    def describe(self, t: str) -> dict:
        c = self.classes.get(t)
        if not c:
            raise KeyError(f"{t} is not a {self.name} type")
        return {"type": t, **c}

    def allowed(self, src: str, tgt: str) -> set:
        return set(self.permitted.get((src, tgt), ()))

    def check(self, src: str, rel: str, tgt: str) -> dict:
        ok = rel in self.allowed(src, tgt)
        return {"ok": ok, "source": src, "relation": rel, "target": tgt,
                "allowed": sorted(self.allowed(src, tgt))}

    def classify(self, text: str, limit: int = 5) -> list:
        """Keyword scoring over names, definitions, examples, facets — a deterministic
        candidate list for the agent to decide from (the decision stays with the agent)."""
        import re
        words = {w for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) > 2}
        out = []
        for t, c in self.classes.items():
            if c.get("matrix_only"):
                continue
            name_words = set(re.findall(r"[a-z]+", re.sub(r"(?<!^)(?=[A-Z])", " ", t).lower()))
            ex = " ".join(c.get("examples", [])).lower()
            definition = (c.get("definition") or "").lower()
            score = (5 * len(words & name_words)
                     + 3 * sum(1 for w in words if w in ex)
                     + 1 * sum(1 for w in words if w in definition))
            if score:
                out.append((score, t))
        return [{"type": t, "score": s, **self.classes[t]} for s, t in sorted(out, reverse=True)[:limit]]

    # ---- RDF rendering ----
    def graph(self) -> Graph:
        g = Graph(); ns = self.ns
        g.bind("meta", META); g.bind(self.name.split("-")[0], ns)
        vocab = URIRef(self.base.rstrip("#/"))
        g.add((vocab, RDF.type, OWL.Ontology)); g.add((vocab, RDFS.label, Literal(self.name)))
        for facet, values in self.facets.items():
            fcls = META[facet.capitalize()]
            g.add((fcls, RDF.type, OWL.Class))
            for v, definition in values.items():
                node = META[f"{facet}-{v}"]
                g.add((node, RDF.type, fcls)); g.add((node, RDFS.label, Literal(v)))
                if definition:
                    g.add((node, RDFS.comment, Literal(definition)))
                fac_cls = ns[f"{facet.capitalize()}_{v}"]          # e.g. archimate:Aspect_active
                g.add((fac_cls, RDF.type, OWL.Class)); g.add((fac_cls, RDFS.label, Literal(f"{facet} {v}")))
        for t, c in self.classes.items():
            u = self.cls(t)
            g.add((u, RDF.type, OWL.Class)); g.add((u, RDFS.label, Literal(t)))
            if c.get("definition"):
                g.add((u, RDFS.comment, Literal(c["definition"])))
            for facet in self.facets:
                if c.get(facet):
                    g.add((u, META[facet], META[f"{facet}-{c[facet]}"]))
                    g.add((u, RDFS.subClassOf, ns[f"{facet.capitalize()}_{c[facet]}"]))
            for p in c.get("parents", []):
                g.add((u, RDFS.subClassOf, self.cls(p)))
            for ex in c.get("examples", []):
                g.add((u, META.example, Literal(ex)))
            if c.get("confusable_with"):
                g.add((u, META.confusableWith, Literal(c["confusable_with"])))
        for r, c in self.relations.items():
            p = self.rel(r)
            g.add((p, RDF.type, OWL.ObjectProperty)); g.add((p, RDFS.label, Literal(r)))
            if c.get("definition"):
                g.add((p, RDFS.comment, Literal(c["definition"])))
        for (s, t), rels in self.permitted.items():
            for r in rels:
                b = BNode()
                g.add((b, RDF.type, META.Permission)); g.add((b, META.source, self.cls(s)))
                g.add((b, META.target, self.cls(t))); g.add((b, META.relation, self.rel(r)))
        for i, rule in enumerate(self.rules):
            g.add((vocab, META.rule, Literal(f"{i+1}. {rule}")))
        return g


class Registry:
    def __init__(self):
        self._v: dict[str, Vocabulary] = {}

    def add(self, v: Vocabulary):
        self._v[v.name] = v; return v

    def get(self, name: str) -> Vocabulary:
        if name not in self._v:
            raise KeyError(f"unknown vocabulary {name}; have {sorted(self._v)}")
        return self._v[name]

    def names(self):
        return sorted(self._v)


class SemanticStore:
    """Vocabularies + instance models as named graphs in one dataset; SPARQL over all.
    In-memory today; swap the Dataset for a persistent rdflib store later without changing
    callers."""

    def __init__(self, registry: Registry):
        self.registry = registry
        self.ds = Dataset(default_union=True)   # SPARQL sees vocabularies + models, not just the default graph
        self.ds.bind("meta", META)
        for name in registry.names():
            v = registry.get(name)
            g = self.ds.graph(URIRef(f"urn:lab:semantic:vocab:{name}"))
            for t in v.graph():
                g.add(t)
            self.ds.bind(name.split("-")[0], v.ns)

    def load_model(self, model_iri: str, triples, replace=True) -> int:
        g = self.ds.graph(URIRef(model_iri))
        if replace:
            g.remove((None, None, None))
        for t in triples:
            g.add(t)
        return len(g)

    def models(self):
        return sorted(str(g.identifier) for g in self.ds.graphs()
                      if str(g.identifier).startswith("urn:lab:semantic:model:"))

    def query(self, sparql: str, limit: int = 200) -> dict:
        res = self.ds.query(sparql)
        cols = [str(v) for v in res.vars] if res.vars else []
        rows = []
        for r in res:
            rows.append([self._short(x) for x in r])
            if len(rows) >= limit:
                break
        return {"columns": cols, "rows": rows, "count": len(rows)}

    @staticmethod
    def _short(x):
        if x is None:
            return None
        s = str(x)
        if isinstance(x, URIRef):
            return s.rsplit("#", 1)[-1] if "#" in s else s.rsplit("/", 1)[-1]
        return s
