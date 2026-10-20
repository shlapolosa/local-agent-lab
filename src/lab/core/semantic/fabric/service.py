"""FabricService — the four metadata products (note 004) over ONE rdflib Dataset and ONE Catalog port:

  Catalog        catalog_get · catalog_upsert · catalog_state · catalog_assert
  Graph          graph_assert · graph_retract · graph_traverse · graph_impact
  Vocabulary     vocab_link · vocab_propose
  facade         embed · similar · search        (the embedding index is not a product — it proposes)
  gate           promote                          (a person's decision: actor required)
  persistence    snapshot · restore · PERSISTED   (one N-Quads text per named graph; the substrate stores them)

Every write goes into a rung graph WITH a PROV record (graph.py), is SHACL-checked against the fabric's
shapes, and — only if it conforms — is reported to `on_write` with the graphs it touched. A violation is
undone before the caller hears of it, so the store never holds a triple the shapes refuse (NFR-2, NFR-3).
Pure: rdflib + pyshacl + the catalog port; no HTTP, no Redis, no store — the substrate wraps this."""
from __future__ import annotations

import re
from itertools import combinations
from typing import Any, Callable, Iterable, Mapping

from rdflib import RDF, Dataset, Literal, URIRef
from rdflib.namespace import Namespace

from lab.core import ids
from lab.core.delivery import DeliveryContext
from lab.core.viz import TopologyView
from lab.core.semantic.fabric import concepts, relations, renderings
from lab.core.semantic.fabric import derive as DR
from lab.core.semantic.fabric import graph as G
from lab.core.semantic.fabric import shapes
from lab.core.semantic.fabric import corpus, topology
from lab.core.semantic.fabric.vocabulary import _LOCAL_NAME
from lab.core.semantic.fabric.catalog import (FIELDS, STATE_IRI, STATES, Catalog, CatalogEntry, MAX_TITLE, describe,
                                              iri_safe, pointer_key, subject_labels)
from lab.core.semantic.fabric.ontology import DocumentTypes, short as _short
from lab.core.semantic.fabric.rungs import (DERIVED, CANDIDATES_GRAPH, CONFIRMED, CONSTRUCTED, CURATED_GRAPH, EXTRACTED, GRAPH_RUNGS,
                                             IMPACT_READS,
                                             PROV_GRAPH, graph_iri)

FAB, DCT, SKOS = G.FAB, G.DCT, G.SKOS
DCAT = Namespace("http://www.w3.org/ns/dcat#")
CANDIDATE = "urn:fabric:candidate:"
CURATION = "urn:fabric:curation:"      # one recorded decision about the vocabulary
CONFLICT = "urn:fabric:conflict:"      # one word with several meanings, awaiting a steward
#: one record's "this is NOT what I am about", so a label match cannot put it back. Its OWN node, as a
#: conflict has: the artifact's shape is closed, and a record's facts are not the place for a negative.
EXCLUSION = "urn:fabric:not-about:"
#: one proposed RELATION between two concepts, awaiting a steward. Keyed like a conflict and for the
#: same reason: both producers recompute their candidates, so only askedness and refusal are durable.
RELATION_Q = "urn:fabric:relation-q:"
DOC_TYPE_SCHEME = "urn:fabric:scheme:doc-types#"
PERSON = "urn:fabric:person:"
#: What an IRI looks like HERE: a URN, or a scheme with an authority (`art://`, `collab://`, `https://`). A
#: bare `word:word` is a label — `09:00`, `Confidential:Internal` — however scheme-shaped its first token.
_IRI = re.compile(r"^(urn:[a-z0-9][a-z0-9-]*:|[a-z][a-z0-9+.-]*://)\S+$", re.I)


def _norm(label: str) -> str:
    """A label as it is MATCHED: case-folded with internal whitespace collapsed. Spelling is a person's;
    sameness is not — `Decision record`, `Decision Record` and `  decision   record ` are one question."""
    return " ".join(str(label or "").split()).casefold()


def term(value: Any) -> URIRef | Literal:
    """A tool argument as an RDF term: an IRI when it reads as one (`_IRI`), a typed literal otherwise."""
    if isinstance(value, (URIRef, Literal)):
        return value
    if isinstance(value, str) and _IRI.match(value):
        return URIRef(value)
    return Literal(value)


def _prefixed(prefix: str, what: str) -> Callable[[Any], URIRef]:
    def coerce(value: Any) -> URIRef:
        if not (isinstance(value, str) and value.startswith(prefix)):
            raise ValueError(f"{what} must be an IRI under {prefix}, not {value!r}")
        return URIRef(value)
    return coerce


#: catalog facet -> (the predicate its assertion carries, how its value becomes a typed term). The facets are
#: TYPED here rather than guessed by `term()`: an owner is a person IRI, a type is a doc-types concept, a label
#: is always a literal (NFR-3 is about where the label comes from, not what it looks like).
def _rendering(v: Any) -> Literal:
    name = str(v or "").strip()
    if name not in renderings.RENDERINGS:
        raise ValueError(f"rendering must be one of {sorted(renderings.RENDERINGS)}, not {name!r}")
    return Literal(name)


FACETS: dict[str, tuple[URIRef, Callable[[Any], URIRef | Literal]]] = {
    "document_type": (FAB.documentType, _prefixed(DOC_TYPE_SCHEME, "document_type")),
    "owner": (FAB.ownedBy, _prefixed(PERSON, "owner")),
    "sensitivity_label": (FAB.sensitivityLabel, lambda v: Literal(str(v))),
    # the projection page's URL: a LITERAL, because the URL a person opens can embed its own tenant and is
    # not a thing the graph names — `dcat:landingPage` is "a web page to navigate to in order to gain access
    # to the resource", which is exactly what the projector writes.
    "projection_url": (DCAT.landingPage, lambda v: Literal(str(v))),
    # HOW the text a record's concepts were grounded in was read. A LITERAL from a declared ladder, and
    # refused when undeclared — unlike `renderings.of()`, which is deliberately forgiving because an
    # unclassified INPUT must still be ingestible. A caller naming a rendering is making a claim, and a
    # typo in a claim must fail loudly rather than quietly become the weakest reading.
    "rendering": (FAB.rendering, _rendering),
}
#: the identity facts mirrored into graph C on upsert — set, not asserted (they ARE the catalog row), so a
#: caller may never retract one edge-wise: `catalog_state` moves them.
_MIRRORED = (RDF.type, DCT.title, DCAT.accessURL, FAB.lifecycleState, FAB.producedBy, FAB.sourceKind,
             FAB.baselineVersion, FAB.unassociated)
#: the edges `catalog_get` reports beside the row
_LINKS = (FAB.deliveredUnder, FAB.references, FAB.duplicateOf, FAB.relatedTo, FAB.synthesisedFrom, DCT.subject, FAB.documentType,
          FAB.ownedBy, FAB.sensitivityLabel, DCAT.landingPage, FAB.rendering)
#: persisted name -> named graph: the five rungs, the PROV records, the candidates
def _iri_or_raise(what: str, value: str) -> str:
    """A gateway tool takes a free string, and a non-IRI stored here breaks the curated graph's own
    serialisation later — far from the call that caused it. The same check `graph_assert` makes."""
    if not isinstance(value, str) or iri_safe(value) != value:
        raise ValueError(f"{what} is not a serialisable IRI: {value!r}")
    return value


def concept_id_for(label: str) -> str:
    """The id a NEW concept takes when the steward names none: the label as one word, in the shape the seeded
    vocabularies already use ("Model card" -> "ModelCard"). ONE home — the substrate's gate shows this as the
    default and sends it as the answer, so a second copy that split on spaces alone gave "Model-card" a
    different id depending on which path minted it. A steward may always override it, because an id is what
    every consumer joins on and is the one thing that must not be regretted."""
    return "".join(w[:1].upper() + w[1:] for w in re.split(r"[^0-9A-Za-z]+", str(label or "")) if w) or "Concept"


PERSISTED_GRAPHS: dict[str, URIRef] = {"prov": PROV_GRAPH, "candidates": CANDIDATES_GRAPH,
                                       "curated": CURATED_GRAPH,
                                       **{r: graph_iri(r) for r in GRAPH_RUNGS}}


