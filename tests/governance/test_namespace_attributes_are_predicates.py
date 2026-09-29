"""`FAB.term` is not a predicate — it is rdflib's `Namespace.term` METHOD, and the triple built from it fails
deep inside rdflib with "Predicate ... must be an rdflib term", far from the line that wrote it.

An `rdflib.Namespace` is a `str` subclass whose `__getattr__` mints an IRI — but only for names the class does
not already have. So `FAB.title`, `FAB.split`, `FAB.index`, `FAB.count`, `FAB.term` and about forty others
resolve to a bound method instead, and the code reads exactly like the code beside it that works. Measured
29 Sep 2026: `FAB.term` for a vocabulary conflict.

The fix is to name the predicate something the base classes do not use, which is also better naming
(`conflictTerm` says whose term it is). This test finds the collision at the source, offline.
"""
import ast
import importlib
import pathlib

from rdflib import Namespace, URIRef

ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "lab"

#: the attributes a PLAIN `Namespace` answers itself, so `__getattr__` never mints an IRI for them. A
#: `DefinedNamespace` (DCTERMS, SKOS, PROV) is a class whose terms are declared, so `DCT.title` is a real
#: predicate — which is why the object is resolved below rather than the name being judged on its spelling.
SHADOWED = {n for n in dir(Namespace("urn:x:"))
            if not n.startswith("__") and not isinstance(getattr(Namespace("urn:x:"), n), URIRef)}


def _module_of(path: pathlib.Path):
    dotted = ".".join(path.relative_to(ROOT.parent).with_suffix("").parts)
    try:
        return importlib.import_module(dotted)
    except Exception:                                    # a module that needs a client to import is not our subject
        return None


def test_no_namespace_attribute_silently_resolves_to_a_method():
    bad = []
    for path in sorted(ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text())
        suspects = {(n.value.id, n.attr, n.lineno) for n in ast.walk(tree)
                    if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.attr in SHADOWED}
        if not suspects:
            continue
        module = _module_of(path)
        if module is None:
            continue
        for name, attr, line in sorted(suspects, key=lambda s: s[2]):
            ns = getattr(module, name, None)
            # only a PLAIN Namespace instance mints by __getattr__; anything else defines its own terms
            if isinstance(ns, Namespace) and not isinstance(getattr(ns, attr, None), URIRef):
                bad.append(f"{path.relative_to(ROOT.parent.parent)}:{line}: {name}.{attr} resolves to "
                           f"{type(getattr(ns, attr)).__name__}, not an IRI — use {name}[{attr!r}] "
                           "or rename the predicate")
    assert not bad, "\n".join(bad)


def test_the_guard_would_have_caught_the_one_that_got_through():
    """The collision this test was written for, so the guard cannot quietly stop working."""
    assert "term" in SHADOWED and not isinstance(Namespace("urn:x:").term, str)
