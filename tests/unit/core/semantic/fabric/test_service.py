"""FabricService — the four products over one Dataset and one Catalog, offline. Every write lands in a rung
graph WITH provenance, is SHACL-checked, and is reported to the persistence hook; a violation is undone."""
import pytest
from rdflib import RDF, Dataset, Literal, URIRef

from fixtures.embed import HashEmbedder
from fixtures.skos import scheme
from lab.core.semantic.fabric import graph as G
from lab.core.semantic.fabric.catalog import MemoryCatalog
from lab.core.semantic.fabric.ontology import DocumentTypes
from lab.core.semantic.fabric.rungs import CANDIDATES_GRAPH, CONFIRMED, CONSTRUCTED, EXTRACTED, PROV_GRAPH, SUGGESTED, graph_iri
from lab.core.semantic.fabric.service import PERSISTED_GRAPHS, FabricService, term

LAB = {"source": "lab", "ref": "art://run1/minutes.md"}
DOC = {"source": "collab", "handle": "collab://site/drive/doc7", "version": "2"}


@pytest.fixture
def fab():
    ds = Dataset(default_union=True)
    sc = scheme()
    ds.graph(URIRef("urn:lab:semantic:vocab:syn-v1")).__iadd__(sc.graph())
    written: list[tuple[str, ...]] = []
    f = FabricService(ds, MemoryCatalog(), DocumentTypes(), schemes=lambda: {sc.name: sc},
                      embedder=HashEmbedder(dim=8), on_write=lambda touched: written.append(tuple(touched)))
    f.written = written        # type: ignore[attr-defined]
    return f


def test_term_reads_iris_literals_and_typed_values():
    assert isinstance(term("urn:x:1"), URIRef) and isinstance(term("https://a/b"), URIRef)
    assert term("a plain label") == Literal("a plain label")
    assert term(True) == Literal(True) and term(0.5) == Literal(0.5)
    assert term(Literal("x")) == Literal("x")
    # a colon does not make an IRI: a scheme does
    assert term("09:00") == Literal("09:00") and term("Confidential:Internal") == Literal("Confidential:Internal")


def test_a_label_on_an_artifact_with_no_owner_is_still_refused_outside_c(fab):
    """NFR-3 for the label alone: the shape used to target only owners, so an owner-less artifact was never a
    focus node and a guessed label at S slipped through."""
    a = fab.catalog_upsert(DOC)["iri"]
    with pytest.raises(ValueError, match="NFR-3"):
        fab.catalog_assert(a, "sensitivity_label", "Confidential", rung=SUGGESTED, method="guess", confidence=0.5)
    assert G.find(fab.ds, URIRef(a), G.FAB.sensitivityLabel) == [] and fab.catalog.get(a).sensitivity_label == ""


def test_facets_are_typed_not_guessed(fab):
    a = fab.catalog_upsert(DOC)["iri"]
    with pytest.raises(ValueError, match="owner must be an IRI"):
        fab.catalog_assert(a, "owner", "Maria Perez", rung=CONSTRUCTED, method="owner-map")
    with pytest.raises(ValueError, match="document_type must be an IRI"):
        fab.catalog_assert(a, "document_type", "minutes", rung=SUGGESTED, method="m", confidence=0.9)
    fab.catalog_assert(a, "sensitivity_label", "Confidential:Internal", rung=CONSTRUCTED, method="site-default")
    assert G.find(fab.ds, URIRef(a), G.FAB.sensitivityLabel)[0][1][2] == Literal("Confidential:Internal")


def test_retract_goes_through_the_guard_and_never_touches_the_rows_own_facts(fab):
    a = fab.catalog_upsert(DOC, title="Notes")["iri"]
    with pytest.raises(ValueError, match="catalog_state"):
        fab.graph_retract(a, "urn:fabric:ont#lifecycleState", "urn:fabric:ont#Pending", actor="x", reason="y")
    assert fab.validate().conforms
    fab.graph_assert(a, "urn:fabric:ont#references", "urn:fabric:artifact:other", rung=EXTRACTED, method="x")
    assert fab.graph_retract(a, "urn:fabric:ont#references", "urn:fabric:artifact:other", actor="rule", reason="r")
    assert fab.validate().conforms and set(fab.written[-1]) >= {"X", "prov"}


