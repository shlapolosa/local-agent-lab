"""The Documentation Fabric's tools on semantic-mcp, through an in-memory fastmcp Client, OFFLINE: temp
artifact store, FakeRedis, the hash embedder, the in-process catalog, a synthetic SKOS scheme. One artifact's
life: identified → classified at a rung → linked → impact answered → indexed → promoted → published; every
write shadowed to the artifact store and restorable by `boot()`."""
import asyncio
import importlib.util
import os
import sys
import tempfile

import pytest
from fastmcp import Client
from rdflib import URIRef

from fixtures.embed import HashEmbedder
from fixtures.fakes import FakeRedis
from fixtures.skos import scheme
from lab.core.semantic.fabric.rungs import graph_iri
from lab.core.semantic.fabric.service import PERSISTED_GRAPHS
from lab.platform import config
from lab.platform.contracts import SemanticTools
from lab.substrate import artifacts
from lab.substrate.mcp.semantic.rung_store import KEY

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))
SERVER = os.path.join(ROOT, "src", "lab", "substrate", "mcp", "semantic", "server.py")

srv = STORE = REDIS = None
LAB = {"source": "lab", "ref": "art://run1/minutes.json"}
DOC = {"source": "collab", "handle": "collab://site/drive/doc7", "version": "2"}


@pytest.fixture(scope="module", autouse=True)
def _server():
    global srv, STORE, REDIS
    mp = pytest.MonkeyPatch()
    tmp = tempfile.mkdtemp(prefix="semantic-fabric-test-")
    ref_dir = os.path.join(tmp, "no-ref-models"); os.makedirs(ref_dir)
    mp.setenv("REFERENCE_MODELS_DIR", ref_dir); mp.setenv("MCP_SHARED_SECRET", "shh")
    for k in ("OTEL_EXPORTER_OTLP_ENDPOINT", "UPLOADS_URL", "DATABASE_URL", "FABRIC_DB_URL"):
        mp.delenv(k, raising=False)
    mp.setattr(config, "REFERENCE_MODELS_DIR", ref_dir)
    mp.setattr(config, "FABRIC_DB_URL", "")
    spec = importlib.util.spec_from_file_location("semantic_fabric_server", SERVER)
    srv = importlib.util.module_from_spec(spec); sys.modules["semantic_fabric_server"] = srv
    spec.loader.exec_module(srv)
    STORE, REDIS = artifacts.LocalStore(os.path.join(tmp, "store")), FakeRedis()
    srv.server.container.artifacts.override(STORE)
    srv.server.container.redis.override(REDIS)
    srv.server.container.embedder.override(HashEmbedder(dim=8))
    assert srv.boot() == {}                        # composed from the overridden container; nothing persisted yet
    sc = scheme()
    srv.S.registry.add(sc); srv.S.schemes_[sc.name] = sc
    g = srv.S.store.ds.graph(URIRef(f"urn:lab:semantic:vocab:{sc.name}"))
    for t in sc.graph():
        g.add(t)
    yield
    sys.modules.pop("semantic_fabric_server", None)
    mp.undo()
    srv = STORE = REDIS = None


def call(_tool, **args):
    async def go():
        async with Client(srv.server.mcp) as c:
            return (await c.call_tool(_tool, args)).data
    return asyncio.run(go())


def call_error(_tool, **args) -> str:
    async def go():
        async with Client(srv.server.mcp) as c:
            r = await c.call_tool(_tool, args, raise_on_error=False)
            assert r.is_error, f"{_tool} should have failed"
            return r.content[0].text
    return asyncio.run(go())


def test_every_fabric_tool_in_the_contract_is_served():
    async def go():
        async with Client(srv.server.mcp) as c:
            return {t.name for t in await c.list_tools()}
    assert SemanticTools.names() <= asyncio.run(go())


