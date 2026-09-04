"""model_rdf derivation rules (ArchiMate 3.1 §5.7) on a small in-code chain — offline, no vocab files.
Run: .venv/bin/python tests/unit/core/semantic/test_model_rdf.py   (also pytest-compatible)"""

from rdflib import RDFS, Literal, URIRef


from lab.core.semantic.model_rdf import derive, model_iri, spec_to_triples
from lab.core.semantic.ontology import Vocabulary

V = Vocabulary(name="t-1.0", base="urn:t#")          # cls()/rel()/ns are all derive() needs
BASE = model_iri("m1") + "#"
E = lambda eid: URIRef(BASE + eid)  # noqa: E731

CHAIN = {"name": "chain", "elements": [
    {"id": "comp", "type": "ApplicationComponent", "name": "Gateway"},
    {"id": "svc", "type": "ApplicationService", "name": "Routing"},
    {"id": "cap", "type": "Capability", "name": "Governance"},
    {"id": "goal", "type": "Goal", "name": "Pattern parity"},
    {"id": "node", "type": "Node", "name": "Mac"},
    {"id": "sysw", "type": "SystemSoftware", "name": "Python"},
], "relations": [
    {"id": "r1", "type": "Realization", "src": "comp", "tgt": "svc"},
    {"id": "r2", "type": "Realization", "src": "svc", "tgt": "cap"},
    {"id": "r3", "type": "Realization", "src": "cap", "tgt": "goal"},
    {"id": "r4", "type": "Assignment", "src": "node", "tgt": "sysw"},
    {"id": "r5", "type": "Serving", "src": "sysw", "tgt": "comp"},
]}


def _derived(spec):
    return {(str(s).split("#")[1], str(p).split("#")[1], str(o).split("#")[1]) for s, p, o in derive(spec, V, E)}


def test_structural_chain_derives_weakest_and_dependency_carries():
    d = _derived(CHAIN)
    assert ("comp", "derivedRealization", "cap") in d
    assert ("comp", "derivedRealization", "goal") in d
    assert ("svc", "derivedRealization", "goal") in d
    assert ("node", "derivedServing", "comp") in d        # structural chain then dependency
    assert not any(s == o for s, _, o in d)              # no self-loops
    assert not any(p == "derivedRealization" and s == "comp" and o == "svc" for s, p, o in d)  # asserted, not derived
    assert len(d) == 4, d


def test_weakest_relation_in_mixed_chain():
    spec = {"elements": [], "relations": [
        {"type": "Composition", "src": "a", "tgt": "b"},
        {"type": "Assignment", "src": "b", "tgt": "c"},
        {"type": "Realization", "src": "c", "tgt": "d"},
    ]}
    d = _derived(spec)
    assert ("a", "derivedAssignment", "c") in d           # min(Composition, Assignment)
    assert ("a", "derivedRealization", "d") in d          # Realization is weakest
    assert ("b", "derivedRealization", "d") in d


def test_cycle_excludes_self_loops_and_dependency_alone_derives_nothing():
    cyc = {"elements": [], "relations": [{"type": "Composition", "src": "a", "tgt": "b"},
                                         {"type": "Composition", "src": "b", "tgt": "a"}]}
    assert _derived(cyc) == set()                         # a->b->a would be a self loop; b->a->b too
    dep = {"elements": [], "relations": [{"type": "Serving", "src": "a", "tgt": "b"},
                                         {"type": "Serving", "src": "b", "tgt": "c"}]}
    assert _derived(dep) == set()                         # dependencies never chain on their own


def test_spec_to_triples_labels_every_element_once():
    T = spec_to_triples(CHAIN, V, "m1")
    labels = [(s, o) for s, p, o in T if p == RDFS.label and s != URIRef(model_iri("m1"))]
    assert len(labels) == len(CHAIN["elements"])
    assert (E("comp"), Literal("Gateway")) in labels
    assert sum(1 for _, p, _ in T if "derived" in str(p)) == 4
    unnamed = {"elements": [{"id": "x", "type": "Node", "name": ""}], "relations": []}
    assert not [1 for s, p, o in spec_to_triples(unnamed, V, "m2") if p == RDFS.label and s == URIRef(model_iri("m2") + "#x")]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"ok  {name}")
    print("ALL TESTS PASSED")
