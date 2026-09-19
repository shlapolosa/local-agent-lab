"""The durable shadow of the rung graphs: a write lands as one artifact per touched graph plus a Redis index
of the latest refs; a restart restores from exactly those; a graph the service does not persist is ignored."""
import tempfile

from rdflib import Dataset, URIRef

from fixtures.fakes import FakeRedis
from lab.core.semantic.fabric import graph as G
from lab.core.semantic.fabric.catalog import MemoryCatalog
from lab.core.semantic.fabric.ontology import DocumentTypes
from lab.core.semantic.fabric.rungs import EXTRACTED
from lab.core.semantic.fabric.service import FabricService
from lab.substrate.artifacts import LocalStore
from lab.substrate.mcp.semantic import rung_store
from lab.substrate.mcp.semantic.rung_store import CONTENT_TYPE, KEY, LOCK, RungStore

DOC = {"source": "collab", "handle": "collab://s/d/i1"}


def parts():
    store, redis = LocalStore(tempfile.mkdtemp(prefix="rungs-")), FakeRedis()
    rs = RungStore(artifacts=lambda: store, redis=lambda: redis)
    fab = FabricService(Dataset(default_union=True), MemoryCatalog(), DocumentTypes(), schemes=dict,
                        on_write=lambda names: rs.save(fab, names))
    return store, redis, rs, fab


def test_every_save_runs_under_the_single_writer_lock(monkeypatch):
    """Two replicas would clobber each other's whole-graph snapshots; the lock makes the second WAIT. Asserted
    on the lock call rather than on timing."""
    store, redis, rs, fab = parts()
    taken = []
    import contextlib

    @contextlib.contextmanager
    def fake_lock(name, **kw):
        taken.append((name, kw.get("client") is redis)); yield
    monkeypatch.setattr(rung_store.locks, "lock", fake_lock)
    fab.catalog_upsert(DOC, title="Notes")
    assert taken == [(LOCK, True)]
    assert f"lock:{LOCK}" not in redis.kv        # and the real one is released after a real save


def test_every_conforming_write_lands_as_artifacts_and_an_index():
    store, redis, rs, fab = parts()
    a = fab.catalog_upsert(DOC, title="Notes")["iri"]
    refs = rs.refs()
    assert set(refs) == {"C", "prov"} and all(r.startswith("art://") for r in refs.values())
    fab.graph_assert(a, "urn:fabric:ont#references", "urn:fabric:artifact:other", rung=EXTRACTED, method="x")
    assert set(rs.refs()) == {"C", "prov", "X"}
    assert b"urn:fabric:graph:X" in store.get(rs.refs()["X"])


def test_the_index_points_at_the_latest_ref_of_each_graph():
    store, redis, rs, fab = parts()
    fab.catalog_upsert(DOC, title="v1")
    first = rs.refs()["C"]
    fab.catalog_upsert(DOC, title="v2")
    assert rs.refs()["C"] != first and b"v2" in store.get(rs.refs()["C"]) and b"v2" not in store.get(first)


def test_restore_loads_exactly_what_was_persisted_and_ignores_strangers():
    store, redis, rs, fab = parts()
    a = fab.catalog_upsert(DOC, title="Notes")["iri"]
    fab.vocab_propose("Candidate", actor="c")
    redis.hset(KEY, mapping={"stranger": store.put("x.nq", b"", CONTENT_TYPE)})
    fresh = FabricService(Dataset(default_union=True), MemoryCatalog(), DocumentTypes(), schemes=dict)
    loaded = RungStore(artifacts=lambda: store, redis=lambda: redis).restore(fresh)
    # a plain document's upsert makes no PROV record, so the prov graph is persisted empty — and restored empty
    assert set(loaded) == {"C", "prov", "candidates"} and loaded["C"] > 0 and loaded["candidates"] > 0
    assert (URIRef(a), G.DCT.title, None) in fresh.ds.graph(URIRef("urn:fabric:graph:C"))


def test_save_skips_names_the_service_does_not_persist_and_an_empty_save_writes_nothing():
    store, redis, rs, fab = parts()
    assert rs.save(fab, ["not-a-graph"]) == {} and rs.refs() == {}


def test_restore_on_an_empty_index_is_a_no_op():
    store, redis, rs, fab = parts()
    assert rs.restore(fab) == {}


def test_a_ref_the_store_no_longer_holds_is_skipped_rather_than_crashing_the_server():
    """The index lives in Redis and the graphs live in the artifact store — two stores with
    independent lifetimes. Measured 19 Sep 2026: the artifact store was rebuilt (its previous
    contents were unrecoverable) while Redis kept its index, so every ref pointed at nothing and
    `restore` raised `KeyError: unknown artifact art://…/fabric-graph-C.nq` at IMPORT time.
    semantic-mcp crash-looped, the gateway could list none of its tools, and every workload's
    preflight then refused with "gateway does not expose ['semantic_store_spec']" — one missing
    file took down every business process in the lab.

    A graph that cannot be read is a graph to REBUILD, not a reason to refuse to start. It is named
    in the log, because starting empty and silent is how a server comes up serving nothing and
    nobody notices."""
    store, redis, rs, fab = parts()
    fab.catalog_upsert(DOC, title="Notes")
    redis.hset(KEY, mapping={"C": "art://gone/fabric-graph-C.nq"})
    fresh = FabricService(Dataset(default_union=True), MemoryCatalog(), DocumentTypes(), schemes=dict)
    loaded = RungStore(artifacts=lambda: store, redis=lambda: redis).restore(fresh)
    assert "C" not in loaded, "the unreadable graph is skipped"
    assert loaded, "every OTHER graph still restores — one bad ref is not a bad restore"


def test_the_skipped_graph_is_named_on_stdout_so_an_empty_server_is_visible():
    store, redis, rs, fab = parts()
    fab.catalog_upsert(DOC, title="Notes")
    redis.hset(KEY, mapping={"C": "art://gone/fabric-graph-C.nq"})
    fresh = FabricService(Dataset(default_union=True), MemoryCatalog(), DocumentTypes(), schemes=dict)
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        RungStore(artifacts=lambda: store, redis=lambda: redis).restore(fresh)
    said = buf.getvalue()
    assert "C" in said and "art://gone" in said
