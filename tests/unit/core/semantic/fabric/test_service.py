"""FabricService — the four products over one Dataset and one Catalog, offline. Every write lands in a rung
graph WITH provenance, is SHACL-checked, and is reported to the persistence hook; a violation is undone."""
import pytest
from rdflib import RDF, Dataset, Literal, URIRef

from fixtures.embed import HashEmbedder
from fixtures.skos import scheme
from lab.core.semantic.fabric import graph as G
from lab.core.semantic.fabric import renderings
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
    # A candidate with no home cannot be ADMITTED — accepting it would write a lifecycle triple on a concept
    # no lookup can reach, which is how the same term came back the next time a document used it.
    with pytest.raises(ValueError, match="names no scheme"):
        fab.promote(cand["iri"], actor="steward@x", method="steward-review")
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
    assert set(snaps) == set(PERSISTED_GRAPHS) >= {"S", "X", "C", "H", "D", "prov", "candidates", "curated"}
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


def _store_down(fab):
    def fail(touched):
        raise RuntimeError("artifact store down")
    fab._on_write = fail


def test_every_write_path_undoes_what_the_store_did_not_take(fab):
    d = fab.catalog_upsert(DOC, title="ADR")["iri"]
    m = fab.catalog_upsert(LAB, title="Minutes")["iri"]
    fab.catalog_assert(d, "document_type", "urn:fabric:scheme:doc-types#decision-record", rung="S", method="m", confidence=0.7)
    fab.graph_assert(d, "urn:fabric:ont#references", m, rung="X", method="link")
    _store_down(fab)
    # upsert: no row, no mirror
    with pytest.raises(RuntimeError):
        fab.catalog_upsert({"source": "lab", "ref": "art://1/new"}, title="new")
    assert fab.catalog_get(pointer={"source": "lab", "ref": "art://1/new"}) is None
    # retract: the triple is back AND the row's column is not cleared
    with pytest.raises(RuntimeError):
        fab.graph_retract(d, "urn:fabric:ont#documentType", "urn:fabric:scheme:doc-types#decision-record", actor="x", reason="r")
    assert fab.catalog_get(d)["document_type"].endswith("#decision-record")
    assert ("documentType", "S") in {(l["predicate"], l["rung"]) for l in fab.catalog_get(d)["links"]}
    # supersede: the old triple is back with NO dangling invalidation on its assertion record
    with pytest.raises(RuntimeError):
        fab.graph_assert(d, "urn:fabric:ont#references", "urn:fabric:artifact:other", rung="X", method="link", supersede=True)
    prov = fab.ds.graph(PROV_GRAPH)
    assert not list(prov.triples((None, G.PROV.wasInvalidatedBy, None)))
    assert ("references", "X") in {(l["predicate"], l["rung"]) for l in fab.catalog_get(d)["links"]}
    # propose: no candidate survives in memory
    with pytest.raises(RuntimeError):
        fab.vocab_propose(label="Ghost", actor="steward@x")
    assert not list(fab.ds.graph(CANDIDATES_GRAPH).triples((None, None, Literal("Ghost"))))


def test_an_unserialisable_subject_is_refused_legibly_before_it_reaches_the_graph(fab):
    d = fab.catalog_upsert(DOC, title="ADR")["iri"]
    with pytest.raises(ValueError, match="serialisable IRI"):
        fab.graph_assert("art://x/a b", "urn:fabric:ont#references", d, rung="X", method="link")


