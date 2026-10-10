"""The SVG adapter: one page a person can open from a download, with no script, no font and no network call."""
import re

import pytest

from lab.core.semantic.fabric.topology import view_of
from lab.core.semantic.fabric.vocabulary import build as vocab
from lab.core.viz import GraphRenderer, Rendered
from lab.core.viz import PALETTE                 # the shared table both renderers read
from lab.substrate.viz_svg import SvgHtmlRenderer

SCHEME = vocab(name="cafe", title="t",
               concepts=[{"id": "AIAgent", "name": "AI agent", "module": "ENG"},
                         {"id": "UseCase", "name": "Use case", "module": "BIZ"}],
               relationships=[{"subject": "AIAgent", "predicate": "realises", "object": "UseCase"}])
RECORD = {"iri": "urn:fabric:artifact:A", "title": "Agent design note", "state": "published",
          "document_type": "urn:fabric:scheme:doc-types#decision-record",
          "links": [{"predicate": "subject", "object": str(SCHEME.uri("AIAgent")), "rung": "X", "label": "AI agent"}]}


def page(**over):
    v = view_of(RECORD, schemes=[SCHEME], as_of="2026-09-29T06:00:00Z", **over)
    out = SvgHtmlRenderer().render(v)
    return out, out.content.decode("utf-8")


def test_it_satisfies_the_port_and_answers_with_what_the_bytes_are():
    r = SvgHtmlRenderer()
    assert isinstance(r, GraphRenderer) and r.name == "svg"
    out, _ = page()
    assert isinstance(out, Rendered) and out.suffix == ".html" and out.media_type.startswith("text/html")


def test_the_page_stands_alone_so_a_download_opens_the_same_as_the_original():
    _, text = page()
    assert "<script" not in text.lower() and "fonts.googleapis" not in text
    for remote in ("http://", "https://"):
        assert remote not in text.replace("http://www.w3.org", "")     # the SVG namespace is not a fetch
    assert text.startswith("<!doctype html>") and "<svg" in text and "</html>" in text


def test_it_draws_the_record_its_subjects_and_what_the_vocabulary_connects_them_to():
    _, text = page()
    for label in ("Agent design note", "AI agent", "Use case", "realises", "about"):
        assert label in text
    assert "decision-record" in text and "2026-09-29T06:00:00Z" in text


def test_colour_says_how_the_fabric_knows_and_the_legend_says_it_in_words():
    _, text = page(proposed=["Widget"],
                   related=[{"iri": "urn:fabric:artifact:B", "title": "Intake", "rung": "D",
                             "predicate": "relatedTo"}])
    assert PALETTE["X"][0] in text and PALETTE["D"][0] in text and PALETTE["proposed"][0] in text
    for words in ("found in the content", "derived by a rule", "proposed, not admitted", "this record"):
        assert words in text
    assert "Widget" in text and "relatedTo" in text


def test_the_layout_is_deterministic_so_two_pictures_can_be_compared():
    assert page()[1] == page()[1]


def test_a_long_label_is_wrapped_and_truncated_rather_than_overflowing():
    long = {**RECORD, "title": "A decision record with a title far too long to sit inside one box on a diagram"}
    text = SvgHtmlRenderer().render(view_of(long, schemes=[SCHEME])).content.decode("utf-8")
    assert "…" in text
    for row in re.findall(r'font-weight="600">([^<]+)</text>', text):
        assert len(row) <= 23


def test_a_caller_supplied_label_cannot_inject_markup():
    nasty = {**RECORD, "title": '<script>alert(1)</script> & "quoted"'}
    text = SvgHtmlRenderer().render(view_of(nasty)).content.decode("utf-8")
    assert "<script>" not in text and "&lt;script&gt;" in text and "&amp;" in text


def test_the_renderer_is_chosen_by_configuration_like_every_other_port():
    from lab.substrate import container as C
    assert isinstance(C.graph_renderer("svg"), GraphRenderer)
    with pytest.raises(ValueError, match="FABRIC_RENDERER"):
        C.graph_renderer("crayon")              # a name no registry entry claims — "d3" is one now
    with pytest.raises(TypeError, match="no options"):
        C.graph_renderer("svg", theme="dark")          # a setting that would never take effect
    c = C.build("semantic-mcp")
    assert c.renderer().name == "svg"


def test_a_double_space_is_not_mistaken_for_words_left_out():
    """The ellipsis says a name was cut. Deciding it by joined length would put one on a label that merely
    had two spaces in it — an ellipsis that lies about the name."""
    spaced = {**RECORD, "title": "Agent  design  note"}
    text = SvgHtmlRenderer().render(view_of(spaced)).content.decode("utf-8")
    assert "…" not in text
