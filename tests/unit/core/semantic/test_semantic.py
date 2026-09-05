"""Semantic layer contract — offline (taxonomy + Appendix-B matrix ship in the repo; reference
schemes are built synthetically, never from the licensed workbooks).
Run: .venv/bin/python tests/unit/core/semantic/test_semantic.py   (also pytest-compatible)"""
import tempfile


from lab.core.semantic.ontology import Ontology, Registry, SemanticStore, Vocabulary
from lab.core.semantic.service import SemanticService
from lab.core.semantic.skos import SkosScheme

_SVC = None


def service():
    """One SemanticService for the module, with NO reference workbooks (empty dir)."""
    global _SVC
    if _SVC is None:
        _SVC = SemanticService(reference_dir=tempfile.mkdtemp(prefix="no-ref-models-"))
    return _SVC


# ---- Appendix-B matrix contract: known permitted / forbidden triples (ArchiMate 3.1) ----
PERMITTED = [
    ("ApplicationComponent", "Realization", "ApplicationService"),
    ("ApplicationComponent", "Composition", "ApplicationInterface"),
    ("ApplicationInterface", "Assignment", "ApplicationService"),
    ("ApplicationComponent", "Assignment", "ApplicationFunction"),
    ("ApplicationFunction", "Realization", "ApplicationService"),
    ("ApplicationService", "Serving", "BusinessProcess"),
    ("ApplicationFunction", "Access", "DataObject"),
    ("Node", "Assignment", "SystemSoftware"),
    ("TechnologyService", "Serving", "ApplicationComponent"),
    ("ApplicationComponent", "Realization", "Requirement"),
    ("Resource", "Assignment", "Capability"),
    ("Capability", "Realization", "Outcome"),
    ("BusinessEvent", "Triggering", "BusinessProcess"),
    ("WorkPackage", "Realization", "Plateau"),
    ("Plateau", "Aggregation", "ApplicationComponent"),
    ("Stakeholder", "Association", "Driver"),
]
FORBIDDEN = [
    ("DataObject", "Serving", "ApplicationComponent"),         # passive cannot serve
    ("ApplicationService", "Composition", "BusinessProcess"),  # no cross-layer composition
    ("ApplicationComponent", "Access", "ApplicationComponent"),  # access targets passive only
    ("BusinessActor", "Realization", "ApplicationComponent"),
    ("DataObject", "Access", "ApplicationFunction"),
    ("ApplicationInterface", "Serving", "DataObject"),
    ("Goal", "Serving", "ApplicationComponent"),
    ("ApplicationComponent", "Composition", "BusinessActor"),
]


def test_matrix_contract():
    S = service()
    for s, r, t in PERMITTED:
        c = S.check(s, r, t)
        assert c["ok"], f"expected permitted: {s} {r} {t} (allowed: {c['allowed']})"
    for s, r, t in FORBIDDEN:
        c = S.check(s, r, t)
        assert not c["ok"], f"expected forbidden: {s} {r} {t}"
        assert r not in c["allowed"]
    v = S.vocab()
    assert len(v.classes) >= 61 and len(v.permitted) > 3000    # full Appendix B, not a sample


def test_validate_model_illegal_and_interface_warning():
    """One illegal relation + one consumed service with no interface -> exactly 1 illegal, 1 warning."""
    spec = {"name": "fixture", "elements": [
        {"id": "comp", "type": "ApplicationComponent", "name": "Gateway"},
        {"id": "svc", "type": "ApplicationService", "name": "Routing"},
        {"id": "proc", "type": "BusinessProcess", "name": "Intake"},
        {"id": "data", "type": "DataObject", "name": "Ledger"},
    ], "relations": [
        {"id": "r1", "type": "Realization", "src": "comp", "tgt": "svc"},
        {"id": "r2", "type": "Serving", "src": "svc", "tgt": "proc"},      # consumed, no interface
        {"id": "r3", "type": "Serving", "src": "data", "tgt": "comp"},     # illegal
    ]}
    r = service().validate_model(spec)
    assert len(r["illegal"]) == 1 and r["illegal"][0]["id"] == "r3", r["illegal"]
    assert r["illegal"][0]["types"] == "DataObject -> ApplicationComponent"
    assert len(r["warnings"]) == 1 and r["warnings"][0].startswith("svc (ApplicationService)"), r["warnings"]
    assert r["elements"] == 4 and r["relations"] == 3
    # add the access point: Assignment interface -> service clears the warning
    spec["elements"].append({"id": "api", "type": "ApplicationInterface", "name": "/v1"})
    spec["relations"].append({"id": "r4", "type": "Assignment", "src": "api", "tgt": "svc"})
    assert service().validate_model(spec)["warnings"] == []