def test_a_new_version_of_a_known_product_reopens_the_record_and_keeps_its_baseline(fab):
    p1 = {"source": "lab", "product": "use_case_screening/art://s/sub.json/screening_ref", "ref": "art://r1/s.json", "version": "wfr-1"}
    first = fab.catalog_upsert(p1, title="screening.json", produced_by="use_case_screening", context="usecase:u1")
    assert "revised" not in first
    fab.catalog_state(first["iri"], "published", baseline_version="wfr-1")
    p2 = {**p1, "ref": "art://r2/s.json", "version": "wfr-2"}
    second = fab.catalog_upsert(p2, title="screening.json", produced_by="use_case_screening", context="usecase:u1")
    assert second["iri"] == first["iri"] and second["revised"] is True and second["previous_version"] == "wfr-1"
    row = fab.catalog_get(first["iri"])
    assert row["state"] == "pending" and row["baseline_version"] == "wfr-1" and row["pointer"]["ref"] == "art://r2/s.json"
    assert "revised" not in fab.catalog_upsert(p2, title="screening.json", produced_by="use_case_screening", context="usecase:u1")


def test_a_duplicate_adjudication_is_an_edge_the_shapes_allow_and_the_record_shows(fab):
    from lab.core.semantic.fabric.ontology import DUPLICATE_OF
    a = fab.catalog_upsert(LAB, title="A")["iri"]; b = fab.catalog_upsert(DOC, title="B")["iri"]
    r = fab.graph_assert(a, DUPLICATE_OF, b, rung="H", method="draft-review", actor="steward@x")
    assert r["rung"] == "H" and ("duplicateOf", "H") in {(l["predicate"], l["rung"]) for l in fab.catalog_get(a)["links"]}


def test_recommend_answers_only_with_published_records(fab):
    a = fab.catalog_upsert(LAB, title="published one")["iri"]; b = fab.catalog_upsert(DOC, title="pending one")["iri"]
    fab.embed(a, "claims intake"); fab.embed(b, "claims intake"); fab.catalog_state(a, "published", baseline_version="1")
    assert [h["iri"] for h in fab.recommend("claims intake")] == [a]


def test_derive_persists_d_and_a_store_failure_leaves_d_empty_and_raises(fab):
    from lab.core.semantic.fabric.ontology import SYNTHESISED_FROM
    m = fab.catalog_upsert(LAB, title="Minutes", produced_by="transcript_to_minutes", context="meeting:AAMk1")["iri"]
    d = fab.catalog_upsert(DOC, title="ADR")["iri"]
    fab.graph_assert(d, SYNTHESISED_FROM, m, rung="C", method="drafted-from")
    out = fab.derive()
    assert out["derived"] == 1 and ("D", "prov") in fab.written[-1:] or ("D", "prov") == fab.written[-1]
    assert ("deliveredUnder", "D") in {(l["predicate"], l["rung"]) for l in fab.catalog_get(d)["links"]}
    _store_down(fab)
    with pytest.raises(RuntimeError):
        fab.derive()
    assert ("deliveredUnder", "D") not in {(l["predicate"], l["rung"]) for l in fab.catalog_get(d)["links"]}


def test_relinking_REPLACES_the_extracted_subjects_instead_of_accumulating(fab):
    """Re-classification must be able to take a wrong subject BACK.

    `vocab_link` only ever added, so a record classified from its file name kept those links for ever: the
    catalogue measured 7 Oct 2026 carried `Clinical document` on 39 of 93 records, and a re-run with better
    evidence would have produced a UNION of the old guesses and the new reading — strictly worse than before,
    because a reader cannot tell which pass produced which link.

    Superseding per assertion is not the answer either: `vocab_link` asserts once per concept, so each call
    would retract the one before it and a document would end with its last subject only. The unit being
    replaced is the SET, so the extracted subjects this run did not produce are retracted once, at the end.
    """
    a = fab.catalog_upsert(DOC)["iri"]
    first = fab.vocab_link(a, ["Triage", "Care Delivery"])
    assert len(G.find(fab.ds, URIRef(a), G.DCT.subject)) == 2
    # Triage's concept IRI as the FIRST pass resolved it — the independent yardstick for which subject
    # survived. A concept id here is a hash of its label path, so the IRI does not spell the label and
    # the survivor cannot be identified by reading it.
    triage = next(r["concept"] for r in first["linked"] if r["label"] == "Triage")
    dropped = next(r["concept"] for r in first["linked"] if r["label"] == "Care Delivery")

    kept = fab.vocab_link(a, ["Triage"])               # a narrower, better-evidenced reading
    live = G.find(fab.ds, URIRef(a), G.DCT.subject)
    assert len(live) == 1, "the dropped subject must not survive a re-link"
    # WHICH subject survived, not merely how many. The count alone passes just as happily when the
    # retraction takes the wrong one, and "it kept exactly one link" is the symptom either way.
    survivor = str(live[0][1][2])
    assert survivor == kept["linked"][0]["concept"], "the surviving link must be the one this run asserted"
    assert survivor == triage, "and it is Triage, judged against the first pass rather than this call's answer"
    # The DROPPED one is NAMED in `retracted`, which nothing asserted. Saying "Care Delivery is not in
    # linked" would have re-asserted the input instead: only ["Triage"] was passed, so it could not be
    # there however the retraction behaved. A re-classification whose removals are invisible is
    # indistinguishable from one that did nothing, so the report of them is part of the contract.
    assert kept["retracted"] == [dropped], kept["retracted"]
    assert fab.validate().conforms


