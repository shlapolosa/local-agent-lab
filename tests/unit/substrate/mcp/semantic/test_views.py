"""The CAFÉ views as governed tools: read under a pin, stored by ref, refused without one.

Served from the COMMITTED masters through the in-memory reference library, exactly as decision-mcp's
tests are — the ontology aside, whose tables are private and are built here by hand.
"""
import asyncio

import pytest
from fastmcp import Client

from fixtures.reference import FakeReferenceLibrary, SeededArtifact
from fixtures.usecase_corpus import seeded
from lab.core.reference.model import ArtifactKind
from lab.core.usecase import seed
from lab.core.usecase.views import tables
from lab.platform.contracts import SemanticTools
from lab.substrate import artifacts
from lab.substrate.mcp.semantic import views
from lab.substrate.mcpserver import LabServer

ONTOLOGY = {
    "ontology-concepts": [{"id": "Payer", "name": "Payer", "module": "FIN", "parent": ""},
                          {"id": "Coverage", "name": "Coverage", "module": "FIN", "parent": ""}],
    "ontology-relationships": [{"id": "r1", "subject": "Coverage", "predicate": "issuedBy",
                                "object": "Payer"}],
}


def _private(artifact_id, rows):
    return SeededArtifact(artifact_id, ArtifactKind.RECORD, record_type=tables.RECORD_TYPE[artifact_id],
                          records=[{"record_id": f"rec-{i}", **r} for i, r in enumerate(rows)])


PUBLIC = [t for v in tables.VIEWS if v != "ontology_graph" for t in tables.artifacts_for(v)]


@pytest.fixture
def served(tmp_path):
    library = FakeReferenceLibrary([seeded(a) for a in dict.fromkeys(PUBLIC)]
                                   + [_private(a, rows) for a, rows in ONTOLOGY.items()])
    server = LabServer("semantic-mcp", 9200)
    views.register(server)
    store = artifacts.LocalStore(str(tmp_path / "store"))
    with server.container.reference.override(library), server.container.artifacts.override(store):
        yield server, library, store


def call(server, tool, **args):
    async def go():
        async with Client(server.mcp) as c:
            r = await c.call_tool(tool, args, raise_on_error=False)
            return r
    return asyncio.run(go())


RUN = {"run_id": "wfr-t", "process": "use_case_screening"}


def ok(server, tool, **args):
    r = call(server, tool, **{**RUN, **args})
    assert not r.is_error, r.content[0].text
    return r.data


def pin(library, *ids):
    return library.pin(list(ids)).pin_id


L3 = [r["id"] for r in seed.master_rows("technology_capability_l3")]
COMPONENTS = [r["id"] for r in seed.master_rows("reference_architecture_components")]


def test_the_catalogue_names_exactly_the_tools_this_module_registers(served):
    server, _, _ = served
    tools = asyncio.run(server.mcp.list_tools())
    registered = {t.name for t in (tools.values() if isinstance(tools, dict) else tools)}
    assert registered == set(SemanticTools.VIEWS)


def test_a_view_is_stored_by_ref_and_says_which_versions_it_drew(served):
    server, library, store = served
    out = ok(server, SemanticTools.view_capabilities, pin_id=pin(library),
             capabilities=[{"id": L3[0], "status": "new"}], title="Prior auth")
    assert out["html_ref"].endswith("/capabilities.html")
    page = store.get(out["html_ref"]).decode()
    assert page.startswith("<!doctype html>") and L3[0] in page
    assert out["summary"]["impacted"] == 1
    assert out["rules_source"]["pin_id"] and out["rules_source"]["versions"]


def test_no_pin_no_view(served):
    server, _, _ = served
    r = call(server, SemanticTools.view_capabilities, pin_id="", capabilities=[], **RUN)
    assert r.is_error and "pin" in r.content[0].text


def test_a_pin_missing_a_table_the_view_needs_is_refused_by_name(served):
    server, library, _ = served
    r = call(server, SemanticTools.view_capabilities,
             pin_id=pin(library, "technology-capability-l1", "technology-capability-l2"),
             capabilities=[], **RUN)
    assert r.is_error and "technology-capability-l3" in r.content[0].text


def test_a_pin_missing_only_an_enriching_table_still_draws(served):
    server, library, _ = served
    out = ok(server, SemanticTools.view_capabilities,
             pin_id=pin(library, *tables.required_for("capability_heatmap")),
             capabilities=[{"id": L3[0], "status": "consumed"}])
    assert out["summary"]["impacted"] == 1


def test_the_realisation_view(served):
    server, library, _ = served
    real = seed.master_rows("ai_capability_map")[0]["l3_id"]
    out = ok(server, SemanticTools.view_realisations, pin_id=pin(library),
             realisations=[{"id": real, "route": "microsoft", "status": "new"}])
    assert out["summary"]["by_route"]["microsoft"] == 1


def test_the_architecture_view_stores_both_pages(served):
    server, library, store = served
    out = ok(server, SemanticTools.view_architecture, pin_id=pin(library),
             components=COMPONENTS[:3])
    assert out["logical_ref"].endswith("/architecture.logical.html")
    assert b"<svg" in store.get(out["physical_ref"])
    assert out["summary"]["components_in_scope"] == 3


def test_the_workflow_view_labels_tasks_from_the_pinned_map(served):
    server, library, store = served
    name = seed.master_rows("technology_capability_l3")[0]["name"]
    spec = {"title": "t", "lanes": [{"id": "a", "label": "Reviewer"}],
            "nodes": [{"id": "s", "type": "start", "lane": "a"},
                      {"id": "t1", "type": "task", "lane": "a", "cap": L3[0]},
                      {"id": "e", "type": "end", "lane": "a"}],
            "edges": [{"from": "s", "to": "t1"}, {"from": "t1", "to": "e"}]}
    out = ok(server, SemanticTools.view_workflow, pin_id=pin(library), spec=spec)
    assert out["summary"]["tasks"] == 1
    assert name.split()[0] in store.get(out["html_ref"]).decode()


def test_a_workflow_referring_to_nothing_is_refused(served):
    server, library, _ = served
    spec = {"lanes": [{"id": "a", "label": "x"}], "nodes": [{"id": "s", "type": "start", "lane": "a"}],
            "edges": [{"from": "s", "to": "ghost"}]}
    r = call(server, SemanticTools.view_workflow, pin_id=pin(library), spec=spec, **RUN)
    assert r.is_error and "ghost" in r.content[0].text


def test_the_ontology_view_draws_without_the_optional_modules(served):
    server, library, _ = served
    out = ok(server, SemanticTools.view_ontology, pin_id=pin(library),
             concepts=[{"id": "Payer", "status": "matched"}, {"id": "Coverage", "status": "partial"}])
    assert out["summary"]["counts"]["matched"] == 1 and out["summary"]["edges"] == 1
