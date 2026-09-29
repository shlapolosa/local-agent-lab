"""The CAFÉ views, drawn from the COMMITTED masters — the tables a run pins, not typed copies.

A fixture typed from a renderer's expectations agrees with the renderer by construction; this is
the lesson of the zone codes (29 Sep 2026). So every view here reads the public masters the corpus
publishes. The ontology is the one exception: its tables are private (ADHDS/CRMF-sourced) and never
in git, so its test builds the four tables by hand and says so.
"""
import re

import pytest

from lab.core.usecase import seed
from lab.core.usecase.views import (bpmn, capability_heatmap, ontology_graph, realisation_heatmap,
                                    scoped_architecture, tables)
from lab.core.usecase.views.common import ViewError, script_json


def _published(table):
    try:
        return seed.master_rows(table.replace("-", "_"))
    except (FileNotFoundError, KeyError):
        return None


def data_for(view):
    return tables.assemble(view, _published, lambda _t: "v0.30")


L3 = [r["id"] for r in seed.master_rows("technology_capability_l3")]
REAL = [r["l3_id"] for r in seed.master_rows("ai_capability_map")]
COMPONENTS = seed.master_rows("reference_architecture_components")


# ------------------------------------------------------------------ capability heatmap (step 5)
def test_the_capability_heatmap_fills_what_is_impacted_and_keeps_the_whole_map():
    inp = {"use_case": "UC-1", "title": "Prior-auth review",
           "capabilities": [{"id": L3[0], "status": "new"}, {"id": L3[1], "status": "consumed"},
                            {"id": "ZZZ.99", "status": "missing"}]}
    out = capability_heatmap.render(data_for("capability_heatmap"), inp)
    assert out["summary"]["impacted"] == 2 and out["summary"]["by_status"]["new"] == 1
    assert out["summary"]["unresolved"] == ["ZZZ.99"], "an unknown id is reported, never dropped"
    assert all(i in out["html"] for i in L3), "every L3 stays on the page, faded if not impacted"
    assert "Unresolved IDs" in out["html"]


def test_a_proposed_capability_is_drawn_under_its_parent_as_a_delta():
    l2 = seed.master_rows("technology_capability_l2")[0]["id"]
    inp = {"capabilities": [{"name": "Criteria version watch", "parent_l2": l2, "status": "missing"}]}
    out = capability_heatmap.render(data_for("capability_heatmap"), inp)
    assert out["summary"]["proposed"] == 1 and "Criteria version watch" in out["html"]


def test_an_unknown_status_is_refused():
    with pytest.raises(ViewError):
        capability_heatmap.render(data_for("capability_heatmap"),
                                  {"capabilities": [{"id": L3[0], "status": "probably"}]})


# ------------------------------------------------------------------ realisation heatmap (step 6)
def test_the_realisation_heatmap_marks_the_chosen_route():
    inp = {"realisations": [{"id": REAL[0], "route": "sovereign", "product": "Core42 Compass",
                             "status": "new"}]}
    out = realisation_heatmap.render(data_for("realisation_heatmap"), inp)
    assert out["summary"]["by_route"]["sovereign"] == 1
    assert "Core42 Compass" in out["html"]


# ------------------------------------------------------------------ scoped architecture (step 22)
def test_both_scoped_views_draw_only_the_selected_components():
    picked = [COMPONENTS[0]["id"], COMPONENTS[5]["id"]]
    out = scoped_architecture.render(data_for("scoped_architecture"), {"components": picked})
    assert set(out["pages"]) == {"logical", "physical"}
    assert all("<svg" in p for p in out["pages"].values())
    assert out["summary"]["components_in_scope"] == 2
    assert COMPONENTS[0]["name"] in out["pages"]["physical"]
    missing = next(c for c in COMPONENTS if c["id"] not in picked)["name"]
    assert missing not in out["pages"]["physical"], "out of scope is hidden, not faded"


def test_an_unknown_component_is_reported():
    out = scoped_architecture.render(data_for("scoped_architecture"),
                                     {"components": ["cmp-0000000000"]})
    assert out["summary"]["unresolved"] == ["cmp-0000000000"]


# ------------------------------------------------------------------ BPMN (step 10)
SPEC = {"title": "t", "lanes": [{"id": "a", "label": "Reviewer"}],
        "nodes": [{"id": "s", "type": "start", "lane": "a"},
                  {"id": "t1", "type": "task", "lane": "a", "cap": L3[0]},
                  {"id": "e", "type": "end", "lane": "a"}],
        "edges": [{"from": "s", "to": "t1"}, {"from": "t1", "to": "e"}]}


def test_a_task_naming_only_its_capability_is_labelled_from_the_pinned_map():
    l3 = {r["id"]: r for r in seed.master_rows("technology_capability_l3")}
    out = bpmn.render(SPEC, l3=l3)
    assert out["summary"]["tasks"] == 1 and "<svg" in out["html"]
    assert re.sub(r"&amp;", "&", l3[L3[0]]["name"].split()[0]) in out["html"]
    assert "name" not in SPEC["nodes"][1], "the caller's spec is not annotated"


def test_a_flow_referring_to_nothing_is_refused_by_name():
    bad = dict(SPEC, edges=[{"from": "s", "to": "nowhere"}])
    with pytest.raises(ViewError, match="nowhere"):
        bpmn.render(bad)