def test_relinking_leaves_a_HUMAN_confirmed_subject_alone(fab):
    """A person's judgement outranks a re-run. Promotion to H is the only way a link becomes a fact, so a
    classifier that silently retracted one would undo the single act the ladder exists to record."""
    a = fab.catalog_upsert(DOC)["iri"]
    fab.vocab_link(a, ["Triage", "Care Delivery"])
    confirmed = [t for _, t in G.find(fab.ds, URIRef(a), G.DCT.subject)][0]
    fab.graph_assert(a, str(G.DCT.subject), confirmed[2], rung="H", method="steward-review", actor="p@x")

    fab.vocab_link(a, ["Nothing Like This"])           # a re-run that matches nothing at all
    rungs = {r for r, _ in G.find(fab.ds, URIRef(a), G.DCT.subject)}
    assert "H" in rungs, "a confirmed subject survives a re-classification that no longer proposes it"


def test_a_relink_that_changes_nothing_retracts_nothing(fab):
    """Idempotence matters because the re-classification driver will run over the whole catalogue: a pass that
    retracted and re-asserted every unchanged link would fill the provenance graph with invalidations that
    record no decision."""
    a = fab.catalog_upsert(DOC)["iri"]
    fab.vocab_link(a, ["Triage", "Care Delivery"])
    before = fab.catalog_get(a)["links"]
    fab.vocab_link(a, ["Triage", "Care Delivery"])
    assert fab.catalog_get(a)["links"] == before


def test_corpus_view_walks_the_whole_catalogue_in_process(fab):
    """The walk a CALLER must not do. Resolving the corpus over the gateway costs a round trip per record
    and trips the key's own rate limit at about sixty (measured 10 Oct 2026, twice). Doing it here is one
    tool call, and the paging is the same keyset the bulk tools use, so a catalogue that grows under a
    long walk neither skips nor repeats."""
    for n in range(5):
        iri = fab.catalog_upsert(pointer={"source": "collab", "handle": f"collab://d/i{n}"},
                                 title=f"doc{n}.md")["iri"]
        fab.catalog_state(iri, "published")
        if n < 3:                                        # two records are about nothing at all
            fab.vocab_link(iri, ["Care Delivery"])

    view = fab.corpus_view(as_of="2026-10-10")
    drawn = {n.label for n in view.nodes if n.kind == "artifact"}
    assert drawn == {"doc0.md", "doc1.md", "doc2.md"}    # the two about nothing are counted, not drawn
    assert "2 records with no subject" in view.subtitle and view.as_of == "2026-10-10"
    assert view.focus == "" and view.facet_values("state") == ("published",)
    assert all(n.facet("source") == "collab" for n in view.nodes if n.kind == "artifact")


