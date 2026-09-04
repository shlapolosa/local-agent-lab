"""SKOS reference schemes — built from SYNTHETIC in-memory tables and synthetic openpyxl workbooks
(never the licensed BA Guild workbooks): concept ids, the SKOS graph, subtree/find/stats, every
ArchiMate projection variant, the workbook parser's sheets (capability map, value streams, org,
stakeholder, information) and the loader's empty / env-var / unknown-stem paths.
Run: .venv/bin/python tests/unit/core/semantic/test_skos.py   (also pytest-compatible)"""
import os
import tempfile
from rdflib import RDF, RDFS, Literal, URIRef

from lab.core.semantic.ontology import META, Ontology
from lab.core.semantic.reference import baguild
from lab.core.semantic.skos import KIND_TO_ARCHIMATE, SKOS, SkosScheme, concept_id

from fixtures.skos import (BASE, scheme, write_workbook, HEALTH, INSURE)


# ---------------------------------------------------------------- tests
def test_concept_ids_are_stable_hashes_of_the_label_path():
    a = concept_id("s", ("Care Delivery", "Triage"))
    assert a == concept_id("s", ("Care Delivery", "Triage")) and a.startswith("cap-") and len(a) == 14
    assert a != concept_id("s", ("Triage",)) and a != concept_id("other", ("Care Delivery", "Triage"))


def test_scheme_queries_and_protocol():
    sc = scheme()
    assert isinstance(sc, Ontology) and str(sc.uri("c1")) == BASE + "c1" and str(sc.ns) == BASE
    assert sc.roots() == ["c1", "c2", "vs1", "i1", "i2"] and sc.roots("capability") == ["c1", "c2"]
    assert [c["id"] for c in sc.find(" triage ")] == ["c11"] and sc.find("nope") == []
    assert [c["id"] for c in sc.subtree()] == ["c1", "c11", "c111", "c12", "c2"]
    assert [c["id"] for c in sc.subtree("c1", depth=1)] == ["c1", "c11", "c12"]
    assert [c["id"] for c in sc.subtree(kind="information")] == ["i1", "i2"]
    assert sc.summary() == {"name": "syn-v1", "kind": "skos-scheme", "concepts": 8}
    assert sc.stats() == {"capability": {"L1": 2, "L2": 2, "L3": 1}, "value-stream": {"L1": 1}, "information": {"L1": 2}}


def test_skos_graph_shape():
    g = scheme().graph()
    S = URIRef(BASE.rstrip("#"))
    u = lambda c: URIRef(BASE + c)  # noqa: E731
    assert (S, RDF.type, SKOS.ConceptScheme) in g and (S, RDFS.label, Literal("Synthetic Model")) in g
    assert (S, META.source, Literal("fixture")) in g
    assert (u("c11"), SKOS.broader, u("c1")) in g and (u("c1"), SKOS.narrower, u("c11")) in g
    assert (u("c1"), SKOS.topConceptOf, S) in g and (S, SKOS.hasTopConcept, u("c2")) in g
    assert (u("c11"), SKOS.topConceptOf, S) not in g
    assert (u("c1"), SKOS.definition, Literal("Deliver care")) in g
    assert not list(g.triples((u("c12"), SKOS.definition, None)))               # None/'' definitions omitted
    assert (u("c1"), META.tier, Literal(1)) in g and (u("c1"), META.level, Literal(1)) in g
    assert not list(g.triples((u("vs1"), META.tier, None)))                      # tier None omitted
    assert (u("i1"), SKOS.related, u("i2")) in g and (u("i1"), META.kind, Literal("information")) in g
    assert len(list(g.triples((None, RDF.type, SKOS.Concept)))) == 8
    g2 = scheme(source=None).graph()
    assert not list(g2.triples((S, META.source, None)))


