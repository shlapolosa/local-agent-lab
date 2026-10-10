"""The viz PORT — what a picture of the knowledge graph is, stated by the domain.

Pure dataclasses, so these tests pin the invariants an adapter is entitled to rely on: a view cannot
name a node it lacks, a focus must be in the picture, and the facets a renderer builds its filter
controls from are the ones the view actually contains.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/core/test_viz.py
"""
import pytest

from lab.core.viz import (ARTIFACT, CONCEPT, FOCUS, MEANING, PALETTE, PROPOSED, UNKNOWN, VOCABULARY,
                          Edge, Node, TopologyView, colour, meaning)


def _view() -> TopologyView:
    return TopologyView(
        title="corpus", focus="",
        nodes=(Node(id="a", label="BRS.md", kind=ARTIFACT, status="C",
                    facets=(("source", "collab"), ("state", "published"))),
               Node(id="b", label="minutes.json", kind=ARTIFACT, status="X",
                    facets=(("source", "lab"), ("state", "pending"))),
               Node(id="c", label="Requirement", kind=CONCEPT, status=VOCABULARY),
               Node(id="d", label="Nothing recorded", kind=ARTIFACT, status="X",
                    facets=(("source", ""), ("state", "pending")))),
        edges=(Edge(source="a", target="c", label="about", status="X"),))


def test_a_view_refuses_an_edge_or_focus_it_has_no_node_for():
    n = (Node(id="a", label="A", kind=ARTIFACT, status="C"),)
    with pytest.raises(ValueError, match="names a node the view lacks"):
        TopologyView(title="t", focus="a", nodes=n, edges=(Edge(source="a", target="z", label="x", status="C"),))
    with pytest.raises(ValueError, match="focus"):
        TopologyView(title="t", focus="z", nodes=n)
    with pytest.raises(ValueError, match="share an id"):
        TopologyView(title="t", focus="", nodes=n + n)


def test_a_node_needs_an_id_and_a_label_and_well_formed_facets():
    with pytest.raises(ValueError):
        Node(id="", label="A", kind=ARTIFACT, status="C")
    with pytest.raises(ValueError, match="a facet is a"):
        Node(id="a", label="A", kind=ARTIFACT, status="C", facets=(("source",),))      # type: ignore[arg-type]
    with pytest.raises(ValueError, match="says HOW"):
        Edge(source="a", target="b", label="", status="C")


def test_facets_describe_only_what_the_view_contains():
    """A renderer builds its filters from these, so a filter must never offer a choice that matches
    nothing — and an empty value means NOT RECORDED, which is a thing to see, not a thing to pick."""
    v = _view()
    assert v.facet_names == ("source", "state")
    assert v.facet_values("source") == ("collab", "lab")          # the "" of node d is not a choice
    assert v.facet_values("state") == ("pending", "published")
    assert v.facet_values("document_type") == ()                  # nothing carries it: no filter
    assert v.node("a").facet("state") == "published"
    assert v.node("c").facet("state", "n/a") == "n/a"             # a concept has no lifecycle


def test_statuses_are_first_seen_order_so_a_legend_reads_like_the_picture():
    assert _view().statuses == ("C", "X", VOCABULARY)


def test_every_status_has_words_and_an_unmet_one_still_draws():
    assert set(MEANING) == set(PALETTE) and all(MEANING.values())
    assert meaning(FOCUS) == "this record" and meaning(PROPOSED) == "proposed, not admitted"
    assert colour("a rung from the future") == UNKNOWN            # never a KeyError: it must be drawable
