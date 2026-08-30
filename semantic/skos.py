"""SkosScheme — a second KIND of vocabulary in the registry: a controlled hierarchy of
concepts (capability maps, value streams, organisation/stakeholder/information maps)
rendered as SKOS, alongside metamodel vocabularies like ArchiMate.

Why SKOS: reference models are taxonomies with definitions, not metamodels — skos:broader /
narrower / prefLabel / definition is the standard shape, tooling-neutral, and keeps 1,600+
concepts out of every architecture graph until a model references them (skos:exactMatch).
`to_archimate_spec()` is the projection: any subtree becomes ArchiMate Capability /
ValueStream elements with Composition, ready for the engine and the governed ADOIT path.
"""
from __future__ import annotations

import hashlib
import re

from rdflib import RDF, RDFS, Graph, Literal, Namespace, URIRef

from .ontology import META

SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
KIND_TO_ARCHIMATE = {"capability": "Capability", "value-stream": "ValueStream",
                     "org-unit": "BusinessActor", "stakeholder": "Stakeholder",
                     "information": "BusinessObject"}


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


class SkosScheme:
    def __init__(self, name, base, title, concepts, source=None):
        """concepts: [{id, label, definition, kind, parent (id|None), level, tier, related:[ids]}]"""
        self.name, self.base, self.title, self.source = name, base, title, source
        self.concepts = {c["id"]: c for c in concepts}
        self.children = {}
        for c in concepts:
            self.children.setdefault(c.get("parent"), []).append(c["id"])

    @property
    def ns(self):
        return Namespace(self.base)

    def uri(self, cid):
        return self.ns[cid]

    # ---- data queries ----
    def roots(self, kind=None):
        return [c for c in self.children.get(None, []) if kind is None or self.concepts[c]["kind"] == kind]

    def find(self, label):
        l = label.strip().lower()
        return [c for c in self.concepts.values() if c["label"].strip().lower() == l]

    def subtree(self, root=None, depth=None, kind="capability"):
        """DFS list of concepts under root (or all roots of `kind`), limited to `depth` levels
        below the root (None = all)."""
        out = []
        def walk(cid, d):
            out.append(self.concepts[cid])
            if depth is None or d < depth:
                for k in self.children.get(cid, []):
                    walk(k, d + 1)
        starts = [root] if root else self.roots(kind)
        for s in starts:
            walk(s, 0)
        return out

    def stats(self):
        by = {}
        for c in self.concepts.values():
            by.setdefault(c["kind"], {}).setdefault(f'L{c.get("level")}', 0)
            by[c["kind"]][f'L{c.get("level")}'] += 1
        return by

    # ---- RDF ----
    def graph(self):
        g = Graph(); g.bind("skos", SKOS); g.bind("meta", META); g.bind(self.name.split("-")[0], self.ns)
        scheme = URIRef(self.base.rstrip("#/"))
        g.add((scheme, RDF.type, SKOS.ConceptScheme)); g.add((scheme, RDFS.label, Literal(self.title)))
        if self.source:
            g.add((scheme, META.source, Literal(self.source)))
        for c in self.concepts.values():
            u = self.uri(c["id"])
            g.add((u, RDF.type, SKOS.Concept)); g.add((u, SKOS.inScheme, scheme))
            g.add((u, SKOS.prefLabel, Literal(c["label"])))
            if c.get("definition"):
                g.add((u, SKOS.definition, Literal(c["definition"])))
            g.add((u, META.kind, Literal(c["kind"])))
            for k in ("level", "tier"):
                if c.get(k) is not None:
                    g.add((u, META[k], Literal(c[k])))
            if c.get("parent"):
                p = self.uri(c["parent"])
                g.add((u, SKOS.broader, p)); g.add((p, SKOS.narrower, u))
            else:
                g.add((u, SKOS.topConceptOf, scheme)); g.add((scheme, SKOS.hasTopConcept, u))
            for r in c.get("related", []):
                g.add((u, SKOS.related, self.uri(r)))
        return g

    # ---- ArchiMate projection ----
    def to_archimate_spec(self, root=None, depth=None, kind="capability", views="overview,branches",
                          row_width=8):
        """Subtree -> engine/adoit-mcp model spec: Capability (or ValueStream/...) elements with
        Composition parent->child. Views: 'overview' = top concepts in rows; 'branches' = one
        view per top concept nesting its children (capability maps nest by convention)."""
        nodes = self.subtree(root, depth, kind)
        ids = {c["id"] for c in nodes}
        atype = KIND_TO_ARCHIMATE.get(kind, "Capability")
        elements = [{"id": c["id"], "type": atype, "name": c["label"],
                     "doc": f'{self.title} · Tier {c.get("tier")} L{c.get("level")}. {c.get("definition") or ""}'.strip()}
                    for c in nodes]
        relations = [{"id": f'comp-{c["id"]}', "type": "Composition", "src": c["parent"], "tgt": c["id"]}
                     for c in nodes if c.get("parent") in ids]
        vws = []
        tops = [c for c in nodes if c.get("parent") not in ids]
        want = {v.strip() for v in views.split(",") if v.strip()}
        if "overview" in want and tops:
            rows = [[t["id"] for t in tops[i:i + row_width]] for i in range(0, len(tops), row_width)]
            vws.append({"id": f'{_slug(self.name)}-overview', "title": f"{self.title} — Capability Map (L1)",
                        "rows": rows})
        if "branches" in want:
            for t in tops:
                kids = [k for k in self.children.get(t["id"], []) if k in ids]
                if kids:
                    vws.append({"id": f'{_slug(self.name)}-{_slug(t["label"])[:40]}',
                                "title": f'{t["label"]} — L2 capabilities',
                                "elements": kids + [t["id"]],
                                "containers": [{"id": t["id"], "children": kids}]})
        plural = {"capability": "capabilities", "value-stream": "value streams", "org-unit": "organisation units",
                  "stakeholder": "stakeholders", "information": "information concepts"}.get(kind, kind)
        return {"name": f"{self.title} ({plural}" + (f" under {self.concepts[root]['label']}" if root else "") + ")",
                "id": _slug(self.name) + (f"-{_slug(self.concepts[root]['label'])[:30]}" if root else ""),
                "elements": elements, "relations": relations, "views": vws, "standard_views": False}


def concept_id(scheme_name, path):
    """Stable id from the scheme + full label path (the workbooks carry no ids)."""
    return "cap-" + hashlib.md5(f"{scheme_name}|{'/'.join(path)}".encode()).hexdigest()[:10]