def test_corpus_view_narrows_by_state_and_caps_what_it_reads(fab):
    for n in range(4):
        iri = fab.catalog_upsert(pointer={"source": "lab", "ref": f"art://r/{n}"}, title=f"r{n}.json")["iri"]
        fab.catalog_state(iri, "published" if n % 2 else "pending")
        fab.vocab_link(iri, ["Care Delivery"])
    assert len([n for n in fab.corpus_view(state="published").nodes if n.kind == "artifact"]) == 2
    assert len([n for n in fab.corpus_view(limit=1).nodes if n.kind == "artifact"]) == 1
    with pytest.raises(ValueError):
        fab.corpus_view(state="not-a-state")             # a typo must not read as "nothing matched"


def test_the_projection_pages_url_is_the_records_landing_page_and_rides_the_row(fab):
    """`dcat:landingPage` is exactly "a web page to navigate to in order to gain access to the resource", so
    the projection page is one. It is a LITERAL: the page is addressed by the URL a person opens, which carries
    its own tenant and is not a thing the graph names. Reported beside the row, because a caller asking
    `catalog_get` for a record is the caller that wants to hand somebody the page."""
    from lab.core.semantic.fabric.service import DCAT
    a = fab.catalog_upsert(DOC, title="Notes")["iri"]
    fab.catalog_assert(a, "projection_url", "https://wiki/x.md", rung=CONSTRUCTED, method="fabric-projector")
    assert fab.catalog.get(a).projection_url == "https://wiki/x.md"
    assert [(r, o) for r, (_, _, o) in G.find(fab.ds, URIRef(a), DCAT.landingPage)] == [
        (CONSTRUCTED, Literal("https://wiki/x.md"))]
    row = fab.catalog_get(a)
    assert row["projection_url"] == "https://wiki/x.md"
    assert {"predicate": "landingPage", "object": "https://wiki/x.md", "rung": CONSTRUCTED} in row["links"]
    # the page is rewritten on every publish, and a new location supersedes the old one rather than joining it
    fab.catalog_assert(a, "projection_url", "https://wiki/moved.md", rung=CONSTRUCTED, method="fabric-projector")
    assert [str(o) for _, (_, _, o) in G.find(fab.ds, URIRef(a), DCAT.landingPage)] == ["https://wiki/moved.md"]
    assert fab.validate().conforms


# ------------------------------------------------------- the semantic tier of the inverted classifier
def test_indexing_concepts_embeds_the_DEFINITION_and_only_what_is_missing():
    """A term is matched against what a concept MEANS, not what it is called — that is the whole reason
    the semantic tier exists, since the extractor's words almost never equal a label (measured 17 Oct:
    0 of 30 terms matched a label on real prose).

    Only the missing ones are embedded, because this runs lazily on a match and must not re-embed a
    whole vocabulary to answer one term."""
    ds = Dataset(default_union=True)
    sc = scheme()
    f = FabricService(ds, MemoryCatalog(), DocumentTypes(), schemes=lambda: {sc.name: sc},
                      embedder=HashEmbedder(dim=8))
    first = f.index_concepts(sc.name)
    assert first["indexed"] > 0 and first["model"] == "test-embed"
    sent = f.embedder.calls[-1][0]
    assert any(c["definition"] in " ".join(sent) for c in sc.concepts.values() if c.get("definition"))
    assert f.embedder.calls[-1][1] == "document", "a definition is the passage, never the probe"

    before = len(f.embedder.calls)
    again = f.index_concepts(sc.name)
    assert again["indexed"] == 0 and len(f.embedder.calls) == before, "nothing missing, nothing embedded"


