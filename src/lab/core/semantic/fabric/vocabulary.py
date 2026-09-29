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
from rdflib.namespace import DCTERMS

from lab.core.semantic.ontology import META
from lab.core.semantic.skos import SKOS, SkosScheme

__all__ = ["DomainScheme", "build", "BASE"]

#: The scheme's IRI base. The VERSION is deliberately NOT in it: the reference schemes carry their version in the
#: name (`healthcare-provider-v2.0#`), which makes two versions two unrelated vocabularies with disjoint ids —
#: right for a licensed workbook nobody curates, wrong for one the fabric owns and grows, where a concept keeps
#: its identity across versions and the version is a property of the publication.
BASE = "urn:lab:semantic:domain:"


#: the columns `build` interprets; anything else on a row is carried through untouched as `extra`
MODELLED = ("id", "name", "label", "kind", "parent", "definition", "module", "alt")


def _text(row: Mapping[str, Any], *names: str) -> str:
    for n in names:
        v = row.get(n)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _level_of(cid: str, concepts: Mapping[str, dict]) -> int:
    """Depth from the root. Walks upward with a seen-set so a cycle in the source is NAMED rather than hanging
    the process that reads it."""
    seen, level, at = {cid}, 1, concepts[cid].get("parent")
    while at:
        if at in seen:
            raise ValueError(f"the concept hierarchy has a cycle through {cid!r}")
        seen.add(at)
        level, at = level + 1, concepts[at].get("parent")
    return level


