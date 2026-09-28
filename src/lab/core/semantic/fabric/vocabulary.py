"""The domain vocabulary the fabric OWNS — a concept scheme with ALT LABELS and TYPED relationships.

A reference scheme (`SkosScheme`) is a taxonomy: labelled concepts in a hierarchy. An ontology is that plus the
statements about how concepts relate, and those relationships are the half the fabric's derived rung needs — "A
is about X, X relates to Y, B is about Y" is only answerable if the edge carries its predicate. `skos:related`
cannot: it is one untyped, unlabelled link, so the 159 relationships become REAL predicates in the scheme's own
namespace, declared as `rdf:Property` so a reader can enumerate them.

Two decisions worth stating, both learned from the layer around this:
- **Ids come from the SOURCE.** The reference schemes mint ids by hashing a concept's label path
  (`skos.concept_id`), which is right when the source has no ids and fatal when it does: every consumer of this
  vocabulary joins on the published id, and a hash would move the day somebody fixes a typo in a label.
- **A dangling edge is refused, not dropped.** A relationship naming a concept that is not in the scheme is a
  defect in the source, and silently skipping it produces a graph that answers confidently and wrongly.

Pure: dicts in, a scheme out. Reading a workbook or a master belongs to whoever has the file.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from rdflib import RDF, Literal, Namespace, URIRef

from lab.core.semantic.ontology import META
from lab.core.semantic.skos import SKOS, SkosScheme

__all__ = ["DomainScheme", "build", "BASE"]

#: The scheme's IRI base. The VERSION is deliberately NOT in it: the reference schemes carry their version in the
#: name (`healthcare-provider-v2.0#`), which makes two versions two unrelated vocabularies with disjoint ids —
#: right for a licensed workbook nobody curates, wrong for one the fabric owns and grows, where a concept keeps
#: its identity across versions and the version is a property of the publication.
BASE = "urn:lab:semantic:domain:"


def _text(row: Mapping[str, Any], *names: str) -> str:
    for n in names:
        v = row.get(n)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _levels(concepts: dict[str, dict]) -> None:
    """Depth from the root, in place. Walks upward with a seen-set so a cycle in the source is NAMED rather than
    hanging the process that reads it."""
    for cid, c in concepts.items():
        seen, level, at = {cid}, 1, c.get("parent")
        while at:
            if at in seen:
                raise ValueError(f"the concept hierarchy has a cycle through {cid!r}")
            seen.add(at)
            level, at = level + 1, concepts[at].get("parent")
        c["level"] = level


def build(*, name: str, title: str, concepts: Iterable[Mapping[str, Any]],
          relationships: Iterable[Mapping[str, Any]] = (), source: str = "",
          version: str = "") -> "DomainScheme":
    """Source rows -> a scheme. `concepts` carry id, name, and optionally module, kind, parent, definition and
    alt; `relationships` carry subject, predicate, object and optionally cardinality and note."""
    out: dict[str, dict] = {}
    for row in concepts:
        cid = _text(row, "id")
        if not cid:
            raise ValueError(f"a concept is named by its id, and this row has none: {dict(row)!r}")
        label = _text(row, "name", "label")
        if not label:
            raise ValueError(f"concept {cid!r} has no name")
        out[cid] = {"id": cid, "label": label, "kind": _text(row, "kind") or "concept",
                    "parent": _text(row, "parent") or None, "definition": _text(row, "definition"),
                    "module": _text(row, "module"),
                    "alt": [str(a).strip() for a in (row.get("alt") or []) if str(a).strip()]}
    for cid, c in out.items():
        if c["parent"] and c["parent"] not in out:
            raise ValueError(f"concept {cid!r} names a parent the scheme does not hold: {c['parent']!r}")
    _levels(out)

    edges: list[dict] = []
    for row in relationships:
        s, p, o = _text(row, "subject"), _text(row, "predicate"), _text(row, "object")
        if not p:
            raise ValueError(f"a relationship carries a predicate, and this row has none: {dict(row)!r}")
        for end in (s, o):
            if end not in out:
                raise ValueError(f"relationship {s!r} {p} {o!r} names a concept the scheme does not hold: {end!r}")
        edges.append({"subject": s, "predicate": p, "object": o,
                      "cardinality": _text(row, "cardinality"), "note": _text(row, "note")})
    return DomainScheme(name=name, base=f"{BASE}{name}#", title=title, concepts=list(out.values()),
                        relationships=edges, source=source or None, version=version)


class DomainScheme(SkosScheme):
    """A `SkosScheme` that also knows its alt labels, its typed relationships and the version it was built at."""

    def __init__(self, name, base, title, concepts, relationships=(), source=None, version=""):
        super().__init__(name, base, title, concepts, source)
        self.version = version
        self.relationships: Sequence[dict] = list(relationships)

    # ------------------------------------------------------------------ naming

    def predicate(self, name: str) -> URIRef:
        """The IRI of one of this scheme's relationship types, in its own namespace."""
        return Namespace(f"{self.base.rstrip('#')}/rel#")[name]

    def find(self, label):
        """Concepts whose PREFERRED or ALTERNATIVE label matches, case-folded and trimmed. The reference schemes
        match the preferred label alone, which is why an intake's honest synonym lands in `missed`."""
        want = str(label).strip().casefold()
        return [c for c in self.concepts.values()
                if want in {c["label"].strip().casefold(), *(a.strip().casefold() for a in c.get("alt") or [])}]

    def resolve(self, value: str) -> str:
        """A concept id from an id, an IRI, a preferred label or an alt label. An unknown value is refused NAMING
        the choices, so the person or agent that offered it can answer again — the pattern `DocumentTypes.resolve`
        already sets for document types."""
        text = str(value).strip()
        if text in self.concepts:
            return text
        if text.startswith(self.base) and text[len(self.base):] in self.concepts:
            return text[len(self.base):]
        hits = self.find(text)
        if len(hits) == 1:
            return hits[0]["id"]
        if len(hits) > 1:
            raise ValueError(f"{value!r} matches several concepts: {', '.join(sorted(h['id'] for h in hits))}")
        labels = ", ".join(sorted(c["label"] for c in self.concepts.values())[:20])
        raise ValueError(f"{value!r} is not a concept of {self.name} — it is one of: {labels}")

    # ------------------------------------------------------------------ queries

    def relations_of(self, cid: str) -> list[tuple[str, str, str]]:
        """(predicate, the concept at the other end, "out" | "in") for everything this concept is connected to."""
        out = [(e["predicate"], e["object"], "out") for e in self.relationships if e["subject"] == cid]
        return out + [(e["predicate"], e["subject"], "in") for e in self.relationships if e["object"] == cid]

    # ---------------------------------------------------------------------- RDF

    def graph(self):
        g = super().graph()
        for c in self.concepts.values():
            u = self.uri(c["id"])
            for a in c.get("alt") or []:
                g.add((u, SKOS.altLabel, Literal(a)))
            if c.get("module"):
                g.add((u, META.module, Literal(c["module"])))
        if self.version:
            g.add((URIRef(self.base.rstrip("#/")), META.version, Literal(self.version)))
        for e in self.relationships:
            p = self.predicate(e["predicate"])
            g.add((self.uri(e["subject"]), p, self.uri(e["object"])))
            g.add((p, RDF.type, RDF.Property))
            g.add((p, SKOS.prefLabel, Literal(e["predicate"])))
            if e.get("cardinality"):
                g.add((p, META.cardinality, Literal(e["cardinality"])))
        return g