def test_a_bare_item_id_gets_a_custody_iri_not_a_relative_one(fab):
    row = fab.catalog_upsert({"source": "work", "workItem": "12345"}, title="Work item")
    url = next(fab.ds.graph(graph_iri(CONSTRUCTED)).objects(URIRef(row["iri"]), URIRef("http://www.w3.org/ns/dcat#accessURL")))
    assert str(url) == "urn:fabric:custody:work%3A12345"
    text = fab.snapshot("C")
    other = FabricService(Dataset(default_union=True), MemoryCatalog(), DocumentTypes(), schemes=dict)
    other.restore([text])
    assert (URIRef(row["iri"]), URIRef("http://www.w3.org/ns/dcat#accessURL"), url) in other.ds.graph(graph_iri(CONSTRUCTED))


def test_validation_is_focused_on_the_subject_that_changed(fab):
    """The guard's work is proportional to the change, not the corpus: another artifact's triples are not in
    the view a write is checked against."""
    a = fab.catalog_upsert(DOC, title="A")["iri"]; b = fab.catalog_upsert(LAB, title="B")["iri"]
    view = fab._view([URIRef(a)])
    assert (URIRef(a), G.DCT.title, Literal("A")) in view.graph(graph_iri(CONSTRUCTED))
    assert (URIRef(b), G.DCT.title, Literal("B")) not in view.graph(graph_iri(CONSTRUCTED))
    assert len(fab._view().graph(graph_iri(CONSTRUCTED))) > len(view.graph(graph_iri(CONSTRUCTED)))


def test_similarity_stays_within_one_embedding_space(fab):
    a = fab.catalog_upsert(LAB, title="A")["iri"]; b = fab.catalog_upsert(DOC, title="B")["iri"]
    fab.embed(a, "A")
    fab.catalog.put_embedding(b, fab.catalog.embedding(a)[0], "another-model")     # same vector, other space
    assert [n["iri"] for n in fab.similar(iri=a)] == []


def test_upsert_mints_an_iri_mirrors_the_row_into_graph_c_and_reports_the_write(fab):
    row = fab.catalog_upsert(LAB, title="Minutes 2026-09-01", produced_by="transcript_to_minutes",
                             context="meeting:AAMk1", source_kind="lab")
    a = URIRef(row["iri"])
    assert row["iri"].startswith("urn:fabric:artifact:") and row["state"] == "pending"
    c = fab.ds.graph(graph_iri(CONSTRUCTED))
    assert (a, RDF.type, G.FAB.Artifact) in c and (a, G.FAB.lifecycleState, G.FAB.Pending) in c
    assert (a, URIRef("http://www.w3.org/ns/dcat#accessURL"), URIRef("art://run1/minutes.md")) in c
    # produced by a lab process -> its type is a FACT (rung C, method produced-by), delivered under the run's context
    assert row["document_type"] == "urn:fabric:scheme:doc-types#minutes"
    assert G.find(fab.ds, a, G.FAB.documentType)[0][0] == CONSTRUCTED
    assert G.find(fab.ds, a, G.FAB.deliveredUnder, URIRef("urn:fabric:context:meeting:AAMk1"))[0][0] == CONSTRUCTED
    assert fab.written and set(fab.written[-1]) >= {"C", "prov"}
    assert fab.validate().conforms


def test_upsert_is_idempotent_on_the_pointer_and_keeps_the_iri(fab):
    first = fab.catalog_upsert(DOC, title="Notes")
    again = fab.catalog_upsert(DOC, title="Notes v2")
    assert again["iri"] == first["iri"] and again["title"] == "Notes v2"
    assert len(fab.catalog) == 1
    assert len(list(fab.ds.graph(graph_iri(CONSTRUCTED)).triples((URIRef(first["iri"]), G.DCT.title, None)))) == 1


def test_upsert_refuses_a_body_sized_title_and_a_bad_pointer(fab):
    with pytest.raises(ValueError):
        fab.catalog_upsert(DOC, title="x" * 301)
    with pytest.raises(ValueError):
        fab.catalog_upsert({"source": "collab"}, title="no id")
    assert len(fab.catalog) == 0


def test_get_labels_a_subject_link_so_a_person_and_the_index_read_the_concept(fab):
    d = fab.catalog_upsert(DOC, title="ADR")["iri"]
    fab.vocab_link(d, terms=["Care Delivery"])
    subj = [l for l in fab.catalog_get(d)["links"] if l["predicate"] == "subject"]
    assert subj and subj[0]["label"] == "Care Delivery"
    assert all("label" not in l for l in fab.catalog_get(d)["links"] if l["predicate"] != "subject")


