"""SemanticService + ontology core beyond the matrix contract: every QUESTIONS template over a
small instance model, the reference-scheme API (schemes/scheme/concepts/export) and the
skos:exactMatch mapping graph across two SYNTHETIC workbooks, describe/classify incl. unknown
types, Registry/Vocabulary/SemanticStore edges (facets, parents, limits, unbound OPTIONALs),
model_rdf doc/accessType triples. Offline — no licensed workbooks are ever read.
Run: .venv/bin/python tests/unit/core/semantic/test_semantic_more.py   (also pytest-compatible)"""
import os
import tempfile

from rdflib import OWL, RDF, RDFS, Literal, URIRef


from lab.core.semantic.model_rdf import model_iri, spec_to_triples
from lab.core.semantic.ontology import META, Registry, SemanticStore, Vocabulary
from lab.core.semantic.service import QUESTIONS, SemanticService
from fixtures.skos import HEALTH, INSURE, write_workbook

MODEL = {"name": "Lab slice", "elements": [
    {"id": "goal", "type": "Goal", "name": "Pattern parity", "doc": "Azure-shaped"},
    {"id": "cap", "type": "Capability", "name": "Governance"},
    {"id": "svc", "type": "ApplicationService", "name": "Routing"},
    {"id": "api", "type": "ApplicationInterface", "name": "/v1"},
    {"id": "orphan", "type": "ApplicationService", "name": "Unexposed"},
    {"id": "comp", "type": "ApplicationComponent", "name": "Gateway"},
    {"id": "proc", "type": "BusinessProcess", "name": "Intake"},
    {"id": "node", "type": "Node", "name": "Mac host"},
    {"id": "sysw", "type": "SystemSoftware", "name": "Python"},
    {"id": "data", "type": "DataObject", "name": "Ledger"},
], "relations": [
    {"id": "r1", "type": "Realization", "src": "comp", "tgt": "svc"},
    {"id": "r2", "type": "Realization", "src": "svc", "tgt": "cap"},
    {"id": "r3", "type": "Realization", "src": "cap", "tgt": "goal"},
    {"id": "r4", "type": "Assignment", "src": "node", "tgt": "sysw"},
    {"id": "r5", "type": "Serving", "src": "sysw", "tgt": "comp"},
    {"id": "r6", "type": "Serving", "src": "svc", "tgt": "proc"},
    {"id": "r7", "type": "Assignment", "src": "api", "tgt": "svc"},
    {"id": "r8", "type": "Serving", "src": "orphan", "tgt": "proc"},
    {"id": "r9", "type": "Serving", "src": "api", "tgt": "proc"},
    {"type": "Access", "src": "comp", "tgt": "data", "accessType": "ReadWrite"},
]}

_TMP = tempfile.mkdtemp(prefix="syn-ref-")
_SVC = None


def service():
    """One service with TWO synthetic schemes sharing the top capability 'Billing'."""
    global _SVC
    if _SVC is None:
        write_workbook(os.path.join(_TMP, "healthcare-provider-v2.0.xlsx"), caps=HEALTH,
                       value_streams=[("Admit Patient", "Arrive to bed")])
        write_workbook(os.path.join(_TMP, "insurance-v5.0.xlsx"), caps=INSURE)
        _SVC = SemanticService(reference_dir=_TMP)
        _SVC.load_model(MODEL, "slice")
    return _SVC


def test_schemes_and_exact_match_mappings():
    S = service()
    assert [s["name"] for s in S.schemes()] == ["healthcare-provider-v2.0", "insurance-v5.0"]
    h = S.schemes()[0]
    assert h["title"].startswith("BA Guild Healthcare") and h["source"] == "healthcare-provider-v2.0.xlsx"
    assert h["counts"] == {"capability": {"L1": 2, "L2": 3, "L3": 1}, "value-stream": {"L1": 1}}
    # Membership: the two reference schemes and the built-in metamodel must be there; a third
    # vocabulary registered elsewhere is not this test's business.
    assert {"archimate-3.1", "healthcare-provider-v2.0", "insurance-v5.0"} <= set(S.registry.names())
    try:
        S.scheme("nope")
    except KeyError as e:
        assert "unknown scheme nope" in str(e)
    else:
        raise AssertionError
    A, B = S.scheme("healthcare-provider-v2.0"), S.scheme("insurance-v5.0")
    g = S.store.ds.graph(URIRef("urn:lab:semantic:mappings"))
    pairs = {(str(s).split("#")[1], str(o).split("#")[1]) for s, _, o in g}
    ba, bb = A.find("Billing")[0]["id"], B.find("Billing")[0]["id"]
    assert pairs == {(ba, bb), (bb, ba)}                      # only the shared TOP capability, both directions
    r = S.ask("shared_reference_concepts")
    assert r["columns"] == ["concept", "schemeA", "schemeB"] and r["rows"] == [
        ["Billing", "BA Guild Healthcare Provider Reference Model v2.0", "BA Guild Insurance Reference Model v5.0"]]