def synthetic_scheme():
    return SkosScheme("synthetic-v1", "urn:lab:semantic:ref:synthetic#", "Synthetic Ref", [
        {"id": "c1", "label": "Care Delivery", "definition": "Deliver care", "kind": "capability",
         "parent": None, "level": 1, "tier": "core"},
        {"id": "c2", "label": "Triage", "definition": "", "kind": "capability",
         "parent": "c1", "level": 2, "tier": "core"},
        {"id": "c3", "label": "Discharge", "definition": "", "kind": "capability",
         "parent": "c1", "level": 2, "tier": "core"},
    ], source="in-code fixture")


def test_ontology_protocol_on_both_kinds():
    S = service()
    vocab, scheme = S.vocab(), synthetic_scheme()
    for o in (vocab, scheme):
        assert isinstance(o, Ontology), type(o)
        assert isinstance(o.name, str) and o.base.startswith("urn:")
        assert str(o.ns).startswith(o.base)
        assert len(o.graph()) > 0
        assert o.summary()["name"] == o.name and o.summary()["kind"]
    assert vocab.summary() == {"name": "archimate-3.1", "kind": "metamodel", "classes": len(vocab.classes),
                               "relations": len(vocab.relations), "permitted_pairs": len(vocab.permitted)}
    assert scheme.summary() == {"name": "synthetic-v1", "kind": "skos-scheme", "concepts": 3}


def test_registry_ontologies_and_vocab_kind_error():
    S = SemanticService(reference_dir=tempfile.mkdtemp(prefix="no-ref-models-"))
    sc = synthetic_scheme()
    S.registry.add(sc); S.schemes_[sc.name] = sc
    names = S.registry.names()
    # Membership, not a census: registering another vocabulary is an additive change and must not
    # break an unrelated test (decision Sep 4 2026).
    assert {"archimate-3.1", "synthetic-v1"} <= set(names)
    assert S.ontologies() == [S.registry.get(n).summary() for n in names]
    assert S.vocab("archimate-3.1") is S.vocab()
    try:
        S.vocab("synthetic-v1")
    except TypeError as e:
        assert "skos-scheme" in str(e) and "synthetic-v1" in str(e)
    else:
        raise AssertionError("vocab() must refuse a non-metamodel entry")
    # a SKOS scheme is still reachable through the scheme API and projects to an engine spec
    spec = S.export_archimate("synthetic-v1", "Care Delivery")
    assert [e["type"] for e in spec["elements"]] == ["Capability"] * 3
    assert len(spec["relations"]) == 2 and spec["views"][0]["rows"] == [["c1"]]


def test_store_has_no_dead_models_api_and_queries_union():
    S = service()
    assert not hasattr(SemanticStore, "models"), "SemanticStore.models() was dead code — deleted"
    assert not hasattr(SemanticService, "export_ttl"), "SemanticService.export_ttl was dead code — deleted"
    r = S.query("SELECT (COUNT(?c) AS ?n) WHERE { ?c a <http://www.w3.org/2002/07/owl#Class> }")
    assert r["count"] == 1 and int(r["rows"][0][0]) >= 61


def test_engine_semantic_is_cached():
    from lab.core.archimate import engine as E
    E._semantic.cache_clear()
    a = E._semantic()
    b = E._semantic()
    assert a is not None and a is b
    assert E._semantic.cache_info().hits >= 1 and E._semantic.cache_info().misses == 1


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"ok  {name}")
    print("ALL TESTS PASSED")
