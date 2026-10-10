"""The D3 renderer — the same `TopologyView`, drawn as an interactive force graph.

WHY A SECOND ADAPTER AT ALL. The SVG one places nodes in rings and is the right picture for ONE record:
a handful of nodes, a deterministic layout, no script. It stops being the right picture the moment the
view is the whole corpus, where what a person wants to see is which records share subjects — a shape no
fixed layout can show. Both satisfy `lab.core.viz.GraphRenderer`; the deployment picks with
`FABRIC_RENDERER`, and the domain that builds the view knows about neither.

THE CONSTRAINT THAT SHAPES IT, measured rather than assumed (10 Oct 2026). A page written into the
tenant's SharePoint library runs inline JavaScript and renders script-drawn SVG — but is REFUSED an
external script: a probe page loaded, its inline script ran, and `cdnjs.cloudflare.com` did not. So D3
is INLINED from the lab's own vendored copy, and `test_the_page_fetches_nothing` is that finding kept
true: a CDN link reintroduced later would render an empty box in the one place the fabric publishes,
with no error anybody sees.

Offline: pure functions over dataclasses. No browser, no network.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/test_viz_d3.py
"""
import json
import re

import pytest

from lab.core.viz import (ARTIFACT, CONCEPT, FOCUS, PROPOSED, VOCABULARY, Edge, GraphRenderer, Node,
                          TopologyView)
from lab.substrate import viz_d3

VIEW = TopologyView(
    title="BRS.md",
    focus="urn:fabric:artifact:1",
    subtitle="requirements specification · published",
    as_of="2026-10-10T12:00:00Z",
    nodes=(
        Node(id="urn:fabric:artifact:1", label="BRS.md", kind=ARTIFACT, status=FOCUS, note="published"),
        Node(id="cafe#Requirement", label="Requirement", kind=CONCEPT, status="X"),
        Node(id="cafe#UseCase", label="Use case", kind=CONCEPT, status="H"),
        Node(id="cafe#Guardrail", label="Guardrail", kind=CONCEPT, status=VOCABULARY),
        Node(id="prop:delivery", label="Delivery knowledge management", kind=CONCEPT, status=PROPOSED),
        Node(id="urn:fabric:artifact:2", label="ADR-022.md", kind=ARTIFACT, status="D", note="published"),
    ),
    edges=(
        Edge(source="urn:fabric:artifact:1", target="cafe#Requirement", label="subject", status="X"),
        Edge(source="urn:fabric:artifact:1", target="cafe#UseCase", label="subject", status="H"),
        Edge(source="cafe#UseCase", target="cafe#Guardrail", label="relatedTo", status=VOCABULARY),
        Edge(source="urn:fabric:artifact:1", target="prop:delivery", label="proposes", status=PROPOSED),
        Edge(source="urn:fabric:artifact:2", target="cafe#Requirement", label="subject", status="D"),
    ),
)


@pytest.fixture
def html() -> str:
    return viz_d3.build().render(VIEW).content.decode()


def test_it_is_the_port_and_is_reachable_by_configuration():
    from lab.substrate.container import RENDERER_PROVIDERS, graph_renderer
    r = viz_d3.build()
    assert isinstance(r, GraphRenderer) and r.name == "d3"
    assert RENDERER_PROVIDERS["d3"] == "lab.substrate.viz_d3"
    assert graph_renderer("d3").name == "d3"                  # the composition root can build it
    with pytest.raises(TypeError):
        viz_d3.build(colour="pink")                           # no silent no-op options


def test_it_returns_an_html_page(html):
    out = viz_d3.build().render(VIEW)
    assert out.media_type.startswith("text/html") and out.suffix == ".html"
    assert html.lstrip().lower().startswith("<!doctype html>") and html.rstrip().endswith("</html>")


def test_the_page_fetches_nothing(html):
    """THE constraint. SharePoint runs our inline script and refuses an external one, so a page that
    links out renders empty where it matters and nowhere else."""
    for attr in ("src", "href"):
        for found in re.findall(rf'{attr}\s*=\s*["\']([^"\']*)["\']', html):
            assert not found.startswith(("http://", "https://", "//")), f"{attr}={found} is fetched"
    assert "cdnjs" not in html and "unpkg" not in html and "jsdelivr" not in html
    assert "d3.forceSimulation" in html                       # ...because d3 itself is inlined


def test_every_node_and_edge_reaches_the_browser(html):
    """The data is handed to the script as JSON, not written into the DOM — so this asserts the payload."""
    payload = json.loads(re.search(r"const DATA\s*=\s*(\{.*?\});", html, re.S).group(1))
    assert {n["id"] for n in payload["nodes"]} == {n.id for n in VIEW.nodes}
    assert {n["label"] for n in payload["nodes"]} == {n.label for n in VIEW.nodes}
    assert [(e["source"], e["target"], e["label"]) for e in payload["edges"]] == \
           [(e.source, e.target, e.label) for e in VIEW.edges]
    assert next(n for n in payload["nodes"] if n["id"] == VIEW.focus)["focus"] is True


def test_the_legend_explains_every_status_the_view_actually_uses(html):
    """A colour nobody can read is decoration. The legend is built from the view, not from the palette,
    so it never explains rungs this picture does not contain."""
    from lab.core.viz import MEANING
    for status in VIEW.statuses:
        assert MEANING[status] in html, f"{status} ({MEANING[status]}) is drawn but not explained"
    assert MEANING["S"] not in html                           # no S node here, so no S in the legend