def test_get_joins_the_row_with_its_links_by_rung(fab):
    row = fab.catalog_upsert(LAB, produced_by="transcript_to_minutes", context="meeting:AAMk1")
    got = fab.catalog_get(row["iri"])
    kinds = {(l["predicate"], l["rung"]) for l in got["links"]}
    assert ("deliveredUnder", "C") in kinds and ("documentType", "C") in kinds
    assert fab.catalog_get("urn:fabric:artifact:nope") is None


def test_state_moves_the_lifecycle_in_row_and_graph(fab):
    a = fab.catalog_upsert(DOC)["iri"]
    row = fab.catalog_state(a, "published", baseline_version="4.0")
    assert (row["state"], row["baseline_version"]) == ("published", "4.0")
    c = fab.ds.graph(graph_iri(CONSTRUCTED))
    states = list(c.objects(URIRef(a), G.FAB.lifecycleState))
    assert states == [G.FAB.Published] and (URIRef(a), G.FAB.baselineVersion, Literal("4.0")) in c
    with pytest.raises(ValueError):
        fab.catalog_state(a, "draft")
    with pytest.raises(LookupError):
        fab.catalog_state("urn:fabric:artifact:nope", "published")
    assert fab.validate().conforms


def test_assert_a_facet_writes_row_and_rung_and_replaces_the_previous_value(fab):
    a = fab.catalog_upsert(DOC)["iri"]
    fab.catalog_assert(a, "document_type", "urn:fabric:scheme:doc-types#decision-record", rung=SUGGESTED,
                       method="classifier", confidence=0.8)
    assert fab.catalog.get(a).document_type.endswith("decision-record")
    assert G.find(fab.ds, URIRef(a), G.FAB.documentType)[0][0] == SUGGESTED
    fab.catalog_assert(a, "document_type", "urn:fabric:scheme:doc-types#minutes", rung=CONFIRMED,
                       method="approval", actor="reviewer@x")
    hits = G.find(fab.ds, URIRef(a), G.FAB.documentType)
    assert [(r, str(o)) for r, (_, _, o) in hits] == [("H", "urn:fabric:scheme:doc-types#minutes")]
    assert fab.catalog.get(a).document_type.endswith("minutes")
    with pytest.raises(ValueError):
        fab.catalog_assert(a, "colour", "red", rung=CONSTRUCTED, method="x")


def test_owner_and_label_may_only_be_constructed_and_a_violation_is_undone(fab):
    a = fab.catalog_upsert(DOC)["iri"]
    fab.catalog_assert(a, "owner", "urn:fabric:person:oid-1", rung=CONSTRUCTED, method="owner-map")
    fab.catalog_assert(a, "sensitivity_label", "Confidential", rung=CONSTRUCTED, method="inherited-label")
    assert fab.catalog.get(a).owner == "urn:fabric:person:oid-1"
    with pytest.raises(ValueError, match="NFR-3"):
        fab.catalog_assert(a, "owner", "urn:fabric:person:oid-2", rung=SUGGESTED, method="guess", confidence=0.5)
    # the failed write left nothing behind: the C owner stands, no S triple, no dangling prov record
    assert [(r, str(o)) for r, (_, _, o) in G.find(fab.ds, URIRef(a), G.FAB.ownedBy)] == [("C", "urn:fabric:person:oid-1")]
    assert fab.catalog.get(a).owner == "urn:fabric:person:oid-1"
    live = [s for s in fab.ds.graph(PROV_GRAPH).subjects(G.FAB.rung, Literal("S"))]
    assert live == []
    assert fab.validate().conforms


def test_graph_assert_and_retract_are_the_raw_edges_with_provenance(fab):
    a = fab.catalog_upsert(DOC)["iri"]; b = fab.catalog_upsert(LAB)["iri"]
    r = fab.graph_assert(a, "urn:fabric:ont#references", b, rung=EXTRACTED, method="link-extraction")
    assert r["rung"] == "X" and r["assertion"].startswith("urn:fabric:assertion:")
    assert G.find(fab.ds, URIRef(a), G.FAB.references, URIRef(b))[0][0] == "X"
    with pytest.raises(ValueError):
        fab.graph_assert(a, "urn:fabric:ont#references", b, rung="D", method="x")
    assert fab.graph_retract(a, "urn:fabric:ont#references", b, actor="rule:stale", reason="superseded") is True
    assert G.find(fab.ds, URIRef(a), G.FAB.references, URIRef(b)) == []
    assert fab.graph_retract(a, "urn:fabric:ont#references", b, actor="rule:stale", reason="again") is False