def test_a_term_is_embedded_as_a_QUERY_against_definitions_indexed_as_DOCUMENTS():
    """The asymmetric sides of the embedder, the way `lab.platform.embed.PURPOSES` spells them: the term
    is the probe and the definition is the passage. Getting this backwards is silent — both are vectors
    of the same width and the scores merely get worse."""
    ds = Dataset(default_union=True)
    sc = scheme()
    f = FabricService(ds, MemoryCatalog(), DocumentTypes(), schemes=lambda: {sc.name: sc},
                      embedder=HashEmbedder(dim=8))
    f.concept_match("some term", scheme=sc.name)
    assert f.embedder.calls[-1][1] == "query"


def test_a_narrow_margin_matches_NOTHING_so_the_term_becomes_a_candidate():
    """The finding the whole tier rests on: 'proposed decision status' ranked top against *Prior
    authorisation* with a margin of 0.0016 — unrelated concepts the embedding could not tell apart,
    which an absolute threshold would have written to the graph as a fact at rung X."""
    ds = Dataset(default_union=True)
    sc = scheme()
    f = FabricService(ds, MemoryCatalog(), DocumentTypes(), schemes=lambda: {sc.name: sc},
                      embedder=HashEmbedder(dim=8))
    out = f.concept_match("anything at all", scheme=sc.name, floor=0.0, margin=0.99)
    assert out["concept"] == "" and out["term"] == "anything at all"


def test_without_an_embedder_the_semantic_tier_says_so_and_does_not_pretend():
    """An unavailable embedder means tier 2 is unavailable and the term becomes a candidate — the
    degradation pattern used everywhere else here. It must never look like 'the vocabulary has no such
    concept', which is a different and much more interesting claim."""
    ds = Dataset(default_union=True)
    sc = scheme()
    f = FabricService(ds, MemoryCatalog(), DocumentTypes(), schemes=lambda: {sc.name: sc}, embedder=None)
    out = f.concept_match("anything", scheme=sc.name)
    assert out["concept"] == "" and out["unavailable"] is True


def _about(fab, ref, concepts, *, state=""):
    iri = fab.catalog_upsert({"source": "lab", "ref": ref})["iri"]
    for c in concepts:
        fab.graph_assert(iri, str(G.DCT.subject), c, rung="X", method="label-match")
    if state:
        fab.catalog_state(iri, state)
    return iri


def test_RELATED_ranks_by_the_rarest_shared_concept_not_by_how_many(fab):
    """What a researcher means by "what else is about this". Two documents sharing a concept everything
    shares are not related in any useful sense; two sharing a rare one are. So the score is the specificity
    of the RAREST shared concept, and a document sharing several common concepts ranks BELOW one sharing a
    single precise concept.

    Document frequency is counted now, over the live graph, because specificity is a property of the corpus
    as it stands — a concept that distinguished a document among forty stops distinguishing it among four
    thousand."""
    c = [f"urn:lab:semantic:ref:syn#c{n}" for n in range(5)]
    me = _about(fab, "art://s/me", [c[0], c[1], c[2]])
    common = _about(fab, "art://s/common", [c[0], c[1]])     # two shared, both widespread
    precise = _about(fab, "art://s/precise", [c[2]])         # one shared, and nobody else has it
    _about(fab, "art://s/noise", [c[0], c[1], c[3]])
    _about(fab, "art://s/more-noise", [c[0], c[1], c[4]])

    out = fab.related(me)
    assert [r["iri"] for r in out] == [precise, common, *sorted({r["iri"] for r in out} - {precise, common})][:len(out)]
    assert out[0]["iri"] == precise, "one rare shared concept outranks two widespread ones"
    assert out[0]["score"] > out[1]["score"]
    assert out[0]["via"] == c[2], "the answer names WHICH concept earned the rank"
    assert [sh["concept"] for sh in out[0]["shared"]] == [c[2]]