def test_an_artifacts_life_through_the_tools():
    # identify: a lab process's output — type is a fact, delivery edge from the run's context
    m = call("semantic_catalog_upsert", pointer=LAB, title="Minutes 2026-09-01", produced_by="transcript_to_minutes",
             context="meeting:AAMk1")
    assert m["iri"].startswith("urn:fabric:artifact:") and m["document_type"].endswith("#minutes")
    assert call("semantic_catalog_upsert", pointer=LAB, title="Minutes 2026-09-01")["iri"] == m["iri"]   # idempotent
    # a human-authored document: classified by a model at S, owner constructed at C
    d = call("semantic_catalog_upsert", pointer=DOC, title="ADR-14 Event bus")
    r = call("semantic_catalog_assert", iri=d["iri"], field="document_type",
             value="urn:fabric:scheme:doc-types#decision-record", rung="S", method="classifier-agent", confidence=0.83)
    assert r["rung"] == "S" and r["assertion"].startswith("urn:fabric:assertion:")
    call("semantic_catalog_assert", iri=d["iri"], field="owner", value="urn:fabric:person:oid-1", rung="C", method="owner-map")
    assert "NFR-3" in call_error("semantic_catalog_assert", iri=d["iri"], field="sensitivity_label", value="Secret",
                                 rung="S", method="guess", confidence=0.4)
    got = call("semantic_catalog_get", iri=d["iri"])
    assert got["owner"] == "urn:fabric:person:oid-1" and {(l["predicate"], l["rung"]) for l in got["links"]} == {
        ("documentType", "S"), ("ownedBy", "C")}
    # structure and subjects
    call("semantic_edge_assert", subject=d["iri"], predicate="urn:fabric:ont#references", object=m["iri"],
         rung="X", method="link-extraction")
    link = call("semantic_vocab_link", iri=d["iri"], terms=["Care Delivery", "Unknown Term"])
    assert [l["label"] for l in link["linked"]] == ["Care Delivery"] and link["missed"] == ["Unknown Term"]
    # impact: the ADR reaches the minutes over X; a suggested edge would not count
    call("semantic_edge_assert", subject="urn:fabric:artifact:S", predicate="urn:fabric:ont#references",
         object=m["iri"], rung="S", method="nn", confidence=0.5)
    hit = call("semantic_impact", iri=m["iri"])
    assert [(h["iri"], h["rung"], h["title"]) for h in hit] == [(d["iri"], "X", "ADR-14 Event bus")]
    trav = call("semantic_trace", start="urn:fabric:context:meeting:AAMk1",
                predicates=["urn:fabric:ont#deliveredUnder"], rungs=["C"])
    assert [t["iri"] for t in trav] == [m["iri"]]
    # the index proposes
    assert call("semantic_embed", iri=m["iri"], text="Minutes 2026-09-01 · minutes")["dim"] == 8
    call("semantic_embed", iri=d["iri"], text="ADR-14 Event bus · decision record")
    near = call("semantic_similar", iri=m["iri"])
    assert [n["iri"] for n in near] == [d["iri"]] and "score" in near[0]
    assert call("semantic_search", text="ADR-14 Event bus · decision record", document_type="")[0]["iri"] == d["iri"]
    assert call("semantic_search", text="x", state="published") == []
    # a switched embedder is one governed call away from a readable index again
    srv.F.catalog.put_embedding(d["iri"], srv.F.catalog.embedding(d["iri"])[0], "retired-model")
    assert call("semantic_reindex") == {"model": "test-embed", "indexed": 1, "skipped": 0}
    assert srv.F.catalog.embedding(d["iri"])[1] == "test-embed"
    # a person confirms the classification and publishes
    p = call("semantic_promote", subject=d["iri"], predicate="urn:fabric:ont#documentType",
             object="urn:fabric:scheme:doc-types#decision-record", actor="reviewer@x", method="draft-review")
    assert (p["from"], p["rung"]) == ("S", "H")
    assert "actor" in call_error("semantic_promote", subject=d["iri"], predicate="urn:fabric:ont#documentType",
                                 object="urn:fabric:scheme:doc-types#decision-record", actor="", method="x")
    pub = call("semantic_catalog_state", iri=d["iri"], state="published", baseline_version="1.0")
    assert (pub["state"], pub["baseline_version"]) == ("published", "1.0")
    assert call("semantic_edge_retract", subject="urn:fabric:artifact:S", predicate="urn:fabric:ont#references",
                object=m["iri"], actor="rule:stale", reason="never confirmed") == {"retracted": True}
    assert call("semantic_validate_shapes") == {"conforms": True, "messages": []}


def test_a_candidate_concept_is_parked_then_accepted():
    c = call("semantic_vocab_propose", label="Discharge Summary", actor="classifier-agent", definition="Sent at discharge")
    assert c["iri"].startswith("urn:fabric:candidate:")
    acc = call("semantic_promote", subject=c["iri"], actor="steward@x", method="steward-review")
    assert acc["from"] == "candidates" and acc["rung"] == "H"
    assert "not a candidate" in call_error("semantic_promote", subject="urn:fabric:artifact:nope", actor="s", method="m")


def test_a_content_property_is_refused_by_the_shapes():
    d = call("semantic_catalog_upsert", pointer={"source": "collab", "handle": "collab://s/d/body"})
    err = call_error("semantic_edge_assert", subject=d["iri"], predicate="urn:fabric:ont#body",
                     object="the whole text", rung="C", method="x")
    assert "refused by the fabric's shapes" in err
    assert call("semantic_validate_shapes")["conforms"] is True


def test_every_write_is_shadowed_and_boot_restores_it():
    refs = {k: v for k, v in REDIS.hgetall(KEY).items()}
    assert {"C", "prov", "X", "S", "H", "candidates"} <= set(refs) and all(v.startswith("art://") for v in refs.values())
    assert b"urn:fabric:graph:C" in STORE.get(refs["C"])
    # wipe the working copy and boot: the persisted graphs come back
    ds = srv.S.store.ds
    before = len(ds.graph(graph_iri("C")))
    for iri in PERSISTED_GRAPHS.values():
        ds.graph(iri).remove((None, None, None))
    assert len(ds.graph(graph_iri("C"))) == 0
    loaded = srv.boot()
    assert loaded["C"] == before and set(loaded) == set(refs)