def _levels(concepts: dict[str, dict]) -> None:
    """Depth from the root, for every concept, in place."""
    for cid, c in concepts.items():
        c["level"] = _level_of(cid, concepts)


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
                    "alt": [str(a).strip() for a in (row.get("alt") or []) if str(a).strip()],
                    # Everything the fabric does not model, kept verbatim. It becomes the MASTER of this
                    # vocabulary, so a column it cannot interpret must survive the round trip rather than be
                    # lost the first time it publishes: the real master carries seven of them.
                    "extra": {k: str(v).strip() for k, v in row.items()
                              if k not in MODELLED and str(v or "").strip()}}
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
        """Concepts matching an ID, a PREFERRED label or an ALTERNATIVE label, case-folded and trimmed.

        An exact id wins outright and alone: the classifier is shown these concepts and answers with their ids,
        and were another concept's label to equal this id, returning both would link a document to something it
        was never about. The reference schemes match the preferred label only, which is why an intake's honest
        synonym lands in `missed` rather than on a concept."""
        text = str(label).strip()
        if text in self.concepts:
            # a retired id included: `find` OFFERS live meanings, `resolve` answers about any reference ever
            # made. Offering a retired concept here is how a steward's retirement gets undone by the next run.
            return [self.concepts[text]] if not self.concepts[text].get("retired") else []
        want = text.casefold()
        # `live()`, not `concepts`: a retired term must stop being offered, or the classifier keeps making the
        # link a steward has just retired and the vocabulary grows its own duplicates back.
        return [c for c in self.live()
                if want in {c["label"].strip().casefold(), *(a.strip().casefold() for a in c.get("alt") or [])}]

    def resolve(self, value: str) -> str:
        """A concept id from an id, an IRI, a preferred label or an alt label. An unknown value is refused NAMING
        the choices, so the person or agent that offered it can answer again — the pattern `DocumentTypes.resolve`
        already sets for document types."""
        text = str(value).strip()
        if text in self.concepts:
            return self._live_id(text)
        if text.startswith(self.base) and text[len(self.base):] in self.concepts:
            return self._live_id(text[len(self.base):])
        hits = self.find(text)
        if len(hits) == 1:
            return hits[0]["id"]
        if len(hits) > 1:
            raise ValueError(f"{value!r} matches several concepts: {', '.join(sorted(h['id'] for h in hits))}")
        labels = ", ".join(sorted(c["label"] for c in self.concepts.values())[:20])
        raise ValueError(f"{value!r} is not a concept of {self.name} — it is one of: {labels}")

    def _live_id(self, cid: str) -> str:
        """A retired concept answers with the one that replaced it, so a link made before the retirement still
        lands somewhere true. One hop by construction: `retire` refuses a successor that is itself retired."""
        return str(self.concepts[cid].get("resolves_to") or cid)

    # ------------------------------------------------------------------ curation

    def admit(self, *, id: str, label: str, definition: str = "", parent: str | None = None, module: str = "",
              alt: Iterable[str] = (), extra: Mapping[str, Any] | None = None) -> dict:
        """Put a concept INTO the vocabulary, so `find` returns it from now on.

        This is what makes admission real rather than symbolic: a candidate accepted without this is a
        lifecycle triple on a concept that no lookup can reach, and the same term is proposed again the next
        time a document uses it. A curated concept is marked as such — it is the delta the fabric publishes,
        and it must be separable from the seed it was grown onto."""
        cid = str(id or "").strip()
        if not cid:
            raise ValueError("a concept is named by its id, and none was given")
        if cid in self.concepts:
            raise ValueError(f"{self.name} already holds a concept {cid!r} — retire it or amend it, "
                             "never admit a second under the same id")
        text = str(label or "").strip()
        if not text:
            raise ValueError(f"concept {cid!r} has no label, and a label is what a person recognises it by")
        parent = str(parent or "").strip() or None
        if parent and parent not in self.concepts:
            raise ValueError(f"concept {cid!r} names a parent the scheme does not hold: {parent!r}")
        c = {"id": cid, "label": text, "kind": "concept", "parent": parent, "definition": str(definition or ""),
             "module": str(module or ""), "alt": [str(a).strip() for a in alt if str(a).strip()],
             "extra": {k: str(v).strip() for k, v in (extra or {}).items() if str(v or "").strip()},
             "curated": True}
        self.concepts[cid] = c
        c["level"] = _level_of(cid, self.concepts)
        return c

    def retire(self, cid: str, *, resolves_to: str, reason: str = "") -> dict:
        """Supersede a concept: it stops being offered, and keeps resolving to the one that replaced it.

        NEVER deleted. A link made last month names the old id, and a lookup that fails on it turns a correct
        historical statement into a dangling one — while silently dropping it turns the statement into one the
        fabric never made."""
        cid, to = str(cid or "").strip(), str(resolves_to or "").strip()
        if cid == to:
            raise ValueError(f"{cid!r} cannot be replaced by itself")
        for end in (cid, to):
            if end not in self.concepts:
                raise ValueError(f"{self.name} does not hold a concept {end!r}")
        if self.concepts[to].get("retired"):
            # a chain a reader would have to walk, and the next retirement would lengthen it
            raise ValueError(f"{to!r} is itself retired (it resolves to "
                             f"{self.concepts[to].get('resolves_to')!r}) — name the concept that is live")
        c = self.concepts[cid]
        c.update(retired=True, resolves_to=to, retired_reason=str(reason or ""), curated=True)
        return c

    def amend(self, cid: str, *, alt: str) -> dict:
        """Teach an existing concept another name. The commonest answer to "this term has no concept" is that
        it does, under a different one — and admitting a second concept for it would be exactly the duplicate
        the vocabulary exists to prevent."""
        cid, text = str(cid or "").strip(), str(alt or "").strip()
        if cid not in self.concepts:
            raise ValueError(f"{self.name} does not hold a concept {cid!r}")
        if not text:
            raise ValueError("an amendment adds a name, and none was given")
        c = self.concepts[cid]
        if c.get("retired"):
            raise ValueError(f"{cid!r} is retired (it resolves to {c.get('resolves_to')!r}) — name the live concept")
        known = {a.casefold() for a in c.get("alt") or []} | {c["label"].casefold()}
        if text.casefold() not in known:
            c.setdefault("alt", []).append(text)
            c["curated"] = True
        return c

    def live(self) -> list[dict]:
        """The concepts a classifier may choose from — everything not retired."""
        return [c for c in self.concepts.values() if not c.get("retired")]

    def curated(self) -> list[dict]:
        """What this scheme has grown since its seed — what a publication writes as the delta."""
        return [c for c in self.concepts.values() if c.get("curated")]

    # ------------------------------------------------------------------ queries

    def relations_of(self, cid: str) -> list[tuple[str, str, str]]:
        """(predicate, the concept at the other end, "out" | "in") for everything this concept is connected to."""
        out = [(e["predicate"], e["object"], "out") for e in self.relationships if e["subject"] == cid]
        return out + [(e["predicate"], e["subject"], "in") for e in self.relationships if e["object"] == cid]

    def rows(self) -> list[dict]:
        """The scheme back in the master's own shape — what a publication writes. The inverse of `build`, so a
        column the fabric never modelled leaves exactly as it arrived."""
        out = []
        for c in self.concepts.values():
            row = {"id": c["id"], "name": c["label"], "module": c.get("module", ""), "kind": c["kind"],
                   "parent": c.get("parent") or "", "definition": c.get("definition", "")}
            if c.get("resolves_to"):
                # a publication that dropped this would re-propose the retired term to every reader of it
                row["resolves_to"] = c["resolves_to"]
            row.update(c.get("extra") or {})
            out.append(row)
        return out

    # ---------------------------------------------------------------------- RDF

    def graph(self):
        g = super().graph()
        for c in self.concepts.values():
            u = self.uri(c["id"])
            for a in c.get("alt") or []:
                g.add((u, SKOS.altLabel, Literal(a)))
            if c.get("module"):
                g.add((u, META.module, Literal(c["module"])))
            if c.get("resolves_to"):
                g.add((u, DCTERMS.isReplacedBy, self.uri(c["resolves_to"])))
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
