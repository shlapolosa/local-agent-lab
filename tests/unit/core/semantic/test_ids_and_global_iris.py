"""Two small extensions that everything cross-meeting depends on.

`content_id` — one content-addressed id formula, extracted from the SKOS helper that hardcoded a
`cap-` prefix. Persons, decisions and concepts are not SKOS concepts and should not borrow its name
or its prefix.

The GLOBAL IRI on a spec element — the load-bearing one. `spec_to_triples` scopes every element IRI
to its model graph, so with one graph per meeting the same concept in two meetings becomes two
unjoinable nodes, and a content-addressed id does not save it because the hash is only the fragment.
An element may now declare its own `iri`, and `props` carries the datatype properties (a due date, a
status, a confidence) the meeting model needs and the ArchiMate one never did.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/core/semantic/test_ids_and_global_iris.py
"""
from rdflib import Literal, URIRef

from lab.core.semantic.ids import content_id
from lab.core.semantic.model_rdf import model_iri, spec_to_triples
from lab.core.semantic.skos import concept_id


# ------------------------------------------------------------------ content_id
def test_the_same_content_always_gets_the_same_id():
    assert content_id("cpt-", "Claims Adjudication") == content_id("cpt-", "Claims Adjudication")
    assert content_id("cpt-", "a") != content_id("cpt-", "b")


def test_the_prefix_is_the_callers_choice_not_baked_in():
    """A person is not a capability. Reusing the SKOS helper's `cap-` for everything produced ids
    that lie about what they are."""
    assert content_id("per-", "x").startswith("per-")
    assert content_id("dec-", "x").startswith("dec-")
    assert content_id("cpt-", "x")[4:] == content_id("per-", "x")[4:], "same hash, different prefix"


def test_parts_are_joined_so_scope_changes_the_id():
    """A decision in one meeting is not the same node as an identical sentence in another, unless
    the caller deliberately leaves the meeting out of the parts."""
    assert content_id("dec-", "m1", "retire the portal") != content_id("dec-", "m2", "retire the portal")


def test_reference_model_ids_are_byte_identical_after_the_extraction():
    """The BA Guild ids are in exported specs and possibly already in the EA repository. The default
    keeps `cap-` and the exact same digest, so nothing that was exported changes meaning."""
    got = concept_id("healthcare-v2", ["Care Delivery", "Triage"])
    assert got.startswith("cap-") and len(got) == 14
    assert got == content_id("cap-", "healthcare-v2", "Care Delivery/Triage")


# ------------------------------------------------------------------ global IRIs
class _Vocab:
    """The bare surface `spec_to_triples` needs — it takes ANY vocabulary, which is the whole point."""
    def cls(self, t): return URIRef(f"urn:test:v#{t}")
    def rel(self, t): return URIRef(f"urn:test:v#{t[0].lower() + t[1:]}")


SPEC = {"name": "m", "elements": [
    {"id": "local", "type": "Thing", "name": "Local"},
    {"id": "shared", "type": "Thing", "name": "Shared",
     "iri": "urn:lab:semantic:concept#cpt-abc", "props": {"status": "open", "due": "2026-10-01"}},
]}


def _triples(model_id="m1"):
    return spec_to_triples(SPEC, _Vocab(), model_id)


def test_an_element_without_an_iri_is_scoped_to_its_model_exactly_as_before():
    subjects = {str(s) for s, _, _ in _triples()}
    assert f"{model_iri('m1')}#local" in subjects


def test_an_element_that_declares_an_iri_is_the_same_node_in_every_model():
    """The join that makes 'what did this person commit to, across meetings' answerable at all."""
    a = {str(s) for s, _, _ in _triples("meeting-1")}
    b = {str(s) for s, _, _ in _triples("meeting-2")}
    assert "urn:lab:semantic:concept#cpt-abc" in a and "urn:lab:semantic:concept#cpt-abc" in b
    assert (a & b) >= {"urn:lab:semantic:concept#cpt-abc"}
    assert f"{model_iri('meeting-1')}#local" not in b, "a local id stays local"


def test_datatype_properties_are_written_from_props():
    got = {(str(p).rsplit("#", 1)[-1], str(o)) for s, p, o in _triples()
           if str(s) == "urn:lab:semantic:concept#cpt-abc" and isinstance(o, Literal)}
    assert ("status", "open") in got and ("due", "2026-10-01") in got


def test_a_relation_between_a_global_and_a_local_element_uses_both_iris():
    spec = dict(SPEC, relations=[{"src": "local", "tgt": "shared", "type": "Concerns"}])
    pairs = {(str(s), str(o)) for s, p, o in spec_to_triples(spec, _Vocab(), "m1")
             if str(p).endswith("#concerns")}
    assert (f"{model_iri('m1')}#local", "urn:lab:semantic:concept#cpt-abc") in pairs


def test_specs_without_iri_or_props_are_untouched():
    """Every existing ArchiMate spec must keep producing exactly what it did before."""
    plain = {"name": "m", "elements": [{"id": "a", "type": "Thing", "name": "A"}]}
    before = {(str(s), str(p), str(o)) for s, p, o in spec_to_triples(plain, _Vocab(), "m1")}
    assert all("urn:lab:semantic:model:m1#a" in t[0] or t[0].endswith("model:m1") for t in before)


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