def test_concepts_and_export_archimate_via_service():
    S = service()
    tree = S.concepts("healthcare-provider-v2.0", "care delivery")
    assert [c["label"] for c in tree] == ["Care Delivery", "Triage", "Urgent Triage", "Discharge"]
    assert set(tree[0]) == {"id", "label", "level", "tier", "parent", "definition"}
    assert [c["label"] for c in S.concepts("healthcare-provider-v2.0", "Care Delivery", depth=1)] == ["Care Delivery", "Triage", "Discharge"]
    assert [c["label"] for c in S.concepts("healthcare-provider-v2.0", kind="value-stream")] == ["Admit Patient"]
    assert len(S.concepts("insurance-v5.0")) == 3
    for fn in (S.concepts, S.export_archimate):
        try:
            fn("insurance-v5.0", "Care Delivery")
        except KeyError as e:
            assert "no capability named 'Care Delivery' in insurance-v5.0" in str(e)
        else:
            raise AssertionError
    spec = S.export_archimate("insurance-v5.0", "Billing", views="branches")
    assert [e["name"] for e in spec["elements"]] == ["Billing", "Premium Collection"]
    assert spec["views"][0]["containers"][0]["children"] == [spec["elements"][1]["id"]]
    assert S.export_archimate("insurance-v5.0")["views"][0]["rows"][0] == [c["id"] for c in S.concepts("insurance-v5.0") if c["parent"] is None]


def test_every_question_template():
    S = service()
    assert set(S.questions()) == set(QUESTIONS) and S.questions()["what_serves"] == {"params": ["element"], "doc": QUESTIONS["what_serves"]["doc"]}
    r = S.ask("goals_realized_by_components_on_node", node="mac")
    assert r["question"] == QUESTIONS["goals_realized_by_components_on_node"]["doc"]   # docs carry no %-placeholders
    assert r["rows"] == [["Mac host", "Gateway", "Pattern parity"]]         # node -assign-> sysw -serving-> comp -real*-> goal
    r = S.ask("what_serves", element="routing")
    assert r["rows"] == [["Routing", "serving", "Intake"]]
    r = S.ask("what_serves", element="python")
    assert r["rows"] == [["Python", "serving", "Gateway"]]
    r = S.ask("what_serves", element="Mac host")
    assert r["rows"] == [["Mac host", "derived serving", "Gateway"]]
    r = S.ask("services_without_interface")
    assert r["rows"] == [["Unexposed", "ApplicationService"]]                # Routing has /v1 assigned
    r = S.ask("concepts_under", label="care delivery")
    assert r["columns"] == ["scheme", "level", "concept", "definition"]
    assert [row[1:] for row in r["rows"]] == [["2", "Discharge", "Out"], ["2", "Triage", "Sort"], ["3", "Urgent Triage", None]]
    assert r["question"] == QUESTIONS["concepts_under"]["doc"]              # no %-placeholder in that doc
    r = S.ask("elements_by_layer_aspect")
    assert r["columns"] == ["layer", "aspect", "type", "element"] and len(r["rows"]) == 10
    assert r["rows"][0] == ["Application", "active", "ApplicationComponent", "Gateway"]
    assert ["Motivation", "behaviour", "Goal", "Pattern parity"] in r["rows"]
    for bad, exc in (("no_such_question", KeyError), ("what_serves", ValueError)):
        try:
            S.ask(bad)
        except exc as e:
            assert "unknown question" in str(e) or "missing params ['element']" in str(e)
        else:
            raise AssertionError(bad)


def test_validate_model_interface_serving_and_undeclared_endpoint():
    S = service()
    r = S.validate_model(MODEL)
    assert r["illegal"] == [] and r["elements"] == 10 and r["relations"] == 10
    assert r["warnings"] == ["orphan (ApplicationService) is consumed but no Interface is assigned to it — "
                             "add the access point (channel / API / port) and assign it to the service",
                             "api: interfaces expose services (Assignment interface->service); "
                             "Serving from an interface usually means the service relationship is missing"]
    r = S.validate_model({"elements": MODEL["elements"][:1], "relations": [{"type": "Serving", "src": "goal", "tgt": "ghost"}]})
    assert r["illegal"] == [{"relation": {"type": "Serving", "src": "goal", "tgt": "ghost"}, "reason": "endpoint not declared"}]


