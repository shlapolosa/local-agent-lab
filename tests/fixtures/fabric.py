"""A small fabric graph for the competency-question tests: three artifacts, two delivery contexts, edges at
every rung, subjects from the synthetic SKOS scheme in `fixtures.skos`. Pure rdflib; no store, no server."""
from rdflib import RDF, Dataset, Literal, Namespace, URIRef

from fixtures.skos import BASE as SCHEME_BASE, scheme
from lab.core.semantic.fabric import graph as G
from lab.core.semantic.fabric.rungs import CONFIRMED, CONSTRUCTED, EXTRACTED, SUGGESTED, graph_iri

FAB, DCT, DCAT, SKOS = G.FAB, G.DCT, Namespace("http://www.w3.org/ns/dcat#"), G.SKOS
A1 = URIRef("urn:fabric:artifact:01J9X5K7QZ3M8N2P4R6T8V0W1Y")   # minutes, published
A2 = URIRef("urn:fabric:artifact:01J9X5M2ABCDEFGHJKMNPQRSTV")   # decision record, references A1
A3 = URIRef("urn:fabric:artifact:01J9X5N3ABCDEFGHJKMNPQRSTV")   # a document a person edited, unlinked
MEETING = URIRef("urn:fabric:context:meeting:AAMk1")
USECASE = URIRef("urn:fabric:context:usecase:UC-42")
OWNER = URIRef("urn:fabric:person:oid-3f2a")
C_CARE = URIRef(SCHEME_BASE + "c1")       # Care Delivery
C_TRIAGE = URIRef(SCHEME_BASE + "c11")    # Triage (narrower of Care Delivery)
DT_MINUTES = URIRef("urn:fabric:scheme:doc-types#minutes")


def dataset() -> Dataset:
    ds = Dataset(default_union=True)
    # the vocabulary: the synthetic scheme, so narrower-closure questions can be asked
    ds.graph(URIRef("urn:lab:semantic:vocab:syn-v1")).__iadd__(scheme().graph())
    # catalog facts — constructed
    c = ds.graph(graph_iri(CONSTRUCTED))
    for a, title, url, state in ((A1, "Minutes 2026-09-01", "https://tenant/sites/ea/minutes.docx", FAB.Published),
                                 (A2, "ADR-014 Event bus", "https://tenant/sites/ea/adr-014.docx", FAB.InReview),
                                 (A3, "Integration notes", "https://tenant/sites/ea/notes.docx", FAB.Pending)):
        c.add((a, RDF.type, FAB.Artifact)); c.add((a, DCT.title, Literal(title)))
        c.add((a, DCAT.accessURL, URIRef(url))); c.add((a, FAB.lifecycleState, state))
        G.assert_triple(ds, a, FAB.ownedBy, OWNER, rung=CONSTRUCTED, method="owner-map")
        G.assert_triple(ds, a, FAB.sensitivityLabel, Literal("Confidential"), rung=CONSTRUCTED, method="inherited-label")
    c.add((A3, FAB.unassociated, Literal(True)))
    c.add((A1, FAB.baselineVersion, Literal("3.0")))
    # delivery edges: A1 linked at creation (C); A2 confirmed by a card (H); A3 only suggested (S)
    G.assert_triple(ds, A1, FAB.deliveredUnder, MEETING, rung=CONSTRUCTED, method="link-at-creation")
    G.assert_triple(ds, A2, FAB.deliveredUnder, USECASE, rung=CONFIRMED, method="one-tap card", actor="reviewer@x.org")
    G.assert_triple(ds, A3, FAB.deliveredUnder, USECASE, rung=SUGGESTED, method="author+time", confidence=0.61)
    # structural: A2 references A1 (extracted from an embedded link)
    G.assert_triple(ds, A2, FAB.references, A1, rung=EXTRACTED, method="link-extraction")
    # subjects: A1 about Triage (label match, X); A2 about Care Delivery (confirmed, H); A3 suggested
    G.assert_triple(ds, A1, DCT.subject, C_TRIAGE, rung=EXTRACTED, method="label-match")
    G.assert_triple(ds, A2, DCT.subject, C_CARE, rung=CONFIRMED, method="approval", actor="reviewer@x.org")
    G.assert_triple(ds, A3, DCT.subject, C_CARE, rung=SUGGESTED, method="nearest-neighbour", confidence=0.7)
    # type: A1's is a fact (produced by the minutes run); A2's is suggested
    G.assert_triple(ds, A1, FAB.documentType, DT_MINUTES, rung=CONSTRUCTED, method="produced-by")
    G.assert_triple(ds, A2, FAB.documentType, URIRef("urn:fabric:scheme:doc-types#decision-record"), rung=SUGGESTED, method="model", confidence=0.83)
    return ds