def test_archimate_projection_variants():
    sc = scheme()
    full = sc.to_archimate_spec()
    assert full["id"] == "syn-v1" and full["name"] == "Synthetic Model (capabilities)" and full["standard_views"] is False
    assert [e["id"] for e in full["elements"]] == ["c1", "c11", "c111", "c12", "c2"]
    assert all(e["type"] == "Capability" for e in full["elements"])
    assert full["elements"][0]["doc"] == "Synthetic Model · Tier 1 L1. Deliver care"
    assert full["elements"][3]["doc"] == "Synthetic Model · Tier 2 L2."                 # None definition -> ''
    assert {(r["src"], r["tgt"]) for r in full["relations"]} == {("c1", "c11"), ("c11", "c111"), ("c1", "c12")}
    assert full["relations"][0]["id"] == "comp-c11" and full["relations"][0]["type"] == "Composition"
    views = {v["id"]: v for v in full["views"]}
    assert views["syn-v1-overview"]["rows"] == [["c1", "c2"]] and "Capability Map (L1)" in views["syn-v1-overview"]["title"]
    assert views["syn-v1-care-delivery"] == {"id": "syn-v1-care-delivery", "title": "Care Delivery — L2 capabilities",
                                             "elements": ["c11", "c12", "c1"], "containers": [{"id": "c1", "children": ["c11", "c12"]}]}
    assert "syn-v1-billing" not in views                                                 # a top without children: no branch view
    # subtree under a root, depth-limited: name/id carry the root; overview rows wrap at row_width
    sub = sc.to_archimate_spec(root="c1", depth=1, row_width=1)
    assert sub["id"] == "syn-v1-care-delivery" and sub["name"] == "Synthetic Model (capabilities under Care Delivery)"
    assert [e["id"] for e in sub["elements"]] == ["c1", "c11", "c12"] and len(sub["relations"]) == 2
    assert sub["views"][0]["rows"] == [["c1"]] and len(sub["views"]) == 2
    # view selection
    assert [v["id"] for v in sc.to_archimate_spec(views="overview")["views"]] == ["syn-v1-overview"]
    assert [v["id"] for v in sc.to_archimate_spec(views="branches")["views"]] == ["syn-v1-care-delivery"]
    assert sc.to_archimate_spec(views="")["views"] == []
    # other kinds map to their ArchiMate type and plural
    vs = sc.to_archimate_spec(kind="value-stream")
    assert vs["elements"][0]["type"] == "ValueStream" and vs["name"] == "Synthetic Model (value streams)"
    info = sc.to_archimate_spec(kind="information", views="overview")
    assert {e["type"] for e in info["elements"]} == {"BusinessObject"} and info["relations"] == []
    odd = sc.to_archimate_spec(kind="mystery")
    assert odd["elements"] == [] and odd["name"] == "Synthetic Model (mystery)" and odd["views"] == []
    assert KIND_TO_ARCHIMATE["org-unit"] == "BusinessActor" and KIND_TO_ARCHIMATE["stakeholder"] == "Stakeholder"


