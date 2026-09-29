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
from lab.core.semantic.fabric.vocabulary import build as domain_scheme
from lab.core.semantic.fabric.service import PERSISTED_GRAPHS
from lab.platform import config
from lab.platform.contracts import SemanticTools
from lab.substrate import artifacts
from lab.substrate.mcp.semantic.rung_store import KEY

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))
SERVER = os.path.join(ROOT, "src", "lab", "substrate", "mcp", "semantic", "server.py")

srv = STORE = REDIS = None
def domain():
    """A vocabulary the fabric OWNS (typed relationships, alt labels, curation) beside the reference one it
    merely reads — the ambiguity is deliberate: two concepts a person may call "Agent"."""
    return domain_scheme(name="cafe", title="CAFÉ",
                         concepts=[{"id": "AIAgent", "name": "AI agent", "alt": ["Agent"]},
                                   {"id": "SoftwareAgent", "name": "Agent"},
                                   {"id": "UseCase", "name": "Use case"}],
                         relationships=[{"subject": "AIAgent", "predicate": "realises", "object": "UseCase"}])


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
    # composed from the overridden container: nothing persisted yet, and no curation to replay onto the seed
    assert not any(srv.boot()["curation"].values())
    for sc in (scheme(), domain()):
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
    assert call("semantic_recommend", text="ADR-14 Event bus · decision record") == []      # nothing published yet
    # d references m and m is delivered under the meeting → rule 1 derives d relatedTo that context (rung D)
    derived = call("semantic_derive")
    assert derived["derived"] == 1 and derived["rules"]["references-context"] == 1
    assert ("relatedTo", "D") in {(l["predicate"], l["rung"]) for l in call("semantic_catalog_get", iri=d["iri"])["links"]}
    assert "not computed" in call("semantic_metrics")["note"]
    import json as _json
    from lab.platform import fabric_events as _fe
    REDIS.set(_fe.METRICS_KEY, _json.dumps({"computed_at": "2026-09-13T06:00:00+00:00", "records": {"total": 3}}))
    measured = call("semantic_metrics")
    assert measured["records"]["total"] == 3 and measured["age_seconds"] > 0
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


def test_a_candidate_concept_is_parked_then_ADMITTED_and_findable_from_then_on():
    """The whole point of the gate: a steward's acceptance puts the concept IN the vocabulary, so the next
    document about it is linked instead of proposing the same term again."""
    c = call("semantic_vocab_propose", label="Discharge Summary", actor="classifier-agent",
             definition="Sent at discharge", scheme="cafe")
    assert c["iri"].startswith("urn:fabric:candidate:")
    assert call("semantic_concepts", scheme="cafe", kind="") and not any(
        x["label"] == "Discharge Summary" for x in call("semantic_concepts", scheme="cafe", kind=""))
    acc = call("semantic_promote", subject=c["iri"], actor="steward@x", method="steward-review")
    assert acc["from"] == "candidates" and acc["rung"] == "H" and acc["concept_id"] == "DischargeSummary"
    d = call("semantic_catalog_upsert", pointer={"source": "collab", "handle": "collab://s/d/dis"})
    assert call("semantic_vocab_link", iri=d["iri"], terms=["Discharge Summary"],
                schemes=["cafe"])["linked"][0]["concept"].endswith("#DischargeSummary")
    assert "not a candidate" in call_error("semantic_promote", subject="urn:fabric:artifact:nope", actor="s", method="m")
    # a candidate with no home is refused NAMING the schemes it could join, so the gate can ask for one
    n = call("semantic_vocab_propose", label="Homeless", actor="a")
    assert "names no scheme" in call_error("semantic_promote", subject=n["iri"], actor="s@x", method="m")


def test_a_steward_supersedes_a_concept_and_it_still_resolves():
    call("semantic_vocab_retire", concept_id="UseCase", scheme="cafe", resolves_to="AIAgent",
         actor="steward@x", reason="one meaning, two names")
    live = [x["id"] for x in call("semantic_concepts", scheme="cafe", kind="")]
    assert "UseCase" not in live and "AIAgent" in live          # no longer offered
    assert "actor" in call_error("semantic_vocab_retire", concept_id="AIAgent", scheme="cafe",
                                 resolves_to="UseCase", actor="", reason="x")


def test_a_word_with_two_meanings_waits_for_a_steward_and_is_listed_once():
    assert call("semantic_vocab_conflicts") == []
    d = call("semantic_catalog_upsert", pointer={"source": "collab", "handle": "collab://s/d/amb"})
    r = call("semantic_vocab_link", iri=d["iri"], terms=["Agent"], schemes=["cafe"])
    assert r["linked"] == [] and r["conflicts"][0]["term"] == "Agent"
    open_ = call("semantic_vocab_conflicts")
    assert len(open_) == 1 and open_[0]["concepts"] == ["AIAgent", "SoftwareAgent"]


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
    assert loaded["C"] == before and set(loaded) >= set(refs)