class FabricService:
    PERSISTED: tuple[str, ...] = tuple(PERSISTED_GRAPHS)

    def __init__(self, ds: Dataset, catalog: Catalog, doc_types: DocumentTypes, *,
                 schemes: Callable[[], Mapping[str, Any]], embedder: Any = None,
                 on_write: Callable[[Iterable[str]], None] | None = None) -> None:
        self.ds = ds
        self.catalog = catalog
        self.doc_types = doc_types
        self._schemes = schemes
        self.embedder = embedder
        self._on_write = on_write or (lambda touched: None)

    # ------------------------------------------------------------------ guard

    def _view(self, subjects: Iterable[URIRef] = ()) -> Dataset:
        """The fabric's own graphs, by identity, so the SPARQL constraint sees WHICH graph holds a triple
        without pyshacl walking the vocabularies beside them. With `subjects`, only THEIR triples and the
        PROV records about them — the shapes are per focus node, so a write is checked in work proportional
        to the change, not to the corpus."""
        v = Dataset(default_union=True)
        wanted = set(subjects)
        for iri in PERSISTED_GRAPHS.values():
            g, src = v.graph(iri), self.ds.graph(iri)
            if not wanted:
                for t in src:
                    g.add(t)
                continue
            for s in wanted:
                for t in src.triples((s, None, None)):
                    g.add(t)
        if wanted:
            prov, pv = self.ds.graph(PROV_GRAPH), v.graph(PROV_GRAPH)
            for stmt in {st for s in wanted for st in prov.subjects(RDF.subject, s)}:
                for t in prov.triples((stmt, None, None)):
                    pv.add(t)
                for aid in prov.subjects(FAB.asserts, stmt):
                    for t in prov.triples((aid, None, None)):
                        pv.add(t)
        return v

    def validate(self, subjects: Iterable[URIRef] = ()) -> shapes.Report:
        return shapes.validate(self._view(subjects))

    def _commit(self, touched: Iterable[str], undo: Callable[[], None], *, subjects: Iterable[URIRef] = ()) -> None:
        report = self.validate(subjects)
        if not report.conforms:
            undo()
            raise ValueError("refused by the fabric's shapes: " + "; ".join(report.messages))
        self._persist(touched, undo)

    def _persist(self, touched: Iterable[str], undo: Callable[[], None]) -> None:
        """Hand the touched graphs to the store; a write it did not take must not survive in memory — a restart
        would lose it silently while the caller was told it failed. Sound because `RungStore.save` moves its
        pointer hash only after every snapshot is stored: undoing memory restores agreement with the durable copy."""
        try:
            self._on_write(tuple(dict.fromkeys(touched)))
        except Exception:
            undo()
            raise

    def _invalidations(self) -> set:
        prov = self.ds.graph(PROV_GRAPH)
        return {(a, o) for a, _, o in prov.triples((None, G.PROV.wasInvalidatedBy, None))}

    def _uninvalidate(self, before: set) -> None:
        """Take back the PROV invalidations a supersede wrote — an undone retraction must not leave a live
        triple whose assertion record says it was invalidated."""
        prov = self.ds.graph(PROV_GRAPH)
        for a, o in self._invalidations() - before:
            prov.remove((a, G.PROV.wasInvalidatedBy, o))
            prov.remove((a, G.PROV.invalidatedAtTime, None))

    def _undo_assertion(self, a: G.Assertion) -> None:
        self.ds.graph(graph_iri(a.rung)).remove((a.subject, a.predicate, a.object))
        prov = self.ds.graph(PROV_GRAPH)
        stmt = prov.value(a.id, FAB.asserts)
        prov.remove((a.id, None, None))
        if stmt is not None:
            prov.remove((stmt, None, None))

    # ---------------------------------------------------------------- catalog

    def catalog_page(self, *, after: str = "", limit: int = 100, state: str = "") -> list:
        """One page of the catalogue in IRI order — the service's thin pass-through to the store's walk,
        so every caller gets the same keyset semantics and the same refusal of an unknown state."""
        return self.catalog.page(after=after, limit=limit, state=state)

    def catalog_get(self, iri: str = "", *, pointer: dict | None = None) -> dict | None:
        """The row by IRI — or by POINTER, which is how a sweep asks "have I seen this item at this version"."""
        e = self.catalog.get(iri) if iri else (self.catalog.by_pointer(pointer_key(pointer)) if pointer else None)
        if e is None:
            return None
        iri = e.iri
        a = URIRef(iri)
        links = []
        for r, (_, p, o) in G.find(self.ds, a):
            if p not in _LINKS:
                continue
            link = {"predicate": _short(p), "object": str(o), "rung": r}
            label = self._concept_label(str(o)) if isinstance(o, URIRef) else ""
            if label:                                 # a concept reads by its label, not its hashed id
                link["label"] = label
            links.append(link)
        return {**e.to_dict(), "links": links}

    def catalog_upsert(self, pointer: dict, *, iri: str = "", title: str = "", produced_by: str = "",
                       context: str = "", source_kind: str = "") -> dict:
        """Identify an artifact (mint its IRI, or find it by pointer) and mirror the row into graph C. A lab
        process's output gets its type as a FACT (produced-by) and its delivery edge from the run (rung C)."""
        key = pointer_key(pointer)
        if len(title) > MAX_TITLE:
            raise ValueError(f"a title is a label, not a body: {MAX_TITLE} characters")
        existing = self.catalog.get(iri) if iri else self.catalog.by_pointer(key)
        ctx = DeliveryContext.parse(context) if context else None
        fields = dict(title=title, produced_by=produced_by, context=ctx.key if ctx else "",
                      source_kind=source_kind or pointer.get("source", ""))
        doc_type = self.doc_types.for_process(produced_by) if produced_by else None
        if doc_type:
            fields["document_type"] = doc_type
        # A NEW VERSION of a product already known (the pointer's version moved): the record is the same, its
        # review reopens — state back to pending, the previous baseline kept on the row until the new one lands.
        previous = str(existing.pointer.get("version") or "") if existing else ""
        revised = bool(existing) and str(pointer.get("version") or "") != previous
        if revised and existing.state != "pending":
            fields["state"] = "pending"
        entry = existing.with_(pointer=dict(pointer), **fields) if existing else \
            CatalogEntry(iri or ids.artifact_iri(), dict(pointer), **fields)
        a = URIRef(entry.iri)
        c = self.ds.graph(graph_iri(CONSTRUCTED))
        before = [t for t in c.triples((a, None, None)) if t[1] in _MIRRORED]
        for t in before:
            c.remove(t)
        self._mirror(entry)
        made: list[G.Assertion] = []
        if doc_type and G.find(self.ds, a, FAB.documentType, URIRef(doc_type)) == []:
            for r, (s, p, o) in G.find(self.ds, a, FAB.documentType):
                G.retract(self.ds, s, p, o, actor="rule:produced-by", reason="type is a fact of the producing process")
            made.append(G.assert_triple(self.ds, a, FAB.documentType, URIRef(doc_type), rung=CONSTRUCTED, method="produced-by"))
        if ctx and G.find(self.ds, a, FAB.deliveredUnder, URIRef(ctx.iri)) == []:
            made.append(G.assert_triple(self.ds, a, FAB.deliveredUnder, URIRef(ctx.iri), rung=CONSTRUCTED,
                                        method="run-context"))

        def undo():
            for m in made:
                self._undo_assertion(m)
            for t in c.triples((a, None, None)):
                if t[1] in _MIRRORED:
                    c.remove(t)
            for t in before:
                c.add(t)
        self._commit(("C", "prov"), undo, subjects=(a,))
        self.catalog.put(entry)
        out = entry.to_dict()
        out.update({"revised": revised, "previous_version": previous} if revised else {})
        return out

    def _mirror(self, e: CatalogEntry) -> None:
        a, c = URIRef(e.iri), self.ds.graph(graph_iri(CONSTRUCTED))
        c.add((a, RDF.type, FAB.Artifact))
        c.add((a, DCAT.accessURL, URIRef(e.custody_iri)))
        c.add((a, FAB.lifecycleState, URIRef(STATE_IRI[e.state])))
        if e.title:
            c.add((a, DCT.title, Literal(e.title)))
        if e.produced_by:
            c.add((a, FAB.producedBy, Literal(e.produced_by)))
        if e.source_kind:
            c.add((a, FAB.sourceKind, Literal(e.source_kind)))
        if e.baseline_version:
            c.add((a, FAB.baselineVersion, Literal(e.baseline_version)))
        if e.unassociated:
            c.add((a, FAB.unassociated, Literal(True)))

    def _require(self, iri: str) -> CatalogEntry:
        e = self.catalog.get(iri)
        if e is None:
            raise LookupError(f"no catalog entry {iri}")
        return e

    def catalog_state(self, iri: str, state: str, *, baseline_version: str | None = None,
                      unassociated: bool | None = None) -> dict:
        if state not in STATES:
            raise ValueError(f"state must be one of {list(STATES)}, not {state!r}")
        e = self._require(iri)
        changes: dict[str, Any] = {"state": state}
        if baseline_version is not None:
            changes["baseline_version"] = baseline_version
        if unassociated is not None:
            changes["unassociated"] = bool(unassociated)
        new = e.with_(**changes)
        a, c = URIRef(iri), self.ds.graph(graph_iri(CONSTRUCTED))
        before = [t for t in c.triples((a, None, None)) if t[1] in _MIRRORED]
        for t in before:
            c.remove(t)
        self._mirror(new)

        def undo():
            for t in c.triples((a, None, None)):
                if t[1] in _MIRRORED:
                    c.remove(t)
            for t in before:
                c.add(t)
        self._commit(("C",), undo, subjects=(a,))
        self.catalog.put(new)
        return new.to_dict()

    def catalog_assert(self, iri: str, field: str, value: Any, *, rung: str, method: str, actor: str = "",
                       confidence: float | None = None) -> dict:
        """Assert a classified facet at a rung: the row's column AND the graph triple with its provenance.
        A previous value of the facet is superseded (retracted, never deleted). Owner and label are refused
        anywhere but C by the shapes (NFR-3)."""
        if field not in FIELDS:
            raise ValueError(f"field must be one of {list(FIELDS)}, not {field!r}")
        e = self._require(iri)
        p, coerce = FACETS[field]
        o = coerce(value)
        r = self.graph_assert(iri, str(p), o, rung=rung, method=method, actor=actor, confidence=confidence,
                              supersede=True)
        self.catalog.put(e.with_(**{field: str(o)}))
        return r

    # ------------------------------------------------------------------ graph

    def graph_assert(self, subject: str, predicate: str, obj: Any, *, rung: str, method: str, actor: str = "",
                     confidence: float | None = None, supersede: bool = False) -> dict:
        for what, value in (("subject", subject), ("predicate", predicate)):
            if not isinstance(value, str) or iri_safe(value) != value:
                raise ValueError(f"{what} is not a serialisable IRI: {value!r}")
        s, p, o = URIRef(subject), URIRef(predicate), term(obj)
        # A PERSON'S NO about this record, enforced where the triple is WRITTEN rather than in one reader.
        # `vocab_link` subtracted it, but admission propagation (FR-1.1.5) asserts `dct:subject` through
        # this door instead — so the owner's answer lasted until the next admission and no further. One
        # place, and every path obeys it. Only `dct:subject` is constrained: a record a person says is not
        # ABOUT a concept may still be related to, owned by, or typed as anything at all.
        if p == DCT.subject and str(o) in self._not_about(subject):
            raise ValueError(f"{subject} is recorded as not about {o} — a person's answer. "
                             f"Clear it with about_after_all before asserting it again.")
        prior = G.find(self.ds, s, p) if supersede else []
        for r, (_, _, old) in prior:
            if old == o and r == rung:
                return {"assertion": "", "rung": rung, "subject": subject, "predicate": predicate,
                        "object": str(o), "unchanged": True}
        retracted = [(r, old) for r, (_, _, old) in prior]
        before = self._invalidations()
        for r, old in retracted:
            G.retract(self.ds, s, p, old, actor=actor or method, reason=f"superseded at rung {rung}")
        made = G.assert_triple(self.ds, s, p, o, rung=rung, method=method, actor=actor, confidence=confidence)

        def undo():
            self._undo_assertion(made)
            for r, old in retracted:
                self.ds.graph(graph_iri(r)).add((s, p, old))
            self._uninvalidate(before)
        self._commit((rung, "prov", *[r for r, _ in retracted]), undo, subjects=(s,))
        return {"assertion": str(made.id), "rung": rung, "subject": subject, "predicate": predicate,
                "object": str(o), "unchanged": False}

    def graph_retract(self, subject: str, predicate: str, obj: Any, *, actor: str, reason: str) -> bool:
        """Supersede an edge — through the same guard as an assertion, so the store stays conforming. The
        row's own facts (type, custody, lifecycle …) are not edges: `catalog_state` moves them."""
        s, p, o = URIRef(subject), URIRef(predicate), term(obj)
        if p in _MIRRORED:
            raise ValueError(f"{_short(p)} is the catalog row's own fact — use catalog_state, not a retraction")
        # A FACET edge is mirrored in the row's column: retracting the edge clears the column when it still
        # carries that value, whether or not the triple is still there (the graph and the row must agree —
        # measured live: a retracted type left `minutes` on the row).
        facet = next((f for f, (pred, _) in FACETS.items() if pred == p), None)
        row = self.catalog.get(subject) if facet else None
        clears = row is not None and getattr(row, facet) == str(o)
        hits = G.find(self.ds, s, p, o)
        if not hits:
            if clears:
                self.catalog.put(row.with_(**{facet: ""}))
            return False
        before = self._invalidations()
        G.retract(self.ds, s, p, o, actor=actor, reason=reason)

        def undo():
            for r, _ in hits:
                self.ds.graph(graph_iri(r)).add((s, p, o))
            self._uninvalidate(before)
        self._commit((*[r for r, _ in hits], "prov"), undo, subjects=(s,))
        if clears:                                   # the row follows the graph, never leads it
            self.catalog.put(row.with_(**{facet: ""}))
        return True

    def _join(self, hits: list[tuple[URIRef, int, str]]) -> list[dict]:
        out = []
        for node, dist, rung in hits:
            e = self.catalog.get(str(node))
            out.append({"iri": str(node), "distance": dist, "rung": rung,
                        "title": e.title if e else "", "document_type": e.document_type if e else "",
                        "state": e.state if e else "", "owner": e.owner if e else ""})
        return out

    def graph_traverse(self, start: str, predicates: list[str], *, rungs: list[str], depth: int = 3,
                       inbound: bool = True) -> list[dict]:
        preds = tuple(URIRef(p) for p in predicates)
        return self._join(G.traverse(self.ds, URIRef(start), preds, rungs=tuple(rungs), depth=depth, inbound=inbound))

    def graph_impact(self, iri: str, *, depth: int = 3) -> list[dict]:
        return self._join(G.impact(self.ds, URIRef(iri), depth=depth))

    # ------------------------------------------------------------- vocabulary

    def vocab_link(self, iri: str, terms: list[str], *, schemes: list[str] | None = None) -> dict:
        """Link an artifact to the concepts whose preferred label a term matches exactly — rung X, because a
        label match is extracted, not guessed. Misses are what `vocab_propose` is for.

        The EXTRACTED subjects are REPLACED, not added to: what this run did not produce is retracted at the
        end. Without that a re-classification could only ever widen a record's subjects, so a document first
        read from its file name would keep those guesses for ever and a better-evidenced second pass would
        leave a union nobody can interpret (measured 7 Oct 2026: `Clinical document` on 39 of 93 records).

        Per-assertion superseding would be wrong — this asserts once per concept, so each call would retract
        the one before and a document would end with its last subject only. The unit replaced is the SET.

        Rung H is never touched. Promotion to H is the one act the ladder exists to record, and a classifier
        that silently retracted a person's judgement would undo it on the next sweep."""
        self._require(iri)
        available = self._schemes()
        chosen = {n: sc for n, sc in available.items() if not schemes or n in schemes}
        linked, missed, conflicts = [], [], []
        resolved: list[tuple[Any, dict]] = []
        for t in terms:
            # TWO ATTEMPTS, as the diagram lane does. `find` only strips and case-folds, while an extracted
            # phrase arrives plural, with an article, or wrapped — so "the Care Deliverys" missed a concept
            # the vocabulary holds, and `vocab_propose` then parked a DUPLICATE candidate for it, which is
            # the defect `_held_by` exists to prevent, recreated one tier up. `concepts.normalise` is the
            # same normaliser the semantic tier probes with, so the two tiers agree what a term is.
            hits = ([(n, sc, c) for n, sc in chosen.items() for c in sc.find(t)]
                    or [(n, sc, c) for n, sc in chosen.items() for c in sc.find(concepts.normalise(t))])
            if not hits:
                missed.append(t)
                continue
            by_scheme: dict[str, list] = {}
            for n, sc, c in hits:
                by_scheme.setdefault(n, []).append((n, sc, c))
            # One word, several meanings WITHIN one vocabulary. Linking to all of them is worse than linking
            # to none: the document carries both, and nothing downstream — the picture, impact, search — can
            # tell which was meant. Across vocabularies it is not an ambiguity at all: that is what having
            # two vocabularies means, and each is linked as before.
            ambiguous = {n for n, group in by_scheme.items() if len({c["id"] for _, _, c in group}) > 1}
            for n in sorted(ambiguous):
                conflicts.append(self._conflict(t, n, [c["id"] for _, _, c in by_scheme[n]]))
            for n, sc, c in [h for h in hits if h[0] not in ambiguous]:
                concept = sc.uri(c["id"])
                resolved.append((concept, {"term": t, "scheme": n, "concept": str(concept), "label": c["label"]}))
        # Everything is resolved BEFORE anything is written, so the set this run produces is known and the
        # stale extracted subjects can go in one commit rather than one per concept.
        # ONE ROW PER CONCEPT. Several terms legitimately resolve to one — which is what the second match
        # attempt is for — and a row per TERM meant the owner's card built two items keyed on the same
        # concept IRI, which `approvals_ask` refuses outright ("duplicate labels"), killing the run. It also
        # wrote a second provenance assertion for a triple already asserted. The first spelling that matched
        # is the one reported; the others are not lost, they are the same subject said twice.
        seen_concepts: set[str] = set()
        resolved = [(c, row) for c, row in resolved
                    if not (str(c) in seen_concepts or seen_concepts.add(str(c)))]
        # A person's NO, subtracted before anything is written. Without this the owner's `drop` lasted
        # exactly until the next sweep, while their `keep` lasted for ever.
        refused = self._not_about(iri)
        excluded = sorted({str(c) for c, _ in resolved} & refused)
        resolved = [(c, row) for c, row in resolved if str(c) not in refused]
        kept = {str(concept) for concept, _ in resolved}
        # `G.retract` is rung-agnostic — it removes the triple from EVERY rung graph that holds it. So a
        # subject a person promoted to H would be retracted by a sweep: the one act the ladder exists to
        # record, undone. A subject held at any rung above EXTRACTED is therefore left exactly as it is.
        # (This comment used to say promotion "keeps its X copy". It does not — `G.promote` MOVES the
        # triple and invalidates the old assertion. The X copies this set finds are ones a LATER
        # classification re-added, which is why the re-assert below skips a concept already held higher:
        # without that, every re-read of a confirmed record minted a duplicate X beneath the H, `catalog_get`
        # reported the subject twice at two rungs, and the curator re-promoted it on every review.)
        held_elsewhere = {str(o) for r, (_, _, o) in G.find(self.ds, URIRef(iri), DCT.subject) if r != EXTRACTED}
        stale = [(r, o) for r, (_, _, o) in G.find(self.ds, URIRef(iri), DCT.subject, rungs=(EXTRACTED,))
                 if str(o) not in kept and str(o) not in held_elsewhere]
        if stale:
            a = URIRef(iri)
            for _r, old_obj in stale:
                G.retract(self.ds, a, DCT.subject, old_obj, actor="classifier",
                          reason="no longer matched when the artifact was re-classified")

            def undo(_a=a, _stale=tuple(stale)):
                for r, old_obj in _stale:
                    self.ds.graph(graph_iri(r)).add((_a, DCT.subject, old_obj))

            self._commit(("graph",), undo, subjects=(a,))
        for concept, row in resolved:
            if str(concept) not in held_elsewhere:      # already C/H/D: a second copy at X says nothing new
                self.graph_assert(iri, str(DCT.subject), concept, rung=EXTRACTED, method="label-match")
            linked.append(row)
        return {"linked": linked, "missed": missed, "conflicts": conflicts,
                "retracted": [str(o) for _r, o in stale], "excluded": excluded}

    def _held_by(self, label: str) -> str:
        """The vocabulary that ALREADY holds this term, by preferred or alternative label — or "".

        Checked across EVERY vocabulary, which is the half that was missing. A candidate used to be closed
        only when its OWN scheme found the label, so a term parked under one scheme was never checked
        against another: measured 10 Oct 2026, 25 of 71 open cards were for terms the doc-types scheme
        already held — `Decision record` asked twelve times, `Meeting minutes` six. The classifier had
        confused what a document IS with what it is ABOUT, and the register repeated the confusion once per
        document instead of catching it once."""
        want = _norm(label)
        for iri, t in self.doc_types.types().items():
            if want in {_norm(t["label"]), *(_norm(a) for a in t["alt"])}:
                return self.doc_types.name
        for name, sc in (self._schemes() or {}).items():
            if sc is not None and sc.find(label):
                return name
        return ""

    def _candidate_for(self, label: str, scheme: str, alias_of: str = ""):
        """The candidate row for this term in this scheme, WHATEVER its state, or None. Matched on the
        normalised label so a difference of case or spacing is not a second question (`Decision record` /
        `Decision Record` were two rows on the live register).

        State is deliberately NOT a filter here. A term a steward DECLINED must not quietly start a new row
        the next time a document uses the word — the answer was about the term, so the new artifact joins
        the row that already carries the answer, and `vocab_candidates` is the one place that decides
        whether anybody is asked about it."""
        want, g = _norm(label), self.ds.graph(CANDIDATES_GRAPH)
        for node in g.subjects(RDF.type, SKOS.Concept):
            if _norm(str(g.value(node, SKOS.prefLabel) or "")) != want:
                continue
            if str(g.value(node, FAB.candidateScheme) or "") != scheme:
                continue                      # schemes are never merged: one word may be missing from each
            # ...and a different PROPOSED TARGET is a different question. The key used to be label +
            # scheme alone, which was enough while every candidate meant "invent a concept for this". Once
            # a matcher can say "this looks like another word for X", a term parked with no target and the
            # same term later matched to one would join the same row and the target would simply vanish —
            # the second answer lost to the first with nothing on screen to say so.
            if str(g.value(node, FAB.aliasOf) or "") != alias_of:
                continue
            return node
        return None

    def vocab_propose(self, label: str, *, definition: str = "", actor: str, broader: str = "",
                      scheme: str = "", concept_id: str = "", module: str = "",
                      proposed_for: str = "", alias_of: str = "") -> dict:
        """Park a candidate concept for a steward (the candidates graph is not a scheme: a steward accepts
        it with `promote`, which records the acceptance at rung H).

        ONE ROW PER TERM, not one per time it was met. `proposed_for` is the ARTIFACT that used the word,
        accumulated on the candidate as `fab:proposedFor` — so a steward is asked once however many
        documents want it, the count is evidence of how much it matters, and admitting it can re-match
        exactly the artifacts that asked (FR-1.1.5) instead of the whole catalogue. The count is DERIVED
        from that set rather than stored beside it: two numbers that must agree eventually do not.

        A term any vocabulary ALREADY holds is not parked at all — see `_held_by`. The answer says which
        vocabulary holds it, because "this already means something" is a useful reply to the caller and a
        silent no-op is not.

        `scheme` is the vocabulary it would join and `concept_id` the id it would take — both optional here and
        both REQUIRED by the time it is admitted, because a concept with no home cannot be looked up and an id
        is what every consumer joins on. Left out, the steward supplies them at the gate."""
        if not str(label or "").strip():
            raise ValueError("a candidate has a label")
        if not actor:
            raise ValueError("a proposal names who proposed it")
        held = self._held_by(label)
        if held:
            return {"label": label.strip(), "scheme": scheme, "held_by": held}
        g = self.ds.graph(CANDIDATES_GRAPH)
        existing = self._candidate_for(label, scheme, alias_of)
        if existing is not None:
            if proposed_for:
                g.add((existing, FAB.proposedFor, URIRef(proposed_for)))
                self._persist(("candidates",), lambda: g.remove((existing, FAB.proposedFor,
                                                                 URIRef(proposed_for))))
            return {"iri": str(existing), "label": str(g.value(existing, SKOS.prefLabel) or ""),
                    "scheme": scheme, "concept_id": str(g.value(existing, FAB.candidateId) or ""),
                    "module": str(g.value(existing, FAB.candidateModule) or ""), "held_by": ""}
        c = URIRef(CANDIDATE + ids.ulid())
        g.add((c, RDF.type, SKOS.Concept)); g.add((c, SKOS.prefLabel, Literal(label.strip())))
        g.add((c, G.PROV.wasAttributedTo, Literal(actor)))
        if proposed_for:
            g.add((c, FAB.proposedFor, URIRef(proposed_for)))
        if alias_of:
            # A SUGGESTION on the row, never a write to the scheme. `vocab_amend` lives in the PROMOTE
            # grant and the pipeline does not hold it, because an agent that could narrow the vocabulary
            # it is classified against would be marking its own homework. This lets the card ask the cheap
            # question — "is this another word for X?" — with X already filled in.
            g.add((c, FAB.aliasOf, URIRef(alias_of)))
        if definition:
            g.add((c, SKOS.definition, Literal(definition)))
        if broader:
            g.add((c, SKOS.broader, URIRef(broader)))
        if scheme:
            g.add((c, FAB.candidateScheme, Literal(scheme)))
        if concept_id:
            g.add((c, FAB.candidateId, Literal(concept_id)))
        if module:
            g.add((c, FAB.candidateModule, Literal(module)))
        self._persist(("candidates",), lambda: g.remove((c, None, None)))
        return {"iri": str(c), "label": label.strip(), "scheme": scheme, "concept_id": concept_id,
                "module": module, "held_by": ""}

    def vocab_asked(self, candidate: str, *, request_id: str = "") -> dict:
        """Record that a steward HAS BEEN ASKED about this term, so nobody asks twice.

        `fab:InReview` — the lifecycle already had the word, and the candidate already uses `Published`
        for admitted and `Withdrawn` for declined. Pending -> InReview -> answered is the same ladder the
        artifacts climb, which is one vocabulary rather than two.

        It lives HERE, in the register, and not in the process that asked: a set in memory forgot every
        open question on restart and raised a second card for the same terms — 71 cards became 101 in one
        afternoon. It is also not derived from the approval surface, which was the first attempt and was
        wrong: `approvals_list` returns a TRIAGE brief with no `context`, so the terms a card covers are
        not readable from it, and a check against it would have passed every test and found nothing live."""
        c = URIRef(candidate)
        g = self.ds.graph(CANDIDATES_GRAPH)
        if (c, RDF.type, SKOS.Concept) not in g:
            # A CONFLICT is the other half of this gate and had no memory at all, so the reconciler
            # re-raised the same ambiguity on every sweep tick — ~96 cards a day for one unsettled word,
            # the very flood `fab:InReview` was added to stop for candidates. Same verb, same marker, the
            # other graph: a steward is asked once about either kind of question.
            curated = self.ds.graph(CURATED_GRAPH)
            # THREE things a steward is asked about, ONE verb that remembers it: a candidate term, an
            # ambiguous word, and a proposed relation. One grant, one idea — and the register is what
            # remembers for all of them, because a set in a process forgets on restart.
            if (c, RDF.type, FAB.Conflict) in curated or (c, RDF.type, FAB.RelationQuestion) in curated:
                if curated.value(c, FAB.askedIn) is not None:
                    return {"iri": candidate, "asked": False, "already": True}
                triples = [(c, FAB.askedIn, Literal(request_id or "asked"))]
                for t in triples:
                    curated.add(t)
                self._persist(("curated",), lambda: [curated.remove(t) for t in triples])
                return {"iri": candidate, "asked": True}
            raise LookupError(f"no candidate {candidate}")
        if g.value(c, FAB.lifecycleState) is not None:
            return {"iri": candidate, "asked": False, "already": True}   # answered, or already asked
        added = [(c, FAB.lifecycleState, FAB.InReview)]
        if request_id:
            added.append((c, FAB.askedIn, Literal(request_id)))
        for t in added:
            g.add(t)
        self._persist(("candidates",), lambda: [g.remove(t) for t in added])
        return {"iri": candidate, "asked": True, "request_id": request_id}

    def vocab_decline(self, candidate: str, *, actor: str, reason: str = "") -> dict:
        """A steward's NO about a term, recorded where it survives the process that heard it.

        The decline used to live only on the approval, while the reconciler's "already asked" memory was a
        set in the PROCESS — so every restart re-asked every still-open candidate with a fresh approval id.
        Measured 10 Oct 2026: the open `concept-admission` cards went from 71 to 101 in one afternoon while
        a steward decided nothing, and any cleanup would have been undone by the next deploy.

        `fab:Withdrawn`, not a state of its own: it is the word the artifact lifecycle already uses for
        "this will not proceed", and a second word for one idea is how two readers come to disagree. The
        answer is about the TERM, so meeting the word again does not reopen it — `vocab_propose` finds the
        withdrawn row and adds the artifact to it, and the register still does not ask."""
        if not actor:
            raise ValueError("a decline names the person: actor is required")
        c = URIRef(candidate)
        g = self.ds.graph(CANDIDATES_GRAPH)
        if (c, RDF.type, SKOS.Concept) not in g:
            raise LookupError(f"no candidate {candidate}")
        added = [(c, FAB.lifecycleState, FAB.Withdrawn), (c, G.PROV.wasAttributedTo, Literal(actor))]
        if reason:
            added.append((c, FAB.declineReason, Literal(reason)))
        for t in added:
            g.add(t)
        self._persist(("candidates",), lambda: [g.remove(t) for t in added])
        return {"iri": candidate, "declined": True, "actor": actor, "reason": reason}

    # ------------------------------------------------------------------ gate

    def promote(self, subject: str, predicate: str = "", obj: Any = None, *, actor: str, method: str,
                to: str = CONFIRMED) -> dict:
        """A person's decision. With a predicate: move that assertion up the ladder. Without one: accept a
        candidate concept (its acceptance is a confirmed assertion on the candidate)."""
        if not actor:
            raise ValueError("a promotion is a person's decision: actor is required")
        s = URIRef(subject)
        if not predicate:
            return self._admit(s, actor=actor, method=method, to=to)
        p, o = URIRef(predicate), term(obj)
        current = next((r for r, _ in G.find(self.ds, s, p, o)), None)
        before = self._invalidations()
        made = G.promote(self.ds, s, p, o, to=to, actor=actor, method=method)

        def undo():
            self._undo_assertion(made)
            if current:
                self.ds.graph(graph_iri(current)).add((s, p, o))
            self._uninvalidate(before)
        self._commit((current, to, "prov"), undo, subjects=(s,))
        return {"assertion": str(made.id), "rung": to, "from": current, "subject": subject,
                "predicate": predicate, "object": str(o)}

    # ------------------------------------------------------------ curation

    def _scheme(self, name: str):
        sc = (self._schemes() or {}).get(name)
        if sc is None:
            raise LookupError(f"the fabric holds no vocabulary {name!r} — it holds "
                              f"{sorted((self._schemes() or {}))}")
        return sc

    def _admit(self, candidate: URIRef, *, actor: str, method: str, to: str = CONFIRMED) -> dict:
        """Accept a parked candidate INTO its vocabulary: the concept itself, durably, in the admitting
        person's name — not merely a lifecycle triple on a candidate no lookup can reach."""
        cg = self.ds.graph(CANDIDATES_GRAPH)
        if (candidate, RDF.type, SKOS.Concept) not in cg:
            raise LookupError(f"{candidate} is not a candidate concept")
        label = str(cg.value(candidate, SKOS.prefLabel) or "")
        name = str(cg.value(candidate, FAB.candidateScheme) or "")
        if not name:
            raise ValueError(f"candidate {label!r} names no scheme to join — admit it with a scheme, "
                             f"one of {sorted((self._schemes() or {}))}")
        scheme = self._scheme(name)
        cid = str(cg.value(candidate, FAB.candidateId) or "") or concept_id_for(label)
        held = scheme.concepts.get(cid)
        if held is not None and held.get("label") == label:
            # Already admitted — a redrive of a decision whose first attempt got this far, or a steward
            # answering twice. Idempotent HERE rather than in the applier, because this is what owns the id:
            # raising would leave the approval permanently stuck behind a confusing error.
            return {"from": "candidates", "scheme": name, "concept_id": cid,
                    "concept": str(scheme.uri(cid)), "label": label, "actor": actor, "rung": to,
                    "assertion": "", "already": True}
        broader = str(cg.value(candidate, SKOS.broader) or "")
        row = {"id": cid, "label": label, "definition": str(cg.value(candidate, SKOS.definition) or ""),
               "parent": scheme.resolve(broader) if broader else None,
               "module": str(cg.value(candidate, FAB.candidateModule) or "")}
        scheme.admit(**row)
        undo_scheme = lambda: scheme.concepts.pop(cid, None)          # noqa: E731
        try:
            written = self._record_curation(name, "admitted", row, actor=actor, method=method, to=to)
        except Exception:
            undo_scheme()
            raise
        self.graph_assert(str(candidate), str(FAB.lifecycleState), FAB.Published, rung=to, method=method,
                          actor=actor, supersede=True)
        return {"from": "candidates", "scheme": name, "concept_id": cid, "concept": str(scheme.uri(cid)),
                "label": label, "actor": actor, "rung": to, "assertion": written}

    def vocab_retire(self, cid: str, *, scheme: str, resolves_to: str, actor: str, reason: str = "",
                     to: str = CONFIRMED) -> dict:
        """Supersede a concept: it stops being offered and keeps resolving to the one that replaced it.

        A person's decision, recorded as one — `actor` is refused blank for the same reason an approval's is:
        "who narrowed this vocabulary" is what the record is for."""
        if not actor:
            raise ValueError("a retirement is a person's decision: actor is required")
        sc = self._scheme(scheme)
        before = dict(sc.concepts[cid]) if cid in sc.concepts else None
        sc.retire(cid, resolves_to=resolves_to, reason=reason)
        row = {"id": cid, "resolves_to": resolves_to, "reason": reason}
        try:
            written = self._record_curation(scheme, "retired", row, actor=actor, method="retire", to=to)
        except Exception:
            if before is not None:
                sc.concepts[cid] = before
            raise
        return {"scheme": scheme, "concept_id": cid, "resolves_to": resolves_to, "actor": actor,
                "rung": to, "assertion": written}

    def vocab_amend(self, cid: str, *, scheme: str, alt: str, actor: str, reason: str = "",
                    to: str = CONFIRMED) -> dict:
        """Record that a term is another way of saying a concept the vocabulary already holds — so the next
        document using it is LINKED rather than proposing the same candidate again."""
        if not actor:
            raise ValueError("an amendment is a person's decision: actor is required")
        sc = self._scheme(scheme)
        before = dict(sc.concepts.get(cid) or {})
        sc.amend(cid, alt=alt)
        try:
            written = self._record_curation(scheme, "amended", {"id": cid, "alt": alt, "reason": reason},
                                            actor=actor, method="amend", to=to)
        except Exception:
            # the whole row, not just `alt`: `amend` also sets `curated`, and a seed concept left marked that
            # way would be published as part of the delta by a write the store never took
            sc.concepts[cid] = before
            raise
        # `concept` mirrors what `_admit` answers with, and for the same reason: the caller cannot build
        # the IRI itself (it would need the scheme's base), and the documents that asked for this word
        # have to be linked to something.
        return {"scheme": scheme, "concept_id": cid, "concept": str(sc.uri(cid)), "alt": alt,
                "actor": actor, "rung": to, "assertion": written}

    def vocab_relation_candidates(self, arrows: Iterable[Mapping[str, Any]], *, scheme: str) -> dict:
        """What a structured diagram proposes about the vocabulary's TOPOLOGY — steward B's only feeder.

        The boxes are terms and the arrows are relations, so a diagram is the one artifact that carries how
        the things a corpus is about are CONNECTED, rather than just which they are. Resolution goes through
        `find`, so an alt label works and an AMBIGUOUS term resolves to nothing: choosing between two meanings
        narrows the vocabulary, and that is not a question a diagram may settle.

        It proposes and parks nothing, deliberately. A term candidate arrives one document at a time from many
        documents and has to wait to be batched; a relation candidate is only answerable with the diagram in
        front of the person, and a steward reads these beside it and calls `vocab_relate`. Nothing durable
        means nothing to replay, and no second lifecycle to keep honest.

        Box labels are TERMS, which is what this layer already accepts from a classifier (`vocab_link`) — not
        a document's body, which never crosses this boundary."""
        sc = self._scheme(scheme)

        def resolve(term: str) -> str:
            # `find` folds case and strips, nothing more. A diagram's boxes are hand-authored, so they arrive
            # plural, with an article and wrapped across two lines — each of which became a GAP asking a
            # steward to admit a concept the vocabulary already held, while the relation drawn on it was
            # dropped. The SECOND attempt goes through the classifier's own normaliser, so the two lanes
            # cannot disagree about what a term is.
            hits = {c["id"] for c in sc.find(term)} or {c["id"] for c in sc.find(relations.normalise(term))}
            return next(iter(hits)) if len(hits) == 1 else ""      # ambiguous is not resolved; it is a gap

        def states(subject: str, predicate: str, obj: str) -> bool:
            edges = [e for e in sc.relationships if e["subject"] == subject and e["object"] == obj]
            # An UNNAMED arrow is satisfied by any edge already joining the two: the diagram says they
            # connect, and the vocabulary already says how.
            return bool(edges) if not predicate else any(
                str(e["predicate"]).casefold() == predicate.casefold() for e in edges)

        found, gaps = relations.candidates(arrows, resolve=resolve, states=states)
        return {"scheme": scheme, "candidates": found, "gaps": gaps}

    def graph_not_about(self, iri: str, concept: str, *, actor: str, reason: str = "") -> dict:
        """A PERSON says this record is not about this concept — recorded so it STICKS.

        Retracting the subject was not enough: `G.retract` leaves no trace, so the next classification
        matched the same label, asserted it again at X, and asked the owner the same question. `keep`
        survived every sweep (promotion to H) and `drop` survived until the next read — an asymmetry a
        person cannot see and would not expect.

        The term register already takes the opposite stance for its own negatives — `vocab_decline`, "a
        PERSON'S NO about a term, recorded so it sticks". This is the same answer one level down, about a
        RECORD rather than about the vocabulary, and `vocab_link` subtracts it from what a label match may
        assert. Durable, not permanent: `graph_about_after_all` clears it."""
        if not actor:
            raise ValueError("saying what a document is not about is a person's decision: actor is required")
        self._require(iri)
        _iri_or_raise("concept", concept)
        g = self.ds.graph(CURATED_GRAPH)
        node = URIRef(EXCLUSION + iri_safe(f"{iri}|{concept}"))
        triples = [(node, RDF.type, FAB.SubjectExclusion), (node, FAB.excludedFrom, URIRef(iri)),
                   (node, DCT.subject, URIRef(concept)), (node, G.PROV.wasAttributedTo, Literal(actor)),
                   (node, G.PROV.generatedAtTime, G.now())]
        if reason:
            triples.append((node, FAB.reason, Literal(reason)))
        # RETRACT FIRST. `graph_retract` runs the shape gate and can raise; recording the NO before it
        # would leave a record marked "not about X" while still asserting X, with no undo to compensate.
        # The other order self-heals: a retraction with no NO yet is the behaviour that existed before.
        retracted = self.graph_retract(iri, str(DCT.subject), URIRef(concept), actor=actor,
                                       reason=reason or "the owner said this document is not about it")
        if (node, RDF.type, FAB.SubjectExclusion) not in g:        # idempotent on (record, concept)
            for t in triples:
                g.add(t)
            self._persist(("curated",), lambda: [g.remove(t) for t in triples])
        return {"iri": iri, "concept": concept, "actor": actor, "retracted": bool(retracted)}

    def graph_about_after_all(self, iri: str, concept: str, *, actor: str) -> dict:
        """Clear a record's NO, so a label match may link the concept again.

        A NO is durable, not permanent. Without this one wrong tap would make a record permanently
        un-linkable to a concept, with nothing on screen to explain why the classifier kept ignoring it."""
        if not actor:
            raise ValueError("changing a record's subject exclusion is a person's decision: actor is required")
        _iri_or_raise("concept", concept)
        g = self.ds.graph(CURATED_GRAPH)
        node = URIRef(EXCLUSION + iri_safe(f"{iri}|{concept}"))
        triples = list(g.triples((node, None, None)))
        for t in triples:
            g.remove(t)
        if triples:
            self._persist(("curated",), lambda: [g.add(t) for t in triples])
        return {"iri": iri, "concept": concept, "cleared": bool(triples), "actor": actor}

    def _not_about(self, iri: str) -> set[str]:
        """The concepts a person has said this record is NOT about."""
        g = self.ds.graph(CURATED_GRAPH)
        return {str(o) for n in g.subjects(FAB.excludedFrom, URIRef(iri)) for o in g.objects(n, DCT.subject)}

    def concept_pairs(self, *, min_records: int = 3, limit: int = 20) -> list[dict]:
        """Concepts the CORPUS keeps connecting that the vocabulary says nothing about.

        The second producer for the ontology queue, and the one that works where no diagrams are
        ingested: two concepts turning up on the same documents again and again is the corpus saying they
        are related, and a vocabulary silent about them has a gap a steward can close.

        Evidence, never a conclusion — co-occurrence is not a relation and cannot name one. It proposes
        the QUESTION; a person answers it, because a relation is what the derived rung reasons over.

        Computed in process, over the graph, for the reason `corpus_view` records: a caller doing this
        per record over the gateway pays a round trip each and trips its own rate limit at about sixty.
        Read at `IMPACT_READS`, so a model's suggestion at rung S never proposes a relation.

        Ordered by how often, then by the pair, so two runs agree and a steward sees the strongest first."""
        by_record: dict[str, set[str]] = {}
        for _, (subject, _, obj) in G.find(self.ds, None, DCT.subject, None, rungs=tuple(IMPACT_READS)):
            by_record.setdefault(str(subject), set()).add(str(obj))
        together: dict[tuple[str, str], int] = {}
        for subs in by_record.values():
            for one, two in combinations(sorted(subs), 2):
                together[(one, two)] = together.get((one, two), 0) + 1
        # The vocabulary's own statements, so a pair it already connects is not a gap however often the
        # corpus puts them together. Direction is immaterial here: a relation either way answers it.
        # Every scheme the fabric OWNS, not only those that already state a relation: filtering on a
        # non-empty `relationships` excluded the bootstrap case this producer exists for — a vocabulary
        # whose relation half is empty is precisely where a steward needs the corpus's help.
        stated, by_concept = set(), {}
        for sc in (self._schemes() or {}).values():
            if not hasattr(sc, "relationships"):
                continue                                  # a reference taxonomy the fabric does not curate
            for cid in getattr(sc, "concepts", {}):
                by_concept[str(sc.uri(cid))] = (sc, cid)
            for e in getattr(sc, "relationships", ()) or ():
                stated.add(frozenset((str(sc.uri(e["subject"])), str(sc.uri(e["object"])))))
        out = []
        for (one, two), count in together.items():
            if count < max(1, int(min_records)) or frozenset((one, two)) in stated:
                continue
            if one not in by_concept or two not in by_concept:
                continue                              # a reference concept the fabric does not curate
            sc, left = by_concept[one]
            other_sc, right = by_concept[two]
            if sc is not other_sc:
                continue                              # two vocabularies state nothing about each other
            out.append({"scheme": sc.name, "subject": left, "object": right, "records": count,
                        "evidence": f"{count} records are about both"})
        out.sort(key=lambda r: (-r["records"], r["subject"], r["object"]))
        return out[:max(1, int(limit))]

    def vocab_relation_propose(self, *, scheme: str, subject: str, predicate: str, object: str,
                               evidence: str = "") -> dict:
        """Park a question about how two concepts RELATE, for a steward.

        Modelled on `_conflict`, NOT on `_candidate_for`. A term candidate is parked because it arrives
        one document at a time over weeks and would otherwise be forgotten. A relation candidate is
        RECOMPUTABLE — from a diagram's arrows or from the corpus's co-occurrences — so the candidate
        itself needs no durability. What must survive a restart is that somebody was ASKED and that
        somebody said NO; everything else is derived, which is what keeps the queue from drifting away
        from the vocabulary it is a queue for.

        Idempotent on (scheme, subject, predicate case-folded, object): two producers proposing the same
        relation, or one producer on its second tick, is ONE question. The predicate folds because the
        matcher and the diagram lane both fold it, and "Realises" is not a second question."""
        # The queue that feeds `vocab_relate` must refuse what `vocab_relate` refuses, or it parks a
        # question whose only possible answer raises — and a steward handed a card they cannot answer
        # correctly is worse than no card.
        sc = self._scheme(scheme)
        for end in (subject, object):
            if not str(end or "").strip():
                raise ValueError("a relation question names both concepts")
            if str(end) not in getattr(sc, "concepts", {}):
                raise ValueError(f"{scheme} does not hold a concept {end!r}")
        pred = str(predicate or "").strip()
        if pred and not _LOCAL_NAME.match(pred):
            # A diagram's arrow caption is PROSE ("is realised by"), and `vocab_relate` takes an IRI
            # local name. Parked as the predicate it produced a card whose plain `relate` could only
            # fail; parked as EVIDENCE it produces the right question — "they connect, name how" — with
            # the author's own wording in front of the person answering.
            evidence = f"{evidence + ' · ' if evidence else ''}drawn as {pred!r}"
            pred = ""
        g = self.ds.graph(CURATED_GRAPH)
        key = "|".join([scheme, str(subject), pred.casefold(), str(object)])
        node = URIRef(RELATION_Q + iri_safe(key))
        out = {"iri": str(node), "scheme": scheme, "subject": str(subject), "predicate": pred,
               "object": str(object)}
        if (node, RDF.type, FAB.RelationQuestion) in g:
            return {**out, "already": True}
        triples = [(node, RDF.type, FAB.RelationQuestion), (node, FAB.curationScheme, Literal(scheme)),
                   (node, FAB.relationSubject, Literal(str(subject))),
                   (node, FAB.relationPredicate, Literal(pred)),
                   (node, FAB.relationObject, Literal(str(object))),
                   (node, G.PROV.generatedAtTime, G.now())]
        if evidence:
            triples.append((node, FAB.evidence, Literal(evidence)))
        for t in triples:
            g.add(t)
        self._persist(("curated",), lambda: [g.remove(t) for t in triples])
        return out

    def vocab_relation_open(self) -> list[dict]:
        """The relation questions still waiting on a steward.

        Openness is DERIVED, as a conflict's is: a question disappears exactly when the vocabulary STATES
        the relation — however it came to, through this gate or a republished seed — and a declined one
        stays gone. A marker for "settled" would have to be written by every path that can settle one,
        and the path that forgot would ask a steward the same question for ever."""
        g = self.ds.graph(CURATED_GRAPH)
        out = []
        for node in g.subjects(RDF.type, FAB.RelationQuestion):
            if g.value(node, FAB.lifecycleState) == FAB.Withdrawn:
                continue                                   # a person's NO, recorded so it sticks
            name = str(g.value(node, FAB.curationScheme) or "")
            sub = str(g.value(node, FAB.relationSubject) or "")
            pred = str(g.value(node, FAB.relationPredicate) or "")
            obj = str(g.value(node, FAB.relationObject) or "")
            sc = (self._schemes() or {}).get(name)
            # A NAMED question is DIRECTIONAL — "A contains B" and "B contains A" are different claims and
            # only one was asked. An UNNAMED one is not: `concept_pairs` orders a pair alphabetically and
            # cannot know which way a relation runs, so a relation EITHER way answers it. Without that the
            # queue kept an entry the vocabulary had already settled, which is the one property the
            # derived design was chosen for.
            def settled(e):
                if pred:
                    return (e["subject"] == sub and e["object"] == obj
                            and str(e["predicate"]).casefold() == pred.casefold())
                return {e["subject"], e["object"]} == {sub, obj}

            if sc is not None and any(settled(e) for e in getattr(sc, "relationships", ()) or ()):
                continue                                   # the vocabulary says it now; nobody needs asking
            out.append({"iri": str(node), "scheme": name, "subject": sub, "predicate": pred, "object": obj,
                        "evidence": str(g.value(node, FAB.evidence) or ""),
                        "asked": str(g.value(node, FAB.askedIn) or "")})
        return sorted(out, key=lambda r: (r["subject"], r["predicate"], r["object"]))

    def vocab_relation_decline(self, question: str, *, actor: str, reason: str = "") -> dict:
        """A PERSON says these two concepts are not related that way — recorded so it sticks.

        The sibling of `vocab_decline`. Without it a restart re-asks everything, and both producers
        recompute their candidates on every run, so "not that one" would be answered for ever."""
        if not actor:
            raise ValueError("declining a relation is a person's decision: actor is required")
        g = self.ds.graph(CURATED_GRAPH)
        node = URIRef(question)
        if (node, RDF.type, FAB.RelationQuestion) not in g:
            raise LookupError(f"no relation question {question}")
        triples = [(node, FAB.lifecycleState, FAB.Withdrawn), (node, G.PROV.wasAttributedTo, Literal(actor))]
        if reason:
            triples.append((node, FAB.declineReason, Literal(reason)))
        for t in triples:
            g.add(t)
        self._persist(("curated",), lambda: [g.remove(t) for t in triples])
        return {"iri": question, "declined": True, "actor": actor}

    def vocab_place(self, cid: str, *, scheme: str, parent: str, actor: str, reason: str = "",
                    to: str = CONFIRMED) -> dict:
        """Put an admitted concept under a broader one — steward B's first act.

        `broader` was settable only at proposal time and the batch card deliberately collects no parent, so
        almost every admitted concept arrives unplaced and the hierarchy froze at admission. A person's
        decision, recorded as one: `actor` is refused blank for the same reason a retirement's is."""
        if not actor:
            raise ValueError("a placement is a person's decision: actor is required")
        sc = self._scheme(scheme)
        before = dict(sc.concepts.get(cid) or {})
        placed = sc.place(cid, parent=parent)
        try:
            written = self._record_curation(scheme, "placed", {"id": cid, "parent": parent, "reason": reason},
                                            actor=actor, method="place", to=to)
        except Exception:
            # The row AND the hierarchy. `place` moves a whole SUBTREE, so restoring the one concept it names
            # is not a rollback: measured, a refused persist left a three-deep subtree at depths 4 and 5 while
            # its root was back at 1, and a stale level reaches an agent's prompt through the concept doc
            # string. The older acts (`retire`, `amend`) touch a single row, which is why copying their idiom
            # was the defect. The row restore includes `curated`: a seed concept left marked that way would
            # be published as part of the delta by a write the store never took.
            if before:
                sc.concepts[cid] = before
                sc.levels()
            raise
        return {"scheme": scheme, "concept_id": cid, "concept": str(sc.uri(cid)),
                "parent": placed.get("parent") or "", "level": placed.get("level"),
                "actor": actor, "rung": to, "assertion": written}

    def vocab_relate(self, *, scheme: str, subject: str, predicate: str, object: str, actor: str,
                     cardinality: str = "", note: str = "", to: str = CONFIRMED) -> dict:
        """State how two concepts are connected, with a typed predicate — steward B's second act.

        TYPED, because `skos:related` cannot carry what the derived rung needs: "A is about X, X relates to Y,
        B is about Y" is answerable only if the edge names its predicate."""
        if not actor:
            raise ValueError("a relation is a person's decision: actor is required")
        sc = self._scheme(scheme)
        edge = sc.relate(subject=subject, predicate=predicate, object=object, cardinality=cardinality, note=note)
        # `note` only: `_replay` reads that, and recording the same wording twice invites the two to drift.
        row = {"subject": subject, "predicate": predicate, "object": object,
               "cardinality": cardinality, "note": note}
        try:
            written = self._record_curation(scheme, "related", row, actor=actor, method="relate", to=to)
        except Exception:
            sc.relationships.remove(edge)
            raise
        return {"scheme": scheme, **{k: edge[k] for k in ("subject", "predicate", "object", "cardinality", "note")},
                "actor": actor, "rung": to, "assertion": written}

    def _record_curation(self, scheme: str, act: str, row: Mapping[str, Any], *, actor: str, method: str,
                         to: str) -> str:
        """One curation decision, durably, with who made it. The curated graph is PERSISTED, so a boot that
        rebuilds the seed from its master replays these onto it (`recurate`) instead of losing them."""
        g = self.ds.graph(CURATED_GRAPH)
        node = URIRef(CURATION + ids.ulid())
        triples = [(node, RDF.type, FAB.Curation), (node, FAB.curationAct, Literal(act)),
                   (node, FAB.curationScheme, Literal(scheme)), (node, G.PROV.wasAttributedTo, Literal(actor)),
                   (node, FAB.method, Literal(method)), (node, FAB.rung, Literal(to)),
                   (node, G.PROV.generatedAtTime, G.now())]
        triples += [(node, FAB[k], Literal(v)) for k, v in row.items() if v not in (None, "")]
        for t in triples:
            g.add(t)
        self._persist(("curated",), lambda: [g.remove(t) for t in triples])
        return str(node)

    def _conflict(self, term: str, scheme: str, ids: Iterable[str]) -> dict:
        """One word, several meanings in ONE vocabulary — recorded once for a steward, however many documents
        trip over it.

        Idempotent on (scheme, the term case-folded, the meanings it matched): the same ambiguity met by a
        hundred documents is one decision, and a hundred identical rows would bury the few that differ,
        exactly as an approval backlog does to a channel. Case-folded because `find` matches that way, so
        "Agent" and "agent" are one ambiguity and would otherwise mint two."""
        out = {"term": term, "scheme": scheme, "concepts": sorted(ids)}
        g = self.ds.graph(CURATED_GRAPH)
        key = "|".join([scheme, term.casefold(), *out["concepts"]])
        node = URIRef(CONFLICT + iri_safe(key))
        if (node, RDF.type, FAB.Conflict) in g:
            return out
        triples = [(node, RDF.type, FAB.Conflict), (node, FAB.conflictTerm, Literal(term)),
                   (node, FAB.curationScheme, Literal(out["scheme"])), (node, G.PROV.generatedAtTime, G.now())]
        triples += [(node, FAB.candidateId, Literal(c)) for c in out["concepts"]]
        for t in triples:
            g.add(t)
        self._persist(("curated",), lambda: [g.remove(t) for t in triples])
        return out

    def vocab_candidates(self) -> list[dict]:
        """Terms a run met that the vocabulary has no concept for, and nobody has yet accepted or declined.

        A candidate is OPEN until it is admitted (its lifecycle becomes Published) or the term stops being
        absent — a steward may have settled it by making it another name for a concept already held, which is
        the commonest answer and leaves no candidate to accept. Derived, for the same reason conflict openness
        is: a marker would have to be written by every path that can close one."""
        g = self.ds.graph(CANDIDATES_GRAPH)
        out = []
        for node in g.subjects(RDF.type, SKOS.Concept):
            label = str(g.value(node, SKOS.prefLabel) or "")
            name = str(g.value(node, FAB.candidateScheme) or "")
            state = g.value(node, FAB.lifecycleState)
            if state == FAB.Withdrawn or G.find(self.ds, node, FAB.lifecycleState, FAB.Published):
                continue                     # a steward has answered: admitted, or declined and it STAYS declined
            if self._held_by(label):
                continue      # ANY vocabulary holding it closes the question — not just this candidate's own,
                              # which is what let 25 document-type labels sit here as open subject questions
            # The artifacts that used the word. The COUNT is derived from them rather than stored: it is
            # evidence of how much a term matters (what `FABRIC_CANDIDATE_THRESHOLD` reads), and admitting
            # the concept re-matches exactly these (FR-1.1.5) instead of the whole catalogue. A row from
            # before this existed names none, and is still one proposal — it was proposed at least once.
            for_them = sorted(str(o) for o in g.objects(node, FAB.proposedFor))
            asked = state == FAB.InReview
            out.append({"iri": str(node), "label": label, "scheme": name,
                        "concept_id": str(g.value(node, FAB.candidateId) or ""),
                        "definition": str(g.value(node, SKOS.definition) or ""),
                        # The concept a matcher thinks this is a WORD FOR, when one was found. It turns
                        # the card's expensive question ("what does it mean and where does it sit?") into
                        # the cheap one ("is this another word for X?"), which is the difference between
                        # a steward answering eight terms and a steward answering one.
                        "alias_of": str(g.value(node, FAB.aliasOf) or ""),
                        # NOT RECORDED is not ONE. A row written before `proposedFor` existed carries no
                        # artifacts, and defaulting it to 1 silenced the entire back catalogue at any
                        # threshold above one — measured live 10 Oct 2026, the moment this deployed: all 46
                        # surviving candidates reported `1` and NONE would have been pushed. The test for
                        # exactly this regression passed throughout, because it asserted on an ABSENT count
                        # while the derivation was busy inventing one.
                        "proposed_for": for_them, "proposals": len(for_them) if for_them else None,
                        "asked": asked,
                        "proposed_by": str(g.value(node, G.PROV.wasAttributedTo) or "")})
        return sorted(out, key=lambda c: c["label"])

    def vocab_conflicts(self) -> list[dict]:
        """Ambiguities a steward has not settled — what the gate asks about.

        Openness is DERIVED from the vocabulary, never from a marker: a conflict is settled exactly when the
        term no longer matches more than one LIVE concept, which is true whether the steward retired a meaning
        or made the term another name for one. A marker would have to be written by every path that can settle
        one — and the path that forgot would re-ask the steward, with a fresh approval id, on every restart
        forever."""
        g = self.ds.graph(CURATED_GRAPH)
        out = []
        for node in g.subjects(RDF.type, FAB.Conflict):
            term = str(g.value(node, FAB.conflictTerm) or "")
            name = str(g.value(node, FAB.curationScheme) or "")
            sc = (self._schemes() or {}).get(name)
            if sc is not None and len({c["id"] for c in sc.find(term)}) < 2:
                continue                                   # the ambiguity is gone; nobody needs asking
            out.append({"iri": str(node), "term": term, "scheme": name,
                        # The request a steward was already asked in, "" when nobody has been. Openness is
                        # still DERIVED (above); askedness is recorded, because it cannot be re-derived.
                        "asked": str(g.value(node, FAB.askedIn) or ""),
                        "concepts": sorted(str(o) for o in g.objects(node, FAB.candidateId))})
        return sorted(out, key=lambda c: c["term"])

    def _replay(self, act: str, node: URIRef, sc) -> bool:
        """One recorded decision onto a scheme. True when it changed something, False when it was already
        there — the two are different answers and a boot line that conflated them could not tell a quiet
        replay from a lost one."""
        g = self.ds.graph(CURATED_GRAPH)
        cid = str(g.value(node, FAB.id) or "")
        if act == "admitted":
            if cid in sc.concepts:
                return False
            sc.admit(id=cid, label=str(g.value(node, FAB.label) or ""),
                     definition=str(g.value(node, FAB.definition) or ""),
                     parent=str(g.value(node, FAB.parent) or "") or None,
                     module=str(g.value(node, FAB.module) or ""))
            return True
        if act == "amended":
            alt = str(g.value(node, FAB.alt) or "")
            if alt.casefold() in {a.casefold() for a in (sc.concepts.get(cid) or {}).get("alt") or []}:
                return False
            sc.amend(cid, alt=alt)
            return True
        if act == "placed":
            parent = str(g.value(node, FAB.parent) or "")
            held = sc.concepts.get(cid) or {}
            if (held.get("parent") or "") == parent:
                return False
            sc.place(cid, parent=parent)
            return True
        if act == "related":
            edge = {k: str(g.value(node, FAB[k]) or "") for k in ("subject", "predicate", "object")}
            if any(e["subject"] == edge["subject"] and e["predicate"] == edge["predicate"]
                   and e["object"] == edge["object"] for e in sc.relationships):
                return False
            sc.relate(**edge, cardinality=str(g.value(node, FAB.cardinality) or ""),
                      note=str(g.value(node, FAB.note) or ""))
            return True
        if act == "retired":
            if (sc.concepts.get(cid) or {}).get("retired"):
                return False
            sc.retire(cid, resolves_to=str(g.value(node, FAB.resolves_to) or ""),
                      reason=str(g.value(node, FAB.reason) or ""))
            return True
        raise ValueError(f"unknown curation act {act!r}")

    def recurate(self) -> dict:
        """Replay the curated delta onto the schemes as they stand — the boot path.

        The seed is rebuilt from its master at every start, so the scheme object is NEW and knows nothing a
        steward decided. Three properties this needs, each learned the hard way:

        ORDER. Admissions are replayed FIRST and in passes, because one may name another as its parent and the
        recorded timestamps are only second-resolution — two decisions in the same second tie, and the tie
        would be broken by rdflib's iteration order, i.e. arbitrarily. Passes repeat while progress is made,
        so parent-before-child stops mattering at all.

        SURVIVAL. This runs inside `boot()`, and `admit` refuses a row it cannot place. One malformed row must
        not stop a service from starting — it would refuse identically on every restart, with the bad row
        still in the store, which is the opposite of what a replay is for. So a row that cannot be applied is
        COUNTED and NAMED and the rest go on.

        HONESTY. `skipped` and `failed` are reported beside the successes: a replay that silently dropped
        three decisions and one that had nothing to do both return zeros otherwise, and the scheme is wrong
        in exactly one of those cases."""
        g = self.ds.graph(CURATED_GRAPH)
        counts = {"admitted": 0, "amended": 0, "placed": 0, "related": 0, "retired": 0,
                  "skipped": 0, "failed": 0}
        rows = [(str(g.value(n, FAB.curationAct) or ""), n) for n in g.subjects(RDF.type, FAB.Curation)]
        # (time, node) so a tie is at least DETERMINISTIC; ULIDs are monotonic per process, not across them
        rows.sort(key=lambda r: (str(g.value(r[1], G.PROV.generatedAtTime) or ""), str(r[1])))
        pending = [r for r in rows if r[0] == "admitted"] + [r for r in rows if r[0] != "admitted"]
        while pending:
            progressed, deferred = False, []
            for act, node in pending:
                name = str(g.value(node, FAB.curationScheme) or "")
                sc = (self._schemes() or {}).get(name)
                if sc is None:
                    print(f"[fabric] curation for an absent vocabulary {name!r} left unapplied", flush=True)
                    counts["skipped"] += 1
                    continue
                try:
                    applied = self._replay(act, node, sc)
                except Exception as e:                    # noqa: BLE001 — one bad row must never stop a boot
                    deferred.append((act, node, f"{type(e).__name__}: {e}"))
                    continue
                counts[act if applied else "skipped"] += 1
                progressed = progressed or applied
            if not progressed:
                for act, node, why in deferred:           # nothing left can make these applicable
                    print(f"[fabric] curation {node} ({act}) could not be replayed: {why}", flush=True)
                counts["failed"] += len(deferred)
                break
            pending = [(a, n) for a, n, _ in deferred]
        return counts

    # ---------------------------------------------------------------- facade

    def _need_embedder(self):
        if self.embedder is None:
            raise RuntimeError("no embedder is configured for the fabric (REFERENCE_EMBED_MODEL) — "
                               "exact lookup and the graph still answer; similarity does not")
        return self.embedder

    # ------------------------------------------ the semantic tier of the inverted classifier
    #: Measured on live records, 17 Oct 2026. A term scoring below the FLOOR is a bad answer; a term whose
    #: top two are within the MARGIN is an arbitrary one, which is the failure an absolute threshold
    #: cannot see — 'proposed decision status' ranked top against *Prior authorisation* at a margin of
    #: 0.0016. Accepted matches on the eRx set scored 0.36-0.52 with margins of 0.08-0.13.
    MATCH_FLOOR, MATCH_MARGIN = 0.30, 0.05

    def _live_concepts(self, sc) -> dict:
        """A scheme's concepts a term may match, BY ID — never a retired one. `find()` stops offering
        those, and a vector that outlived the retirement would keep matching a meaning a steward withdrew.

        Both shapes are normalised here because the two kinds of scheme answer differently: a
        `DomainScheme` — the vocabulary the fabric OWNS — has `live()` and returns a LIST, while a
        reference scheme has no `live()` and keeps a dict. Returning whichever came back made every caller
        a coin toss: `.items()` on the list raised, so `semantic_concept_match` and `index_concepts` both
        failed on EVERY call against the only vocabulary the fabric curates — and the intake swallows that
        error by design, so tier 2 was silently dead while eighteen candidates came off three documents
        with not one alias proposed (measured in UAT, 20 Oct 2026)."""
        live = getattr(sc, "live", None)
        rows = live() if callable(live) else list((getattr(sc, "concepts", {}) or {}).values())
        return {str(c.get("id")): c for c in rows if c.get("id")}

    def index_concepts(self, scheme: str = "") -> dict:
        """Embed the DEFINITIONS of a scheme's live concepts that this model's space does not hold yet.

        Lazily, never at boot: `boot()` is synchronous and runs before the server listens, so an embedder
        that is slow or flapping would stop semantic-mcp starting at all — taking `catalog_get`, `impact`
        and every view with it. Tier 2 being unavailable is a degradation; the fabric not starting is an
        outage.

        Only what is MISSING, because this runs on the path of a single term and must not re-embed a
        whole vocabulary to answer it. A model change makes everything missing at once, which is the
        correct amount of work and needs no second bookkeeping table."""
        emb = self._need_embedder()
        names = [scheme] if scheme else list(self._schemes() or {})
        done = 0
        for name in names:
            sc = (self._schemes() or {}).get(name)
            if sc is None:
                continue
            have = self.catalog.indexed_concepts(name, emb.model)
            missing = [(cid, c) for cid, c in self._live_concepts(sc).items()
                       if str(sc.uri(cid)) not in have]
            if not missing:
                continue
            # label AND definition: the label alone is what tier 1 already matches on, so a vector of it
            # would make tier 2 a fuzzy repeat of tier 1 rather than a different question.
            texts = [f"{c.get('label') or cid}. {c.get('definition') or ''}".strip() for cid, c in missing]
            for (cid, _c), vec in zip(missing, emb.embed(texts, purpose="document")):
                self.catalog.put_concept_embedding(str(sc.uri(cid)), vec, emb.model, scheme=name)
                done += 1
        return {"indexed": done, "model": emb.model, "schemes": names}

    def concept_match(self, term: str, *, scheme: str = "", floor: float | None = None,
                      margin: float | None = None, limit: int = 5) -> dict:
        """The concept a term MEANS, or nothing — the tier that runs when no label matched it lexically.

        Nothing is the ordinary answer, not a failure: the term becomes a candidate concept for a
        steward, which is how the vocabulary learns what the corpus needed and it did not have. Measured
        17 Oct 2026, 19 of 30 terms on real documents fell through this way, and the rejected ones include
        `dead-letter handling rota -> Migration disposition`, which is nonsense nobody should have to
        notice on a review card.

        An absent embedder answers `unavailable`, never a bare miss. The two must stay distinguishable:
        'the vocabulary has no such concept' is a claim about the corpus, and 'I could not ask' is a claim
        about the deployment."""
        if self.embedder is None:
            return {"term": term, "concept": "", "label": "", "score": 0.0, "margin": 0.0,
                    "scheme": scheme, "unavailable": True}
        emb = self.embedder
        self.index_concepts(scheme)
        probe = concepts.normalise(term)
        vector = emb.embed([probe], purpose="query")[0]
        ranked = self.catalog.concept_similar(vector, model=emb.model, limit=max(2, int(limit)))
        scores = [{"id": c, "score": s} for c, s in ranked]
        hit = concepts.match(scores, floor=self.MATCH_FLOOR if floor is None else floor,
                             margin=self.MATCH_MARGIN if margin is None else margin)
        top = ranked[0][1] if ranked else 0.0
        gap = (ranked[0][1] - ranked[1][1]) if len(ranked) > 1 else top
        label = ""
        if hit:
            for name, sc in (self._schemes() or {}).items():
                for cid, c in self._live_concepts(sc).items():
                    if str(sc.uri(cid)) == hit:
                        label, scheme = (c.get("label") or cid), name
                        break
        return {"term": term, "concept": hit or "", "label": label, "score": round(top, 4),
                "margin": round(gap, 4), "scheme": scheme, "unavailable": False}

    def embed(self, iri: str, text: str) -> dict:
        """Index an artifact by its DESCRIPTIVE text (title · type · subjects) — never its body."""
        self._require(iri)
        emb = self._need_embedder()
        vector = emb.embed([text], purpose="document")[0]        # the gateway embedder's asymmetric sides
        self.catalog.put_embedding(iri, vector, emb.model)
        return {"iri": iri, "model": emb.model, "dim": len(vector)}

    def _ranked(self, vector: list[float], limit: int, exclude: str = "") -> list[dict]:
        """Ranked within the CURRENT embedder's space: vectors indexed under another model are not compared."""
        model = getattr(self.embedder, "model", "") or ""
        out = []
        for iri, score in self.catalog.similar(vector, limit, exclude=exclude, model=model):
            row = self.catalog_get(iri)
            if row is not None:
                out.append({**row, "score": score})
        # a TEXT query that finds nothing while rows exist outside this space: the index is empty for this
        # embedder — say so, never []. (By iri the source itself is in the space, so an empty answer is real.)
        if not out and not exclude and self.catalog.unindexed(model):
            raise RuntimeError(f"no artifact is indexed in {model}'s space — the embedder changed; "
                               "call semantic_reindex")
        return out

    def similar(self, *, iri: str = "", text: str = "", limit: int = 5) -> list[dict]:
        if iri:
            found = self.catalog.embedding(iri)
            if found is None:
                raise LookupError(f"{iri} is not indexed")
            return self._ranked(found[0], limit, exclude=iri)
        if text:
            vector = self._need_embedder().embed([text], purpose="query")[0]
            return self._ranked(vector, limit)
        raise ValueError("similar needs an iri or a text")

    def search(self, text: str, *, limit: int = 10, document_type: str = "", state: str = "") -> list[dict]:
        """The facade: the index filtered by facets. A withdrawn record is not knowledge any more, so it is
        hidden unless that state is asked for — `similar` stays the raw index."""
        hits = self.similar(text=text, limit=limit * 4)      # over-fetch, then filter by facet
        if document_type:
            hits = [h for h in hits if h["document_type"] == document_type]
        hits = [h for h in hits if h["state"] == state] if state else [h for h in hits if h["state"] != "withdrawn"]
        return hits[:limit]

    def _relational_schemes(self) -> list[Any]:
        """The vocabularies that declare their own relationship TYPES — the only ones that can state how two
        concepts are connected. A capability map is a hierarchy: unioning its 1,600 concepts in would cost a
        derivation everything and tell it nothing, and would put a thousand siblings on a picture. ONE home,
        because a derivation that reads several while a drawing reads one draws edges it cannot explain."""
        return [sc for sc in (self._schemes() or {}).values() if getattr(sc, "relationships", None)]

    def derive(self) -> dict:
        """Rebuild the derived rung D from the trusted rungs (two rules, `derive.RULES`) and persist it. Counts only.
        On a persist failure D is left EMPTY in memory (not restored to the previous derivation): D is recomputed,
        never asserted, so an empty D is honest until the next derivation, where a stale one would not be."""
        vocab = [URIRef(f"urn:lab:semantic:vocab:{sc.name}") for sc in self._relational_schemes()]
        out = DR.derive(self.ds, vocabulary=vocab)
        self._persist((DERIVED, "prov"), lambda: DR.clear(self.ds))
        return out

    def topology(self, iri: str, *, ontology_ring: bool = True, proposed: Iterable[str] = (),
                 as_of: str = "") -> TopologyView:
        """What this record is about, and what that connects it to — as the graph stands NOW.

        The fabric builds the view because only it knows which rung each link was made at; a renderer
        turns it into something a person can open and never learns what a rung is. `proposed` are terms
        this record used that the vocabulary has no concept for: they are the caller's, because a
        candidate is parked without a record to blame, and a gap a person can see is one a steward can
        close."""
        row = self.catalog_get(iri)
        if row is None:
            raise LookupError(f"no catalog record {iri}")
        # relatedTo on the TRUSTED rungs only: a derived neighbour is worth drawing, a suggested one is a
        # model's guess and drawing it beside a confirmed fact is how a picture stops being evidence.
        related = [{**h, "predicate": _short(FAB.relatedTo)}
                   for h in self.graph_traverse(iri, [str(FAB.relatedTo)], rungs=list(IMPACT_READS), depth=1)
                   if h["iri"] != iri]
        # The SAME schemes the derivation reads, so the picture can always explain the edges the derivation made.
        return topology.view_of(row, schemes=self._relational_schemes(), related=related, proposed=proposed,
                                as_of=as_of, ontology_ring=ontology_ring)

    def corpus_view(self, *, state: str = "", limit: int = 2000, as_of: str = "") -> TopologyView:
        """The WHOLE catalogue in one picture: every record that is about something, the concepts they
        share, and the vocabulary's own edges between those.

        Walked in page order through the same keyset the bulk tools use, and resolved IN PROCESS: a
        caller doing this over the gateway pays a round trip per record and trips its own rate limit at
        about sixty (measured, 10 Oct 2026). `limit` is a ceiling on records READ, not on what is drawn
        — a record with no subject is counted and left out by the view, which is where that rule belongs.

        The same schemes as `topology`, for the same reason: a picture that could not explain its own
        edges would be decoration."""
        rows, after = [], ""
        while len(rows) < limit:
            page = self.catalog_page(after=after, limit=min(200, limit - len(rows)), state=state)
            if not page:
                break
            for entry in page:
                row = self.catalog_get(entry.iri)
                if row:
                    rows.append(row)
            after = page[-1].iri
        return corpus.view_of_corpus(rows, schemes=self._relational_schemes(), as_of=as_of)

    def related(self, iri: str, *, limit: int = 20, state: str = "") -> list[dict]:
        """What else the corpus is ABOUT this record — ranked by the rarest concept shared, not by how many.

        The complement of `similar`, which proposes neighbours from an embedding of a record's facets and so
        answers "what reads like this". This answers "what is about the same thing", from assertions a person
        or a derivation stands behind, and it names the concept that earned each rank — the part a researcher
        can check.

        Specificity is computed HERE, per call, and never stored on the assertion: a concept that
        distinguished a document among forty stops distinguishing it among four thousand, and a number frozen
        at assert time would keep insisting otherwise. The population is the records that are about something
        at all, since a record with no subject is not one this concept failed to distinguish.

        **A link worth nothing is not returned.** A concept carried by every record in the population scores
        exactly zero — it would relate all of them to each other with equal confidence and tell a reader
        nothing. The filter is already computed, so returning those rows would mean padding one answer with
        thirty-six non-answers that a caller, and especially a model, cannot tell apart from the answer. The
        consequence is deliberate: in a corpus whose every record shares one subject, that subject relates
        nobody, and an empty answer is the honest one.

        Read at `IMPACT_READS` — the rungs the derivation and the topology picture trust — so a model's
        suggestion at rung S never ranks as a relation. ONE in-process scan of the subject assertions serves
        both the shared sets and the document frequencies; the catalogue is then read for the survivors only,
        AFTER ranking and truncation, so the cost is `limit` reads and not one per candidate (the store is
        Postgres in the cloud, where per-candidate would be a round trip each).

        A withdrawn record is hidden unless that state is asked for, exactly as in `search`: the same corpus
        must not answer "what reads like this" without it and "what is about the same thing" with it."""
        limit = max(1, min(int(limit), 100))      # a ceiling, as `corpus_view` has, so one call cannot hydrate the estate
        by_record: dict[str, set[str]] = {}
        for _, (subject, _, obj) in G.find(self.ds, None, DCT.subject, None, rungs=tuple(IMPACT_READS)):
            by_record.setdefault(str(subject), set()).add(str(obj))
        mine = by_record.get(iri)
        if not mine:
            return []
        frequency: dict[str, int] = {}
        for subs in by_record.values():
            for c in subs:
                frequency[c] = frequency.get(c, 0) + 1
        ranked = []
        for other, subs in by_record.items():
            shared = sorted(mine & subs)
            if other == iri or not shared:
                continue
            via, score = concepts.rarest(shared, frequency, total=len(by_record))
            if score <= 0.0:                      # a concept everything carries is not a relation
                continue
            ranked.append({"iri": other, "score": score, "via": via, "shared": shared,
                           "via_kind": "shared"})
        ranked += self._derived_neighbours(iri, mine, by_record, frequency, seen={r["iri"] for r in ranked})
        # KIND, then score, then IRI. A record about the same concept is about the same THING; a derived
        # neighbour is about something the vocabulary says is CONNECTED to it — both are evidence and one is
        # stronger, so they are ordered by kind rather than by a discount factor nobody could justify. Within
        # a kind, specificity. Sorted BEFORE the catalogue is touched — see the docstring on cost.
        ranked.sort(key=lambda r: (0 if r["via_kind"] == "shared" else 1, -r["score"], r["iri"]))
        out = []
        for row in ranked:
            if len(out) >= limit:
                break
            entry = self.catalog.get(row["iri"])
            # A subject assertion whose record the catalogue does not hold is a divergence, not a document to
            # offer: a nameless row in an answer about documents is worse than one row fewer.
            if entry is None or (entry.state == "withdrawn" if not state else entry.state != state):
                continue
            out.append({**row, "state": entry.state, "title": entry.title or "",
                        "via_label": self._concept_label(row["via"]),
                        **({"via_object_label": self._concept_label(row["via_object"])}
                           if row.get("via_object") else {}),
                        # Every shared concept by its label, not just the winner: a reader checking WHY two
                        # records are related should not be handed one readable concept and N hashed ids.
                        "shared": [{"concept": c, "label": self._concept_label(c)} for c in row["shared"]]})
        return out

    def _derived_neighbours(self, iri: str, mine: set[str], by_record: dict[str, set[str]],
                            frequency: dict[str, int], *, seen: set[str]) -> list[dict]:
        """Records the ONTOLOGY connects to this one — about no concept in common, but about concepts the
        vocabulary states are related.

        The case the whole thing exists for: a document about `Prescription`, a spreadsheet about
        `Prescription item`, and `Prescription contains Prescription item` in the vocabulary. A ranking by
        shared concepts returns nothing; the two are plainly about connected things.

        The edge is READ from rung D, not re-derived here — `derive.RULES` keeps one home for the rule, and
        its `?p a rdf:Property` filter is what stops `skos:broader` from making every branch of the taxonomy
        a false neighbourhood. But D's provenance records only the NEAR concept (`wasDerivedFrom`); the far
        concept and the predicate that joined them are selected and discarded, so they are recovered here by
        intersecting the vocabulary's own `relations_of` with the other record's subjects. Without that a
        reader is told two records are related and never which statement says so.

        Read through `G.traverse` rather than `self.graph_traverse`, deliberately: the latter hydrates every
        hop from the catalogue, which would read the store for candidates this method may never return.

        Costs nothing when the derivation has not run — and it only runs on a publish, so a record that has
        never been published has no derived neighbours. Quieter, never wrong."""
        if not self._relational_schemes():
            return []                                  # no vocabulary states relations; D holds no concept paths
        hops = {str(node) for node, _, _ in G.traverse(self.ds, URIRef(iri), (FAB.relatedTo,),
                                                       rungs=(DERIVED,), depth=1)}
        out = []
        for other in sorted(hops - seen - {iri}):
            theirs = by_record.get(other) or set()
            path = self._concept_path(mine, theirs)
            if path is None:
                # A relatedTo at D that no concept path explains: the OTHER derivation rules
                # (`references-context`, `synthesised-context`) write the same predicate, and those are
                # causal links `impact` already reports. Not this answer's business.
                continue
            near, predicate, far = path
            # The rarer END of the path. A path through two concepts the whole corpus carries says as little
            # as a shared concept the whole corpus carries, and is dropped by the same rule.
            _, score = concepts.rarest([near, far], frequency, total=len(by_record))
            if score <= 0.0:
                continue
            out.append({"iri": other, "score": score, "via": near, "via_predicate": predicate,
                        "via_object": far, "shared": [], "via_kind": "derived"})
        return out

    def _concept_path(self, mine: set[str], theirs: set[str]) -> tuple[str, str, str] | None:
        """The vocabulary statement joining one of MY concepts to one of THEIRS — (near, predicate, far).

        `relations_of` is the authoritative answer to "which concepts are related, and how" and is what both
        drawing paths already use, so the explanation a reader gets here is the one the picture draws.
        Ordered by concept id so two calls agree."""
        for sc in self._relational_schemes():
            for near in sorted(mine):
                head = str(near).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                if head not in getattr(sc, "concepts", {}):
                    continue
                for predicate, other, _direction in sc.relations_of(head):
                    if str(sc.uri(other)) in theirs:
                        return str(near), str(predicate), str(sc.uri(other))
        return None

    def _concept_label(self, concept: str) -> str:
        """A concept reads by its label — a reference concept's id is a hash of its label path. One home for
        resolving that ON THE DATASET; the scheme, candidate and vocabulary graphs are read where they are
        trusted, deliberately not folded in here."""
        label = self.ds.value(URIRef(concept), SKOS.prefLabel) if concept else None
        return str(label) if label is not None else ""

    def recommend(self, text: str, *, limit: int = 5) -> list[dict]:
        """"Before you create": what already exists, PUBLISHED, on this topic — with its owner, so a person
        reuses or asks instead of writing a twin (BR-4)."""
        return self.search(text, limit=limit, state="published")

    def reindex(self) -> dict:
        """Embed every row the CURRENT embedder's space lacks, from its facets (`describe`). This is what a
        switched embedder costs the fabric: one call, no content — the vectors are derived, the catalog is
        the source. A row the embedder refuses is counted and skipped, never the end of the sweep."""
        emb = self._need_embedder()
        indexed, skipped, reason = 0, 0, ""
        for e in self.catalog.unindexed(emb.model):
            row = self.catalog_get(e.iri) or {}
            try:
                self.embed(e.iri, describe(e.title, e.document_type, subject_labels(row.get("links") or [])))
                indexed += 1
            except Exception as exc:                         # noqa: BLE001 — one refused row, one count
                skipped += 1
                reason = reason or f"{type(exc).__name__}: {exc}"   # the FIRST cause travels with the report
        return {"model": emb.model, "indexed": indexed, "skipped": skipped, **({"reason": reason} if reason else {})}

    # ----------------------------------------------------------- persistence

    def snapshot(self, name: str) -> str:
        return G.graph_nquads(self.ds, PERSISTED_GRAPHS[name])

    def restore(self, texts: Iterable[str]) -> int:
        return sum(G.load_nquads(self.ds, t) for t in texts)


__all__ = ["FabricService", "term", "FACETS", "PERSISTED_GRAPHS", "DCAT"]
