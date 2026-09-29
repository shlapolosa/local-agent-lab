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
from lab.core.viz import TopologyView
from lab.core.semantic.fabric import derive as DR
from lab.core.semantic.fabric import graph as G
from lab.core.semantic.fabric import shapes
from lab.core.semantic.fabric import topology
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
_LINKS = (FAB.deliveredUnder, FAB.references, FAB.duplicateOf, FAB.relatedTo, FAB.synthesisedFrom, DCT.subject, FAB.documentType,
          FAB.ownedBy, FAB.sensitivityLabel)
#: persisted name -> named graph: the five rungs, the PROV records, the candidates
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
        label match is extracted, not guessed. Misses are what `vocab_propose` is for."""
        self._require(iri)
        available = self._schemes()
        chosen = {n: sc for n, sc in available.items() if not schemes or n in schemes}
        linked, missed, conflicts = [], [], []
        for t in terms:
            hits = [(n, sc, c) for n, sc in chosen.items() for c in sc.find(t)]
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
                self.graph_assert(iri, str(DCT.subject), concept, rung=EXTRACTED, method="label-match")
                linked.append({"term": t, "scheme": n, "concept": str(concept), "label": c["label"]})
        return {"linked": linked, "missed": missed, "conflicts": conflicts}

    def vocab_propose(self, label: str, *, definition: str = "", actor: str, broader: str = "",
                      scheme: str = "", concept_id: str = "", module: str = "") -> dict:
        """Park a candidate concept for a steward (the candidates graph is not a scheme: a steward accepts
        it with `promote`, which records the acceptance at rung H).

        `scheme` is the vocabulary it would join and `concept_id` the id it would take — both optional here and
        both REQUIRED by the time it is admitted, because a concept with no home cannot be looked up and an id
        is what every consumer joins on. Left out, the steward supplies them at the gate."""
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
        if scheme:
            g.add((c, FAB.candidateScheme, Literal(scheme)))
        if concept_id:
            g.add((c, FAB.candidateId, Literal(concept_id)))
        if module:
            g.add((c, FAB.candidateModule, Literal(module)))
        self._persist(("candidates",), lambda: g.remove((c, None, None)))
        return {"iri": str(c), "label": label.strip(), "scheme": scheme, "concept_id": concept_id,
                "module": module}

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
        return {"scheme": scheme, "concept_id": cid, "alt": alt, "actor": actor, "rung": to,
                "assertion": written}

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
            if G.find(self.ds, node, FAB.lifecycleState, FAB.Published):
                continue                                   # admitted already
            sc = (self._schemes() or {}).get(name)
            if sc is not None and sc.find(label):
                continue                                   # the term means something now; nobody needs asking
            out.append({"iri": str(node), "label": label, "scheme": name,
                        "concept_id": str(g.value(node, FAB.candidateId) or ""),
                        "definition": str(g.value(node, SKOS.definition) or ""),
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
        counts = {"admitted": 0, "amended": 0, "retired": 0, "skipped": 0, "failed": 0}
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