def test_RELATED_does_not_pad_the_answer_with_links_worth_nothing(fab):
    """A concept carried by EVERY record in the population scores exactly zero: it would relate all of them
    to each other with equal confidence. The filter is already computed, so returning those rows would pad
    one answer with non-answers a caller — especially a model — cannot tell apart from the answer.

    The consequence is deliberate: where every record shares one subject, that subject relates nobody."""
    hub = "urn:lab:semantic:ref:syn#hub"
    me = _about(fab, "art://s/me", [hub])
    for n in range(4):
        _about(fab, f"art://s/other{n}", [hub])
    assert fab.related(me) == [], "a subject on the whole corpus is not a relation"


def test_RELATED_hides_a_withdrawn_record_exactly_as_search_does(fab):
    """The same corpus must not answer "what reads like this" without a withdrawn record and "what is about
    the same thing" with it. A withdrawn record is not knowledge any more."""
    rare = "urn:lab:semantic:ref:syn#rare"
    me = _about(fab, "art://s/me", [rare])
    gone = _about(fab, "art://s/gone", [rare], state="withdrawn")
    _about(fab, "art://s/filler", ["urn:lab:semantic:ref:syn#other"])

    assert fab.related(me) == []
    asked = fab.related(me, state="withdrawn")
    assert [r["iri"] for r in asked] == [gone], "hidden unless that state is ASKED for"
    assert asked[0]["state"] == "withdrawn", "and the row says so, so a caller can tell"


def test_RELATED_reads_the_catalogue_only_for_what_it_RETURNS(fab, monkeypatch):
    """Ranking happens on the graph, which is in process; the catalogue is Postgres in the cloud, where one
    read per CANDIDATE is a round trip each. Every record sharing any concept is a candidate, so hydrating
    before truncating is linear in the corpus to return `limit` rows."""
    concepts_ = [f"urn:lab:semantic:ref:syn#c{n}" for n in range(12)]
    me = _about(fab, "art://s/me", concepts_)
    for n, c in enumerate(concepts_):
        _about(fab, f"art://s/other{n}", [c])

    reads = []
    inner = fab.catalog.get
    monkeypatch.setattr(fab.catalog, "get", lambda i: (reads.append(i), inner(i))[1])
    out = fab.related(me, limit=3)
    assert len(out) == 3
    assert len(reads) == 3, f"one read per RETURNED row, not per candidate (got {len(reads)})"


def test_RELATED_caps_its_own_limit_so_one_call_cannot_hydrate_the_estate(fab):
    """A ceiling, as `corpus_view` has: an uncapped `limit` lets one tool call read the whole catalogue."""
    concepts_ = [f"urn:lab:semantic:ref:syn#c{n}" for n in range(105)]
    me = _about(fab, "art://s/me", concepts_)
    for n, c in enumerate(concepts_):
        _about(fab, f"art://s/other{n}", [c])      # one shared concept each, so all 105 score above zero
    assert len(fab.related(me, limit=10_000)) == 100
    assert len(fab.related(me, limit=0)) == 1, "...and a floor, so a caller cannot ask for nothing"


def test_RELATED_of_a_record_sharing_nothing_is_empty(fab):
    alone = fab.catalog_upsert({"source": "lab", "ref": "art://s/alone"})["iri"]
    assert fab.related(alone) == []


def test_HOW_a_record_was_READ_is_a_facet_so_a_reader_can_weigh_the_evidence(fab):
    """Phase 5. A concept grounded in a document's own words is stronger evidence than the same concept
    grounded in a machine translation of speech, and until now an assertion said `label-match` either way.

    The rendering rides the RECORD rather than each assertion, deliberately: one run produces one excerpt, so
    every term it grounds shares a rendering, and nothing in this layer reads per-assertion provenance — a
    field written there would be invisible, which is the shape of a defect this repo has already paid for."""
    iri = fab.catalog_upsert({"source": "lab", "ref": "art://run/minutes.json"}, title="Minutes")["iri"]
    fab.catalog_assert(iri, field="rendering", value="transcript-translated", rung="X", method="read-as")
    row = fab.catalog_get(iri)
    assert row["rendering"] == "transcript-translated"
    assert ("rendering", "X") in {(l["predicate"], l["rung"]) for l in row["links"]}
    assert renderings.weaker(row["rendering"], than="document"), "and a reader can ORDER it"