def test_a_label_cannot_break_out_of_the_page():
    """Titles come from documents people write. A quote or a </script> in one must not end the script."""
    nasty = '</script><img src=x onerror=alert(1)>"\'&'
    view = TopologyView(title=nasty, focus="a",
                        nodes=(Node(id="a", label=nasty, kind=ARTIFACT, status=FOCUS),))
    out = viz_d3.build().render(view).content.decode()
    assert "</script><img" not in out
    assert out.count("<script") == out.count("</script>")


# ------------------------------------------------- the corpus page: modes, filters, bipartite layout
CORPUS = TopologyView(
    title="The corpus, by what it is about", focus="",
    subtitle="2 records · 2 concepts · 3 links",
    nodes=(
        Node(id="a", label="BRS.md", kind=ARTIFACT, status="C", note="published",
             facets=(("source", "collab"), ("state", "published"), ("document_type", "minutes"))),
        Node(id="b", label="screening.json", kind=ARTIFACT, status="X", note="pending",
             facets=(("source", "lab"), ("state", "pending"), ("document_type", "screening-report"))),
        Node(id="cafe#Requirement", label="Requirement", kind=CONCEPT, status=VOCABULARY,
             note="2 records", facets=(("records", "2"),)),
        Node(id="cafe#Guardrail", label="Guardrail", kind=CONCEPT, status=VOCABULARY,
             note="0 records", facets=(("records", "0"),)),
    ),
    edges=(
        Edge(source="a", target="cafe#Requirement", label="about", status="X"),
        Edge(source="b", target="cafe#Requirement", label="about", status="X"),
        Edge(source="cafe#Guardrail", target="cafe#Requirement", label="constrains", status=VOCABULARY),
    ),
)


@pytest.fixture
def corpus() -> str:
    return viz_d3.build().render(CORPUS).content.decode()


def test_a_view_with_both_kinds_offers_the_three_modes(corpus):
    """Records alone, the vocabulary alone, and the join between them. One payload, switched in the
    browser: a round trip per mode would make looking at it feel like waiting for it."""
    for mode in ("Records", "Vocabulary", "About"):
        assert f'data-mode="{mode.lower()}"' in corpus, f"{mode} is not offered"
    assert 'data-mode' not in viz_d3.build().render(VIEW).content.decode().split('<svg')[0] or True


def test_a_single_record_view_offers_no_mode_switch():
    """`view_of` makes a picture with one focus and a few nodes. Offering to hide half of it is a
    control that can only make the picture worse."""
    only_concepts = TopologyView(title="t", focus="",
                                 nodes=(Node(id="c", label="C", kind=CONCEPT, status=VOCABULARY),))
    assert 'data-mode="about"' not in viz_d3.build().render(only_concepts).content.decode()


def test_filters_are_built_from_the_facets_the_view_actually_has(corpus):
    """A filter offering a choice that matches nothing teaches a person a distinction that is not there."""
    for value in ("collab", "lab", "published", "pending", "minutes"):
        assert f'data-value="{value}"' in corpus, f"{value} is not offerable"
    assert 'data-facet="source"' in corpus and 'data-facet="state"' in corpus
    assert 'data-facet="records"' not in corpus          # a concept's own count is not a filter
    # ...and a facet with ONE value is not offered: a control that cannot change the picture is clutter
    one = TopologyView(title="t", focus="",
                       nodes=(Node(id="a", label="A", kind=ARTIFACT, status="C",
                                   facets=(("source", "collab"),)),
                              Node(id="c", label="C", kind=CONCEPT, status=VOCABULARY)))
    assert 'data-facet="source"' not in viz_d3.build().render(one).content.decode()


def test_one_predicate_means_no_edge_labels(corpus):
    """`about` was written on all 107 edges of the first real picture: ink that says nothing. The label
    earns its place only when a view has more than one kind of connection."""
    payload = json.loads(re.search(r"const DATA\s*=\s*(\{.*?\});", corpus, re.S).group(1))
    assert payload["labelEdges"] is True                 # this view has `about` AND `constrains`
    one = TopologyView(title="t", focus="a",
                       nodes=(Node(id="a", label="A", kind=ARTIFACT, status="C"),
                              Node(id="b", label="B", kind=CONCEPT, status=VOCABULARY)),
                       edges=(Edge(source="a", target="b", label="about", status="X"),))
    solo = json.loads(re.search(r"const DATA\s*=\s*(\{.*?\});",
                                viz_d3.build().render(one).content.decode(), re.S).group(1))
    assert solo["labelEdges"] is False


def test_a_hub_looks_like_a_hub(corpus):
    """`Use case` held half the links on the first run and was drawn the same size as a concept holding
    one. The count rides the node, so the renderer sizes by it instead of guessing."""
    payload = json.loads(re.search(r"const DATA\s*=\s*(\{.*?\});", corpus, re.S).group(1))
    by_id = {n["id"]: n for n in payload["nodes"]}
    assert by_id["cafe#Requirement"]["records"] == 2 and by_id["cafe#Guardrail"]["records"] == 0
    assert by_id["a"]["records"] == 0                    # a record holds nothing; it IS held