def test_a_content_property_never_enters_the_graph(fab):
    a = fab.catalog_upsert(DOC)["iri"]
    with pytest.raises(ValueError):
        fab.graph_assert(a, "urn:fabric:ont#body", "the whole document text", rung=CONSTRUCTED, method="x")
    assert G.find(fab.ds, URIRef(a), URIRef("urn:fabric:ont#body")) == []
    assert fab.validate().conforms


def test_impact_reads_trusted_rungs_only_and_joins_the_catalog(fab):
    m = fab.catalog_upsert(LAB, title="Minutes", produced_by="transcript_to_minutes", context="meeting:AAMk1")["iri"]
    d = fab.catalog_upsert(DOC, title="ADR-14")["iri"]
    s = fab.catalog_upsert({"source": "collab", "handle": "collab://x/y/z"}, title="Suggested only")["iri"]
    fab.graph_assert(d, "urn:fabric:ont#references", m, rung=EXTRACTED, method="link-extraction")
    fab.graph_assert(s, "urn:fabric:ont#references", m, rung=SUGGESTED, method="nn", confidence=0.6)
    hit = fab.graph_impact(m)
    assert [(h["iri"], h["distance"], h["rung"], h["title"]) for h in hit] == [(d, 1, "X", "ADR-14")]
    ctx = fab.graph_traverse("urn:fabric:context:meeting:AAMk1", ["urn:fabric:ont#deliveredUnder"], rungs=["C"])
    assert [h["iri"] for h in ctx] == [m]


def test_vocab_link_matches_labels_at_x_and_reports_misses(fab):
    a = fab.catalog_upsert(DOC)["iri"]
    out = fab.vocab_link(a, ["Triage", "Care Delivery", "Nothing Like This"])
    assert [l["term"] for l in out["linked"]] == ["Triage", "Care Delivery"] and out["missed"] == ["Nothing Like This"]
    subj = G.find(fab.ds, URIRef(a), G.DCT.subject)
    assert {r for r, _ in subj} == {"X"} and len(subj) == 2
    assert fab.validate().conforms


def test_vocab_propose_parks_a_candidate_and_promote_accepts_it(fab):
    cand = fab.vocab_propose("Discharge Summary", definition="The letter sent at discharge", actor="classifier-agent")
    g = fab.ds.graph(CANDIDATES_GRAPH)
    c = URIRef(cand["iri"])
    assert (c, RDF.type, G.SKOS.Concept) in g and (c, G.SKOS.prefLabel, Literal("Discharge Summary")) in g
    assert cand["iri"].startswith("urn:fabric:candidate:")
    assert "candidates" in fab.written[-1]
    acc = fab.promote(cand["iri"], actor="steward@x", method="steward-review")
    assert acc["rung"] == "H" and G.find(fab.ds, c, G.FAB.lifecycleState, G.FAB.Published)[0][0] == "H"
    with pytest.raises(ValueError):
        fab.vocab_propose("", actor="x")
    with pytest.raises(ValueError):
        fab.vocab_propose("Label", actor="")


def test_promote_moves_an_edge_up_the_ladder_and_needs_an_actor(fab):
    a = fab.catalog_upsert(DOC)["iri"]
    fab.graph_assert(a, "urn:fabric:ont#deliveredUnder", "urn:fabric:context:usecase:UC-1", rung=SUGGESTED,
                     method="author+time", confidence=0.6)
    with pytest.raises(ValueError):
        fab.promote(a, "urn:fabric:ont#deliveredUnder", "urn:fabric:context:usecase:UC-1", actor="", method="card")
    r = fab.promote(a, "urn:fabric:ont#deliveredUnder", "urn:fabric:context:usecase:UC-1", actor="person@x", method="card")
    assert r["rung"] == "H" and r["from"] == "S"
    assert [x for x, _ in G.find(fab.ds, URIRef(a), G.FAB.deliveredUnder)] == ["H"]
    assert set(fab.written[-1]) >= {"S", "H", "prov"}