def test_an_undeclared_rendering_is_refused_like_any_other_facet_value(fab):
    iri = fab.catalog_upsert({"source": "lab", "ref": "art://run/x.json"})["iri"]
    with pytest.raises(ValueError, match="rendering"):
        fab.catalog_assert(iri, field="rendering", value="made-up", rung="X", method="read-as")


def test_a_term_LINKS_through_the_same_normaliser_the_semantic_tier_probes_with(fab):
    """`find` only strips and case-folds, but an extracted phrase arrives plural, with an article, or
    wrapped across two lines. Each of those missed a concept the vocabulary HOLDS — and the miss then parked
    a duplicate candidate for it, which is the defect `_held_by` exists to prevent, recreated one tier up.

    Two attempts, as the diagram lane already does, so the lexical and semantic tiers agree what a term is."""
    iri = fab.catalog_upsert({"source": "lab", "ref": "art://s/n"})["iri"]
    for term in ("Care Delivery", "the Care Delivery", "Care Deliverys", " care  delivery "):
        out = fab.vocab_link(iri, [term])
        assert [l["label"] for l in out["linked"]] == ["Care Delivery"], f"{term!r} must reach the concept"
        assert out["missed"] == []


def test_RE_READING_a_confirmed_record_does_not_mint_a_duplicate_subject_beneath_it(fab):
    """`G.promote` MOVES the triple to H — it does not leave an X copy, whatever two comments used to say.
    So a re-read that re-asserted at X put the same subject on the record at TWO rungs: `catalog_get`
    reported it twice, and the curator's `_link` read the first (X) and re-promoted on every review."""
    iri = fab.catalog_upsert({"source": "lab", "ref": "art://s/c"})["iri"]
    fab.vocab_link(iri, ["Care Delivery"])
    concept = next(l["concept"] for l in fab.vocab_link(iri, ["Care Delivery"])["linked"])
    fab.promote(iri, predicate=str(G.DCT.subject), obj=concept, actor="a@x", method="review")
    rungs = {r for r, _ in G.find(fab.ds, URIRef(iri), G.DCT.subject)}
    assert rungs == {CONFIRMED}, f"promotion moves it, leaving nothing at X: {rungs}"

    fab.vocab_link(iri, ["Care Delivery"])                 # the next sweep reads the same term
    rungs = {r for r, _ in G.find(fab.ds, URIRef(iri), G.DCT.subject)}
    assert rungs == {CONFIRMED}, f"and the re-read must not put a second copy under it: {rungs}"
    assert [l["predicate"] for l in fab.catalog_get(iri)["links"]].count("subject") == 1


def test_a_subject_a_PERSON_said_this_is_NOT_ABOUT_stays_gone(fab):
    """The asymmetry that made the owner's `drop` a lie. `keep` promotes to H and survives every sweep;
    `drop` retracted the X triple and recorded NOTHING, so the next classification matched the same label
    and put it straight back — and asked the owner again.

    The term register already takes the opposite stance for its own negatives: `vocab_decline` is durable
    because the answer was about the TERM. A document's "not about this" deserves the same, so it is
    recorded as a fact about the record and subtracted from what a label match may assert."""
    iri = fab.catalog_upsert({"source": "lab", "ref": "art://s/na"})["iri"]
    concept = fab.vocab_link(iri, ["Care Delivery"])["linked"][0]["concept"]

    fab.graph_not_about(iri, concept, actor="owner@x", reason="the document only mentions it in passing")
    assert [l for l in fab.catalog_get(iri)["links"] if l["predicate"] == "subject"] == []

    fab.vocab_link(iri, ["Care Delivery"])               # the next sweep reads the same term
    assert [l for l in fab.catalog_get(iri)["links"] if l["predicate"] == "subject"] == [], \
        "a person's NO is not undone by the next classification"
    assert fab.vocab_link(iri, ["Care Delivery"])["excluded"] == [concept], "...and the run SAYS it skipped it"