def test_load_model_replaces_and_counts_derivations():
    S = service()
    r = S.load_model(MODEL, "slice")
    assert r["model"] == model_iri("slice") and r["derived_relations"] == 7 and r["triples"] > 60
    # (api Serving proc is derivable too, but asserted as r9 -> not counted as derived)
    n = S.query(f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{model_iri('slice')}> {{ ?s ?p ?o }} }}")["rows"][0][0]
    assert int(n) == r["triples"]                                              # reload replaced, not appended
    T = spec_to_triples(MODEL, S.vocab(), "slice")
    base = model_iri("slice") + "#"
    assert (URIRef(base + "goal"), RDFS.comment, Literal("Azure-shaped")) in T
    assert any(p == META.accessType and o == Literal("ReadWrite") for _, p, o in T)
    assert S.store.load_model(model_iri("slice"), T[:3], replace=False) == r["triples"]   # append of known triples: same size
    assert S.query("SELECT ?s WHERE { ?s a <urn:lab:semantic:archimate#Goal> }", limit=1)["count"] == 1


def test_describe_classify_and_unknown_types():
    S = service()
    d = S.describe("ApplicationInterface")
    assert d["type"] == "ApplicationInterface" and d["layer"] == "Application" and d["aspect"] == "active" and d["definition"]
    assert S.describe("Relationship")["matrix_only"] is True                 # concept known to the matrix only
    assert "matrix_only" not in S.describe("Junction")                        # in the taxonomy proper
    for t in ("Nope", "AndJunction"):
        try:
            S.describe(t)
        except KeyError as e:
            assert f"{t} is not a archimate-3.1 type" in str(e)
        else:
            raise AssertionError(t)
    c = S.classify("a REST API endpoint exposed by the gateway component", limit=3)
    assert len(c) == 3 and c[0]["score"] >= c[1]["score"] >= c[2]["score"] and "type" in c[0]
    assert "ApplicationInterface" in {x["type"] for x in c}
    assert S.classify("zzzz qqqq") == [] and S.classify("") == []
    assert "Relationship" not in {x["type"] for x in S.classify("relationship concept", limit=62)}   # matrix-only never proposed
    assert S.check("Goal", "Influence", "Goal")["ok"] and not S.check("Nope", "Serving", "Goal")["ok"]
    assert S.check("Nope", "Serving", "Goal")["allowed"] == []


def test_vocabulary_graph_facets_parents_and_registry_edges():
    v = Vocabulary(name="mini-1", base="urn:mini#",
                   classes={"Thing": {"layer": "L1", "definition": "a thing", "examples": ["ex"], "confusable_with": "Stuff"},
                            "Stuff": {"parents": ["Thing"]}},
                   relations={"Uses": {"definition": "uses"}, "Bare": {}},
                   permitted={("Thing", "Stuff"): {"Uses"}},
                   facets={"layer": {"L1": "first", "L2": ""}}, rules=["keep it simple"])
    g = v.graph()
    ns = v.ns
    assert (ns.Thing, RDFS.subClassOf, ns.Layer_L1) in g and (ns.Thing, META.layer, META["layer-L1"]) in g
    assert (META["layer-L1"], RDFS.comment, Literal("first")) in g and not list(g.triples((META["layer-L2"], RDFS.comment, None)))
    assert (ns.Stuff, RDFS.subClassOf, ns.Thing) in g and not list(g.triples((ns.Stuff, META.layer, None)))
    assert (ns.Thing, META.confusableWith, Literal("Stuff")) in g and (ns.Thing, META.example, Literal("ex")) in g
    assert (ns.uses, RDF.type, OWL.ObjectProperty) in g and (ns.uses, RDFS.comment, Literal("uses")) in g
    assert (ns.bare, RDFS.label, Literal("Bare")) in g and not list(g.triples((ns.bare, RDFS.comment, None)))
    assert (URIRef("urn:mini"), META.rule, Literal("1. keep it simple")) in g
    assert len(list(g.triples((None, RDF.type, META.Permission)))) == 1
    assert v.describe("Stuff") == {"type": "Stuff", "parents": ["Thing"]} and v.allowed("Stuff", "Thing") == set()
    assert [x["type"] for x in v.classify("a thing")] == ["Thing"]        # name + definition hits; Stuff scores 0
    reg = Registry(); reg.add(v)
    try:
        reg.get("ghost")
    except KeyError as e:
        assert "unknown vocabulary ghost; have ['mini-1']" in str(e)
    else:
        raise AssertionError
    store = SemanticStore(reg)
    r = store.query("SELECT ?c WHERE { ?c a <http://www.w3.org/2002/07/owl#Class> } ORDER BY ?c", limit=2)
    assert r["count"] == 2 and r["columns"] == ["c"]                         # limit stops the row loop
    r = store.query("SELECT ?c ?d WHERE { ?c a <http://www.w3.org/2002/07/owl#Class> OPTIONAL { ?c <urn:none#x> ?d } } LIMIT 1")
    assert r["rows"][0][1] is None                                             # unbound OPTIONAL -> None
    assert store._short(URIRef("http://x.org/path/Leaf")) == "Leaf" and store._short(Literal(3)) == "3"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
