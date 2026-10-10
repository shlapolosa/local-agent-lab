"""The CORPUS view — every record and what it is about, in one picture.

The sibling of `topology.view_of`, and they divide by the question asked. `view_of` answers "what is THIS
record about, and what does the vocabulary connect that to" — one focus, a handful of nodes. This one
answers "what is our knowledge about, and what is it silent on", which has no focus and only means
anything at scale.

It was built because drawing the whole catalogue by hand first (10 Oct 2026) showed two things a table of
counts had hidden for weeks: one concept, `Use case`, held half the links, and two thirds of the corpus
was the lab's OWN test output rather than documents anybody wrote. Both are findings; neither is visible
without the picture, and neither is READABLE without being able to narrow it. So every record node carries
the facets a person narrows by, and the vocabulary's own edges are in the view — otherwise it shows
co-occurrence and calls it meaning.

Pure: dicts in, a TopologyView out. No store, no HTTP.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/core/semantic/fabric/test_corpus.py
"""
from lab.core.semantic.fabric.corpus import view_of_corpus
from lab.core.viz import ARTIFACT, CONCEPT, VOCABULARY

REQ = "urn:lab:semantic:domain:cafe#Requirement"
UC = "urn:lab:semantic:domain:cafe#UseCase"
GUARD = "urn:lab:semantic:domain:cafe#Guardrail"


def _rec(iri, title, *subjects, state="published", source="collab", dt="", rung="X"):
    return {"iri": iri, "title": title, "state": state, "document_type": dt,
            "pointer": {"source": source},
            "links": [{"predicate": "subject", "object": s, "rung": rung, "label": s.rsplit("#", 1)[-1]}
                      for s in subjects] + [{"predicate": "ownedBy", "object": "urn:fabric:person:x",
                                             "rung": "C"}]}


class _Scheme:
    """The least a vocabulary must do to put its own edges on the picture."""
    concepts = {"Requirement": {"label": "Requirement"}, "UseCase": {"label": "Use case"},
                "Guardrail": {"label": "Guardrail"}}

    def uri(self, term):
        return f"urn:lab:semantic:domain:cafe#{term}"

    def relations_of(self, term):
        return [("constrains", "Requirement", "in")] if term == "Guardrail" else []


def test_records_and_their_subjects_become_one_picture_with_no_focus():
    v = view_of_corpus([_rec("a", "BRS.md", REQ), _rec("b", "ADR.md", REQ, UC)])
    assert v.focus == ""                                    # a corpus has no centre, and saying so matters
    assert {n.label for n in v.nodes if n.kind == ARTIFACT} == {"BRS.md", "ADR.md"}
    assert {n.label for n in v.nodes if n.kind == CONCEPT} == {"Requirement", "UseCase"}
    assert [(e.source, e.target) for e in v.edges] == [("a", REQ), ("b", REQ), ("b", UC)]
    assert all(e.label == "about" for e in v.edges)


def test_a_record_with_no_subject_is_counted_and_NOT_drawn():
    """40 of 100 on the first real run. A node with no edge pads the rim and says nothing; the COUNT is
    the finding, so it goes in the subtitle where a person reads it."""
    v = view_of_corpus([_rec("a", "BRS.md", REQ), _rec("b", "recording.mp4")])
    assert {n.id for n in v.nodes if n.kind == ARTIFACT} == {"a"}
    assert "1 record with no subject" in v.subtitle and "1 record" in v.subtitle


def test_every_record_carries_the_facets_a_person_narrows_by():
    v = view_of_corpus([_rec("a", "BRS.md", REQ, source="collab", state="published", dt="doc-types#minutes"),
                        _rec("b", "screening.json", REQ, source="lab", state="pending")])
    assert v.facet_values("source") == ("collab", "lab")
    assert v.facet_values("state") == ("pending", "published")
    assert v.facet_values("document_type") == ("minutes",)       # short label, not the IRI
    assert v.node("a").facet("source") == "collab"
    assert v.node(REQ).facet("source") == "" and v.node(REQ).facet("state") == ""
    assert [k for k, _ in v.node(REQ).facets] == ["records"]   # a concept has no lifecycle


def test_the_vocabularys_own_edges_are_drawn_so_it_is_meaning_not_co_occurrence():
    """Without this the picture says two records share a tag. With it, it says the vocabulary relates
    the two things they are about — which is the whole claim of owning an ontology."""
    v = view_of_corpus([_rec("a", "BRS.md", GUARD)], schemes=[_Scheme()])
    assert (GUARD, REQ) in [(e.source, e.target) for e in v.edges] or \
           (REQ, GUARD) in [(e.source, e.target) for e in v.edges]
    vocab = [e for e in v.edges if e.status == VOCABULARY]
    assert [e.label for e in vocab] == ["constrains"]
    assert v.node(REQ).kind == CONCEPT                           # brought in by the vocabulary alone


def test_a_concept_is_sized_by_how_much_of_the_corpus_it_holds():
    """`Use case` held half the links on the first run. A hub must LOOK like a hub, so the count rides
    the node rather than being recomputed by whoever draws."""
    v = view_of_corpus([_rec("a", "1", REQ), _rec("b", "2", REQ), _rec("c", "3", UC)])
    assert v.node(REQ).facet("records") == "2" and v.node(UC).facet("records") == "1"
    assert "2 records" in v.node(REQ).note


def test_the_subtitle_states_what_the_picture_is_and_is_not():
    v = view_of_corpus([_rec("a", "1", REQ), _rec("b", "2"), _rec("c", "3", UC)], as_of="2026-10-10")
    assert v.as_of == "2026-10-10"
    for part in ("2 records", "2 concepts", "2 links", "1 record with no subject"):
        assert part in v.subtitle, f"{part!r} missing from {v.subtitle!r}"