def test_embed_similar_and_search_join_the_catalog(fab):
    a = fab.catalog_upsert(LAB, title="Minutes of the bus meeting", produced_by="transcript_to_minutes")["iri"]
    b = fab.catalog_upsert(DOC, title="ADR on the event bus")["iri"]
    e = fab.embed(a, "Minutes of the bus meeting · minutes")
    assert e == {"iri": a, "model": "test-embed", "dim": 8}
    # the two sides of an asymmetric embedder, spelled as `lab.platform.embed.PURPOSES` knows them (live, 11 Sep:
    # a purpose of its own was refused by the gateway embedder and the index stayed empty)
    from lab.platform.embed import PURPOSES
    assert fab.embedder.calls[-1][1] == "document" and "document" in PURPOSES and "query" in PURPOSES
    fab.embed(b, "ADR on the event bus · decision record")
    near = fab.similar(iri=a)
    assert [n["iri"] for n in near] == [b] and "score" in near[0] and near[0]["title"] == "ADR on the event bus"
    hits = fab.search("ADR on the event bus · decision record")
    assert hits[0]["iri"] == b and hits[0]["score"] == pytest.approx(1.0)
    assert fab.embedder.calls[-1][1] == "query"
    typed = fab.search("anything", document_type="urn:fabric:scheme:doc-types#minutes")
    assert [t["iri"] for t in typed] == [a]
    with pytest.raises(ValueError):
        fab.similar()
    with pytest.raises(LookupError):
        fab.similar(iri="urn:fabric:artifact:nope")


def test_without_an_embedder_the_index_refuses_plainly(fab):
    fab.embedder = None
    a = fab.catalog_upsert(DOC)["iri"]
    with pytest.raises(RuntimeError, match="embedder"):
        fab.embed(a, "x")
    with pytest.raises(RuntimeError, match="embedder"):
        fab.search("x")


def test_snapshot_and_restore_round_trip_every_persisted_graph(fab):
    a = fab.catalog_upsert(DOC, title="Notes")["iri"]
    fab.graph_assert(a, "urn:fabric:ont#references", "urn:fabric:artifact:other", rung=EXTRACTED, method="x")
    fab.vocab_propose("Candidate", actor="c")
    snaps = {name: fab.snapshot(name) for name in fab.PERSISTED}
    assert set(snaps) == {"S", "X", "C", "H", "D", "prov", "candidates"} == set(PERSISTED_GRAPHS)
    ds2 = Dataset(default_union=True)
    other = FabricService(ds2, MemoryCatalog(), DocumentTypes(), schemes=dict)
    loaded = other.restore(snaps.values())
    assert loaded > 0
    assert G.find(ds2, URIRef(a), G.FAB.references)[0][0] == "X"
    assert (URIRef(a), G.DCT.title, Literal("Notes")) in ds2.graph(graph_iri(CONSTRUCTED))
    assert len(ds2.graph(CANDIDATES_GRAPH)) > 0


def test_get_by_pointer_answers_a_sweeps_question(fab):
    row = fab.catalog_upsert(DOC, title="Notes")
    assert fab.catalog_get(pointer=DOC)["iri"] == row["iri"]
    assert fab.catalog_get(pointer={"source": "collab", "handle": "collab://item/x/y"}) is None
    assert fab.catalog_get() is None



def test_retracting_a_facet_edge_clears_the_rows_column(fab):
    """The row mirrors the facet; a retraction that left `minutes` on the row while the graph had no type
    was measured live. Cleared even when the triple is already gone, so the two can be brought back in step."""
    a = fab.catalog_upsert(DOC)["iri"]
    fab.catalog_assert(a, "document_type", "urn:fabric:scheme:doc-types#minutes", rung=SUGGESTED, method="m", confidence=0.7)
    assert fab.graph_retract(a, "urn:fabric:ont#documentType", "urn:fabric:scheme:doc-types#minutes", actor="p", reason="wrong")
    assert fab.catalog.get(a).document_type == "" and G.find(fab.ds, URIRef(a), G.FAB.documentType) == []
    fab.catalog.put(fab.catalog.get(a).with_(document_type="urn:fabric:scheme:doc-types#minutes"))   # drifted row, no triple
    assert fab.graph_retract(a, "urn:fabric:ont#documentType", "urn:fabric:scheme:doc-types#minutes", actor="p", reason="drift") is False
    assert fab.catalog.get(a).document_type == ""


