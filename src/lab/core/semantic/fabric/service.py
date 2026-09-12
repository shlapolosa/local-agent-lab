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
from typing import Any, Callable, Iterable, Mapping

from rdflib import RDF, Dataset, Literal, URIRef
from rdflib.namespace import Namespace

from lab.core import ids
from lab.core.delivery import DeliveryContext
from lab.core.semantic.fabric import graph as G
from lab.core.semantic.fabric import shapes
from lab.core.semantic.fabric.catalog import (FIELDS, STATE_IRI, STATES, Catalog, CatalogEntry, MAX_TITLE, describe,
                                              iri_safe, pointer_key, subject_labels)
from lab.core.semantic.fabric.ontology import DocumentTypes, short as _short
from lab.core.semantic.fabric.rungs import (CANDIDATES_GRAPH, CONFIRMED, CONSTRUCTED, EXTRACTED, GRAPH_RUNGS,
                                             PROV_GRAPH, graph_iri)

FAB, DCT, SKOS = G.FAB, G.DCT, G.SKOS
DCAT = Namespace("http://www.w3.org/ns/dcat#")
CANDIDATE = "urn:fabric:candidate:"
DOC_TYPE_SCHEME = "urn:fabric:scheme:doc-types#"
PERSON = "urn:fabric:person:"
#: What an IRI looks like HERE: a URN, or a scheme with an authority (`art://`, `collab://`, `https://`). A
#: bare `word:word` is a label — `09:00`, `Confidential:Internal` — however scheme-shaped its first token.
_IRI = re.compile(r"^(urn:[a-z0-9][a-z0-9-]*:|[a-z][a-z0-9+.-]*://)\S+$", re.I)


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
FACETS: dict[str, tuple[URIRef, Callable[[Any], URIRef | Literal]]] = {
    "document_type": (FAB.documentType, _prefixed(DOC_TYPE_SCHEME, "document_type")),
    "owner": (FAB.ownedBy, _prefixed(PERSON, "owner")),
    "sensitivity_label": (FAB.sensitivityLabel, lambda v: Literal(str(v))),
}
#: the identity facts mirrored into graph C on upsert — set, not asserted (they ARE the catalog row), so a
#: caller may never retract one edge-wise: `catalog_state` moves them.
_MIRRORED = (RDF.type, DCT.title, DCAT.accessURL, FAB.lifecycleState, FAB.producedBy, FAB.sourceKind,
             FAB.baselineVersion, FAB.unassociated)
#: the edges `catalog_get` reports beside the row
_LINKS = (FAB.deliveredUnder, FAB.references, DCT.subject, FAB.documentType, FAB.ownedBy, FAB.sensitivityLabel)
#: persisted name -> named graph: the five rungs, the PROV records, the candidates
PERSISTED_GRAPHS: dict[str, URIRef] = {"prov": PROV_GRAPH, "candidates": CANDIDATES_GRAPH,
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
            label = self.ds.value(o, SKOS.prefLabel) if isinstance(o, URIRef) else None
            if label is not None:                     # a concept reads by its label, not its hashed id
                link["label"] = str(label)
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
        return entry.to_dict()

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
                        "state": e.state if e else ""})
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
        label match is extracted, not guessed. Misses are what `vocab_propose` is for."""
        self._require(iri)
        available = self._schemes()
        chosen = {n: sc for n, sc in available.items() if not schemes or n in schemes}
        linked, missed = [], []
        for t in terms:
            hits = [(n, sc, c) for n, sc in chosen.items() for c in sc.find(t)]
            if not hits:
                missed.append(t)
                continue
            for n, sc, c in hits:
                concept = sc.uri(c["id"])
                self.graph_assert(iri, str(DCT.subject), concept, rung=EXTRACTED, method="label-match")
                linked.append({"term": t, "scheme": n, "concept": str(concept), "label": c["label"]})
        return {"linked": linked, "missed": missed}

    def vocab_propose(self, label: str, *, definition: str = "", actor: str, broader: str = "") -> dict:
        """Park a candidate concept for a steward (the candidates graph is not a scheme: a steward accepts
        it with `promote`, which records the acceptance at rung H)."""
        if not str(label or "").strip():
            raise ValueError("a candidate has a label")
        if not actor:
            raise ValueError("a proposal names who proposed it")
        c = URIRef(CANDIDATE + ids.ulid())
        g = self.ds.graph(CANDIDATES_GRAPH)
        g.add((c, RDF.type, SKOS.Concept)); g.add((c, SKOS.prefLabel, Literal(label.strip())))
        g.add((c, G.PROV.wasAttributedTo, Literal(actor)))
        if definition:
            g.add((c, SKOS.definition, Literal(definition)))
        if broader:
            g.add((c, SKOS.broader, URIRef(broader)))
        self._persist(("candidates",), lambda: g.remove((c, None, None)))
        return {"iri": str(c), "label": label.strip()}

    # ------------------------------------------------------------------ gate

    def promote(self, subject: str, predicate: str = "", obj: Any = None, *, actor: str, method: str,
                to: str = CONFIRMED) -> dict:
        """A person's decision. With a predicate: move that assertion up the ladder. Without one: accept a
        candidate concept (its acceptance is a confirmed assertion on the candidate)."""
        if not actor:
            raise ValueError("a promotion is a person's decision: actor is required")
        s = URIRef(subject)
        if not predicate:
            if (s, RDF.type, SKOS.Concept) not in self.ds.graph(CANDIDATES_GRAPH):
                raise LookupError(f"{subject} is not a candidate concept")
            r = self.graph_assert(subject, str(FAB.lifecycleState), FAB.Published, rung=to, method=method,
                                  actor=actor, supersede=True)
            return {**r, "from": "candidates"}
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

    # ---------------------------------------------------------------- facade

    def _need_embedder(self):
        if self.embedder is None:
            raise RuntimeError("no embedder is configured for the fabric (REFERENCE_EMBED_MODEL) — "
                               "exact lookup and the graph still answer; similarity does not")
        return self.embedder

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