def test_store_page_keeps_a_page_a_page():
    r = call("semantic_store_page", text="# Title\n\nbody", name="notes/adr-14.md")
    assert r["ref"].endswith("/adr-14.md") and r["name"] == "adr-14.md"     # a name, never a path
    assert STORE.get(r["ref"]).decode() == "# Title\n\nbody"                # byte for byte, not wrapped
    assert "content" in call_error("semantic_store_page", text="  ", name="a.md")
    assert "extension" in call_error("semantic_store_page", text="x", name="adr-14")


def test_topology_draws_the_record_from_the_graph_as_it_stands():
    d = call("semantic_catalog_upsert", pointer={"source": "collab", "handle": "collab://s/d/drawn"},
             title="ADR-14 Event bus")
    call("semantic_vocab_link", iri=d["iri"], terms=["Care Delivery"])
    r = call("semantic_topology", iri=d["iri"], proposed=["Widget"])
    assert r["ref"].endswith("/adr-14-event-bus.topology.html") and r["title"] == "ADR-14 Event bus"
    assert (r["suffix"], r["media_type"]) == (".html", "text/html; charset=utf-8")
    assert r["nodes"] >= 3 and r["edges"] >= 2 and "Care Delivery" in r["concepts"] and "Widget" in r["concepts"]
    page = STORE.get(r["ref"]).decode()
    assert page.startswith("<!doctype html>") and "Care Delivery" in page and "<script" not in page.lower()
    assert "focus" in r["statuses"] and call_error("semantic_topology", iri="urn:fabric:artifact:nope")


def test_a_second_renderer_needs_the_adapter_and_the_registry_line_and_nothing_else(monkeypatch):
    """The whole claim of the renderer registry, proved through the real seam: a raster adapter changes the
    file's name and type and NOT one line of the fabric, the tool or the caller."""
    import sys
    import types

    from lab.core.viz import Rendered
    from lab.substrate import container as C

    fake = types.ModuleType("lab.substrate.viz_fake")
    fake.build = lambda **kw: type("Pixels", (), {
        "name": "pixels",
        "render": lambda self, view: Rendered(content=b"\x89PNG-" + view.title.encode(),
                                              media_type="image/png", suffix=".png")})()
    monkeypatch.setitem(sys.modules, "lab.substrate.viz_fake", fake)
    monkeypatch.setitem(C.RENDERER_PROVIDERS, "pixels", "lab.substrate.viz_fake")
    srv.server.container.renderer.override(C.graph_renderer("pixels"))
    try:
        d = call("semantic_catalog_upsert", pointer={"source": "collab", "handle": "collab://s/d/raster"},
                 title="Rastered record")
        r = call("semantic_topology", iri=d["iri"])
        assert (r["suffix"], r["media_type"]) == (".png", "image/png")
        assert r["ref"].endswith("/rastered-record.topology.png")
        assert STORE.get(r["ref"]).startswith(b"\x89PNG-")
    finally:
        srv.server.container.renderer.reset_override()


def test_the_vocabulary_is_staged_as_a_master_an_operator_publishes():
    """The fabric renders what it owns and hands an operator a ref and a command. It cannot publish: the
    signing seed is off every service and the corpus reader holds SELECT only."""
    from lab.core.reference.master import parse

    out = call("semantic_vocab_master", scheme="cafe", owner="ea@doh", version="0.4")
    assert sorted(out) == ["ontology-concepts", "ontology-relationships"]
    made = out["ontology-concepts"]
    assert made["ref"].startswith("art://") and made["ref"].endswith("/ontology-concepts.md")
    assert "--version 0.4" in made["command"] and "--owner ea@doh" in made["command"]
    m = parse(STORE.get(made["ref"]).decode())                     # what the publisher will actually parse
    assert m.meta["Vocabulary"] == "cafe" and {"id", "name"} <= set(m.headers)
    assert {r[0] for r in m.rows} >= {"AIAgent", "UseCase"}
    assert "unknown scheme nope" in call_error("semantic_vocab_master", scheme="nope")   # and names the ones it has


def test_a_concept_a_steward_admitted_is_in_the_master_the_operator_publishes():
    """The loop closed: what a person decided reaches the corpus the other pipelines read, under the ids they
    already join on — so their switch is an artifact id, not code."""
    from lab.core.reference.master import parse

    c = call("semantic_vocab_propose", label="Model card", actor="a", scheme="cafe", definition="what a model is for")
    call("semantic_promote", subject=c["iri"], actor="steward@doh", method="steward-review")
    m = parse(STORE.get(call("semantic_vocab_master", scheme="cafe")["ontology-concepts"]["ref"]).decode())
    row = next(dict(zip(m.headers, r)) for r in m.rows if r[0] == "ModelCard")
    assert row["name"] == "Model card" and row["definition"] == "what a model is for"