def test_reindex_embeds_every_row_the_current_space_lacks_from_its_facets(fab):
    a = fab.catalog_upsert(LAB, title="Minutes of the bus meeting", produced_by="transcript_to_minutes")["iri"]
    b = fab.catalog_upsert(DOC, title="ADR on the event bus")["iri"]
    fab.vocab_link(b, terms=["Care Delivery"])
    fab.embed(a, "stale")
    fab.catalog.put_embedding(a, fab.catalog.embedding(a)[0], "retired-model")      # the embedder was switched
    w = fab.catalog_upsert({"source": "lab", "ref": "art://1/w"}, title="gone")["iri"]
    fab.catalog_state(w, "withdrawn")
    report = fab.reindex()
    assert report == {"model": "test-embed", "indexed": 2, "skipped": 0}
    assert fab.catalog.embedding(a)[1] == "test-embed" and fab.catalog.embedding(w) is None
    texts = [t for (ts, purpose) in fab.embedder.calls for t in ts if purpose == "document"]
    assert "ADR on the event bus · Care Delivery" in texts and "Minutes of the bus meeting · minutes" in texts
    assert fab.reindex()["indexed"] == 0                                             # idempotent


def test_reindex_counts_a_row_the_embedder_refuses_instead_of_stopping(fab):
    a = fab.catalog_upsert(LAB, title="A")["iri"]; fab.catalog_upsert(DOC, title="B")
    calls = fab.embedder.embed

    def flaky(texts, *, purpose):
        if texts[0].startswith("A"):
            raise RuntimeError("upstream 500")
        return calls(texts, purpose=purpose)
    fab.embedder.embed = flaky
    report = fab.reindex()
    assert (report["indexed"], report["skipped"]) == (1, 1) and "upstream 500" in report["reason"]
    assert fab.catalog.embedding(a) is None
    fab.embedder.embed = calls
    assert "reason" not in fab.reindex()                                            # a clean sweep carries none


def test_search_says_the_index_is_empty_rather_than_answering_nothing(fab):
    """The person asking is not the one reading semantic-mcp's log: after an embedder switch the index is
    empty, and that must not read as 'your query matched nothing'."""
    assert fab.search("anything") == []                                             # nothing catalogued: honestly empty
    a = fab.catalog_upsert(LAB, title="A")["iri"]
    with pytest.raises(RuntimeError, match="semantic_reindex"):
        fab.search("anything")
    fab.embed(a, "A")
    assert [h["iri"] for h in fab.search("zzz")] == [a]                             # indexed: ranked, never refused


def test_search_hides_withdrawn_records_unless_that_state_is_asked_for(fab):
    a = fab.catalog_upsert(LAB, title="kept")["iri"]; w = fab.catalog_upsert(DOC, title="gone")["iri"]
    fab.embed(a, "kept"); fab.embed(w, "gone"); fab.catalog_state(w, "withdrawn")
    assert [h["iri"] for h in fab.search("gone")] == [a]
    assert [h["iri"] for h in fab.search("gone", state="withdrawn")] == [w]
    assert [h["iri"] for h in fab.similar(text="gone")][0] == w           # similar is the raw index, unfiltered


def test_a_pointer_with_spaces_is_catalogued_and_every_graph_still_serialises(fab):
    ref = "art://89df6f4cd2a6/meeting-2 test-20260912_180136-Meeting Recording.mp4.minutes.json"
    row = fab.catalog_upsert({"source": "lab", "ref": ref}, title="minutes", produced_by="transcript_to_minutes")
    assert fab.catalog_get(row["iri"])["pointer"]["ref"] == ref                    # the row keeps the real ref
    for name in PERSISTED_GRAPHS:
        fab.snapshot(name)                                                        # nothing refuses to serialise
    from lab.core.semantic.fabric.service import DCAT
    assert "%20" in str(fab.ds.value(URIRef(row["iri"]), DCAT.accessURL))


def test_a_write_the_store_cannot_persist_is_undone_not_kept_in_memory(fab):
    """A conforming write that fails to persist would survive in memory and vanish on restart — the person's
    decision recorded nowhere durable. It is undone and the failure raised instead."""
    d = fab.catalog_upsert(DOC, title="ADR")["iri"]
    fab.catalog_assert(d, "document_type", "urn:fabric:scheme:doc-types#decision-record", rung="S", method="m", confidence=0.7)
    fab._on_write = lambda touched: (_ for _ in ()).throw(RuntimeError("artifact store down"))
    with pytest.raises(RuntimeError, match="artifact store down"):
        fab.promote(d, "urn:fabric:ont#documentType", "urn:fabric:scheme:doc-types#decision-record",
                    actor="maria@x", method="review")
    links = {(l["predicate"], l["rung"]) for l in fab.catalog_get(d)["links"]}
    assert ("documentType", "S") in links and ("documentType", "H") not in links