def test_a_person_can_change_their_mind_and_the_subject_returns(fab):
    """A NO is durable, not permanent. Confirming the subject afterwards clears the exclusion — otherwise
    one wrong tap would make a record permanently un-linkable to a concept, and nothing on screen would
    explain why the classifier kept ignoring it."""
    iri = fab.catalog_upsert({"source": "lab", "ref": "art://s/mind"})["iri"]
    concept = fab.vocab_link(iri, ["Care Delivery"])["linked"][0]["concept"]
    fab.graph_not_about(iri, concept, actor="owner@x", reason="mistake")
    assert fab.vocab_link(iri, ["Care Delivery"])["linked"] == []

    fab.graph_about_after_all(iri, concept, actor="owner@x")
    assert [l["concept"] for l in fab.vocab_link(iri, ["Care Delivery"])["linked"]] == [concept]


def test_TWO_TERMS_for_ONE_concept_link_it_ONCE(fab):
    """A run-killer, and the normaliser made it likely rather than rare. "Care Delivery", "Care Deliverys"
    and "the care delivery" are three terms and one concept — which is exactly what the second match
    attempt is FOR — but `linked` had one row per TERM, so the owner's card built three items keyed on the
    same concept IRI and `approvals_ask` refused the whole card for duplicate labels. The run died at the
    gate, on the first document whose extractor emitted a singular and a plural of the same noun.

    One row per CONCEPT: that is what a subject IS, it is what the card keys on, and it is what the run
    should count. It also stops a second provenance assertion being written for a triple already there."""
    iri = fab.catalog_upsert({"source": "lab", "ref": "art://s/dup"})["iri"]
    out = fab.vocab_link(iri, ["Care Delivery", "Care Deliverys", "the care delivery"])
    assert len({l["concept"] for l in out["linked"]}) == 1
    assert len(out["linked"]) == 1, f"one row per concept, got {out['linked']}"
    assert out["linked"][0]["term"] == "Care Delivery", "the first spelling that matched is the one reported"
    assert out["missed"] == []
    links = [l for l in fab.catalog_get(iri)["links"] if l["predicate"] == "subject"]
    assert len(links) == 1


def test_a_persons_NO_is_enforced_where_the_WRITE_happens_not_in_one_reader(fab):
    """`vocab_link` subtracting the exclusion was only the classifier's path. A steward's admission
    propagates `dct:subject` onto every record that proposed the term through `edge_assert` — a different
    door — so the owner's NO lasted until the next admission rather than for ever: a smaller version of
    exactly the asymmetry it was written to remove.

    So the rule lives where the triple is WRITTEN. One place enforces "a person said this record is not
    about this", and `vocab_link`'s subtraction becomes a consequence rather than the rule."""
    iri = fab.catalog_upsert({"source": "lab", "ref": "art://s/enforce"})["iri"]
    concept = fab.vocab_link(iri, ["Care Delivery"])["linked"][0]["concept"]
    fab.graph_not_about(iri, concept, actor="owner@x", reason="only mentioned in passing")

    with pytest.raises(ValueError, match="not about"):
        fab.graph_assert(iri, str(G.DCT.subject), concept, rung=EXTRACTED, method="vocabulary-admission")
    assert [l for l in fab.catalog_get(iri)["links"] if l["predicate"] == "subject"] == []

    # ...and it constrains THIS predicate only: the record may still be related, owned, typed, anything else.
    fab.graph_assert(iri, str(G.FAB.relatedTo), "urn:fabric:artifact:other", rung=EXTRACTED, method="x")
    fab.graph_about_after_all(iri, concept, actor="owner@x")
    assert fab.graph_assert(iri, str(G.DCT.subject), concept, rung=EXTRACTED, method="m")["assertion"]