# ------------------------------------------------------------------ ontology graph (step 9)
ONTOLOGY = {"ontology": {"version": "v0.5", "tables": {
    "ontology-concepts": [
        {"id": "Payer", "name": "Payer", "module": "FIN", "parent": "", "status": "baseline"},
        {"id": "Coverage", "name": "Coverage", "module": "FIN", "parent": "", "status": "baseline"}],
    "ontology-relationships": [{"subject": "Coverage", "predicate": "issuedBy", "object": "Payer"}],
    "ontology-modules": [{"id": "FIN", "name": "Finance"}],
    "ontology-indicator-links": []}}}


def test_the_ontology_graph_shows_matches_gaps_and_the_existing_relationships_between_them():
    inp = {"concepts": [{"id": "Payer", "status": "matched"}, {"id": "Coverage", "status": "partial"},
                        {"id": "CriteriaVersion", "status": "gap", "name": "Criteria version",
                         "module": "CLN", "definition": "Which criteria text was in force."}]}
    out = ontology_graph.render(ONTOLOGY, inp)
    assert out["summary"]["counts"]["gap"] == 1 and out["summary"]["edges"] == 1
    assert "d3" in out["html"] and "CriteriaVersion" in out["html"]


def test_model_written_text_cannot_end_the_script_element():
    """A note is model output. `</script>` inside the embedded data would close the element and
    run whatever followed it in the reviewer's browser."""
    inp = {"concepts": [{"id": "Payer", "status": "matched", "note": "</script><script>alert(1)"}]}
    page = ontology_graph.render(ONTOLOGY, inp)["html"]
    assert "</script><script>alert(1)" not in page
    assert script_json("</script>") == '"\\u003c/script\\u003e"'


# ------------------------------------------------------------------ which tables
def test_every_view_names_tables_the_corpus_publishes():
    from pathlib import Path
    published = {p.stem.replace("_", "-") for p in Path(seed.MASTERS_DIR).glob("*.md")}
    private = {"ontology-concepts", "ontology-relationships", "ontology-modules",
               "ontology-indicator-links"}                 # published by ref from private masters
    for view in tables.VIEWS:
        for t in tables.artifacts_for(view):
            assert t in published | private, f"{view} reads {t}, which nothing publishes"


def test_a_view_without_a_required_table_refuses_rather_than_drawing_half_a_map():
    with pytest.raises(ViewError, match="technology-capability-l3"):
        tables.assemble("capability_heatmap",
                        lambda t: None if t == "technology-capability-l3" else _published(t))


def test_every_table_is_read_under_the_record_type_the_corpus_publishes_it_as():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[5] / "scripts" / "publish_usecase_corpus.py"
    spec = importlib.util.spec_from_file_location("publish_usecase_corpus", path)
    publish = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publish)
    for table, record_type in tables.RECORD_TYPE.items():
        assert publish.ARTIFACTS[table][0] == record_type, table
    assert set(tables.RECORD_TYPE) == {t for ts in tables.SECTIONS.values() for t in ts}


# ------------------------------------------------------------------ hostile text, every renderer
# Model-written text reaches every page — notes, products, names, labels, titles, definitions — and
# the review app frames these pages. Each field gets a string that would open a script or close an
# attribute; none may survive raw (review, 29 Sep 2026: a BPMN `color` did).
HOSTILE = '"/><script>alert(1)</script><x a="'


def _clean(page):
    assert "<script>alert(1)" not in page and '"/><script' not in page, "hostile text survived raw"


def test_no_renderer_lets_model_written_text_out_of_its_element_or_attribute():
    _clean(capability_heatmap.render(data_for("capability_heatmap"), {
        "title": HOSTILE, "use_case": HOSTILE,
        "capabilities": [{"id": L3[0], "status": "new", "note": HOSTILE}, {"id": HOSTILE, "status": "new"},
                         {"name": HOSTILE, "parent_l2": seed.master_rows("technology_capability_l2")[0]["id"],
                          "status": "missing", "note": HOSTILE}]})["html"])
    _clean(realisation_heatmap.render(data_for("realisation_heatmap"), {
        "title": HOSTILE, "realisations": [{"id": REAL[0], "status": "new", "route": "microsoft",
                                            "product": HOSTILE, "note": HOSTILE}]})["html"])
    for page in scoped_architecture.render(data_for("scoped_architecture"), {
            "title": HOSTILE, "use_case": HOSTILE, "components": [COMPONENTS[0]["id"], HOSTILE]})["pages"].values():
        _clean(page)
    spec = {"title": HOSTILE, "lanes": [{"id": "a", "label": HOSTILE}],
            "nodes": [{"id": "s", "type": "start", "lane": "a"},
                      {"id": "t", "type": "task", "lane": "a", "name": HOSTILE, "note": HOSTILE, "cap": HOSTILE},
                      {"id": "g", "type": "gateway", "kind": "exclusive", "lane": "a", "label": HOSTILE}],
            "edges": [{"from": "s", "to": "t", "label": HOSTILE, "type": "message", "color": HOSTILE},
                      {"from": "t", "to": "g", "label": HOSTILE}]}
    _clean(bpmn.render(spec)["html"])
    _clean(ontology_graph.render(ONTOLOGY, {
        "title": HOSTILE + "__DATA__", "use_case": HOSTILE,
        "concepts": [{"id": "Payer", "status": "matched", "note": HOSTILE},
                     {"id": HOSTILE, "status": "gap", "name": HOSTILE, "definition": HOSTILE}],
        "relationships": [{"subject": HOSTILE, "predicate": HOSTILE, "object": "Payer", "status": "gap"}]})["html"])


def test_a_title_naming_a_placeholder_stays_a_title():
    page = ontology_graph.render(ONTOLOGY, {"title": "__DATA__ and __D3__", "concepts": []})["html"]
    assert "<h1>__DATA__ and __D3__</h1>" in page or "__DATA__ and __D3__" in page.split("<script")[0]