def test_workbook_parser_every_sheet():
    with tempfile.TemporaryDirectory() as d:
        p = write_workbook(os.path.join(d, "health.xlsx"), caps=HEALTH,
                           value_streams=[("Admit Patient", "Arrive to bed"), ("", "blank name skipped")],
                           org=[(1, "Hospital", "", "The org"), (2, "Emergency", "", ""), (2, "Wards", "", ""), ("x", "junk", "", "")],
                           stakeholders=[("Internal", "Clinical", "Nurse", "Cares"), ("Internal", "Clinical", "Doctor", ""),
                                         ("External", "Payer", "Insurer", "Pays"), ("Internal", "Clinical", "", "no name skipped")],
                           info=[("Patient", "", "A person", "Master", "Encounter, Unknown", "Active"),
                                 ("Encounter", "", "A visit", "Transaction", "", ""), ("", "", "blank skipped", "", "", "")])
        sc = baguild.parse(p, "health-syn", "Health Synthetic")
    assert sc.name == "health-syn" and sc.base == "urn:lab:semantic:ref:health-syn#" and sc.source == "health.xlsx"
    caps = {c["label"]: c for c in sc.concepts.values() if c["kind"] == "capability"}
    assert set(caps) == {"Care Delivery", "Triage", "Urgent Triage", "Discharge", "Billing", "Claims"}
    assert caps["Care Delivery"]["parent"] is None and caps["Care Delivery"]["tier"] == 1
    assert caps["Triage"]["parent"] == caps["Care Delivery"]["id"] and caps["Urgent Triage"]["parent"] == caps["Triage"]["id"]
    assert caps["Discharge"]["parent"] == caps["Care Delivery"]["id"]                 # level stack pops back to L1
    assert caps["Claims"]["parent"] == caps["Billing"]["id"] and caps["Claims"]["level"] == 2
    assert caps["Care Delivery"]["id"] == concept_id("health-syn", ("Care Delivery",))
    assert caps["Urgent Triage"]["id"] == concept_id("health-syn", ("Care Delivery", "Triage", "Urgent Triage"))
    vs = [c for c in sc.concepts.values() if c["kind"] == "value-stream"]
    assert [(c["label"], c["definition"]) for c in vs] == [("Admit Patient", "Arrive to bed")]
    org = {c["label"]: c for c in sc.concepts.values() if c["kind"] == "org-unit"}
    assert org["Emergency"]["parent"] == org["Hospital"]["id"] == concept_id("health-syn", ("org", "Hospital"))
    assert org["Hospital"]["definition"] == "The org" and org["Hospital"]["tier"] is None
    st = {c["label"]: c for c in sc.concepts.values() if c["kind"] == "stakeholder"}
    assert set(st) == {"Clinical (Internal)", "Nurse", "Doctor", "Payer (External)", "Insurer"}
    assert st["Nurse"]["parent"] == st["Doctor"]["parent"] == st["Clinical (Internal)"]["id"] and st["Nurse"]["level"] == 2
    info = {c["label"]: c for c in sc.concepts.values() if c["kind"] == "information"}
    assert info["Patient"]["related"] == [info["Encounter"]["id"]] and info["Encounter"]["related"] == []
    assert info["Patient"]["types"] == "Master" and info["Patient"]["states"] == "Active"
    assert sc.stats()["capability"] == {"L1": 2, "L2": 3, "L3": 1}


def test_workbook_parser_without_capability_or_value_stream_sheets():
    with tempfile.TemporaryDirectory() as d:
        p = write_workbook(os.path.join(d, "org-only.xlsx"), org=[(1, "HQ", "", "")])
        sc = baguild.parse(p, "org-only", "Org Only")
        assert [c["kind"] for c in sc.concepts.values()] == ["org-unit"]
        empty = baguild.parse(write_workbook(os.path.join(d, "empty.xlsx")), "e", "E")
        assert empty.concepts == {} and empty.stats() == {}


def test_loader_paths():
    saved = os.environ.pop("REFERENCE_MODELS_DIR", None)
    try:
        with tempfile.TemporaryDirectory() as d:
            assert baguild.load_all(d) == []                                       # no sources at all
            write_workbook(os.path.join(d, "insurance-v5.0.xlsx"), caps=INSURE)
            write_workbook(os.path.join(d, "custom-model.xlsx"), caps=HEALTH[:2])
            schemes = baguild.load_all(d)
            assert [(s.name, s.title) for s in schemes] == [
                ("custom-model", "custom-model"),                                   # unknown stem -> stem as name+title
                ("insurance-v5.0", "BA Guild Insurance Reference Model v5.0")]     # KNOWN stem -> catalogue title
            os.environ["REFERENCE_MODELS_DIR"] = d
            assert [s.name for s in baguild.load_all()] == ["custom-model", "insurance-v5.0"]   # env var path
            os.environ["REFERENCE_MODELS_DIR"] = tempfile.mkdtemp(dir=d)
            assert baguild.load_all() == []
    finally:
        os.environ.pop("REFERENCE_MODELS_DIR", None)
        if saved is not None:
            os.environ["REFERENCE_MODELS_DIR"] = saved


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
