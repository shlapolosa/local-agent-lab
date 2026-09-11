"""NFR-2 and NFR-3 as executable shapes: content in a fabric store fails; an owner not looked up fails."""
from rdflib import RDF, Literal, URIRef

from fixtures.fabric import A1, FAB, dataset
from lab.core.semantic.fabric import shapes
from lab.core.semantic.fabric.rungs import SUGGESTED, graph_iri


def test_the_fixture_conforms():
    report = shapes.validate(dataset())
    assert report.conforms, report.messages


def test_a_content_property_is_refused_however_it_is_spelled():
    ds = dataset()
    ds.graph(graph_iri("C")).add((A1, FAB.body, Literal("the whole document text …")))
    report = shapes.validate(ds)
    assert not report.conforms
    ds2 = dataset()
    ds2.graph(graph_iri("C")).add((A1, URIRef("urn:fabric:ont#content"), Literal("text")))
    assert not shapes.validate(ds2).conforms


def test_a_title_is_a_label_not_a_body():
    ds = dataset()
    ds.graph(graph_iri("C")).add((A1, URIRef("http://purl.org/dc/terms/title"), Literal("x" * 301)))
    assert not shapes.validate(ds).conforms


def test_an_owner_guessed_by_a_model_is_refused():
    ds = dataset()
    other = URIRef("urn:fabric:artifact:01J9X5P4ABCDEFGHJKMNPQRSTV")
    c = ds.graph(graph_iri("C"))
    c.add((other, RDF.type, FAB.Artifact)); c.add((other, URIRef("http://www.w3.org/ns/dcat#accessURL"), URIRef("https://t/x")))
    c.add((other, FAB.lifecycleState, FAB.Pending))
    ds.graph(graph_iri(SUGGESTED)).add((other, FAB.ownedBy, URIRef("urn:fabric:person:guessed")))
    report = shapes.validate(ds)
    assert not report.conforms and any("NFR-3" in m for m in report.messages)


def test_an_artifact_without_custody_is_refused():
    ds = dataset()
    orphan = URIRef("urn:fabric:artifact:01J9X5Q5ABCDEFGHJKMNPQRSTV")
    c = ds.graph(graph_iri("C"))
    c.add((orphan, RDF.type, FAB.Artifact)); c.add((orphan, FAB.lifecycleState, FAB.Pending))
    assert not shapes.validate(ds).conforms
