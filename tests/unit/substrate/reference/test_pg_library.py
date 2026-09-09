"""The Postgres reference adapter, against a fake connection.

What is worth testing offline is the FAIL-CLOSED matrix and the mapping — the places where a wrong
answer looks exactly like a right one. Whether Postgres implements `@>` correctly is Postgres's
problem and the integration suite's; whether this module refuses an unindexed version is ours.
"""
import json
from datetime import timedelta

import pytest

from fixtures.embed import HashEmbedder
from lab.core.reference.errors import (
    ArtifactUnverified,
    ReferenceError,
    IndexUnavailable,
    PinExpired,
    ReferenceUnavailable,
    UnknownRecordType,
)
from lab.core.reference.manifest import generate_key, manifest, sign
from lab.core.reference.model import RunRef
from lab.core.reference.port import ReferenceLibrary
from lab.substrate.reference.pg_library import PostgresReferenceLibrary, _trust_keys

RUN = RunRef(run_id="wfr-1", process="use_case_screening", field="criticality_class")
PRIVATE, PUBLIC = generate_key()
DIGEST, PUBLISHED = "a" * 64, "2026-09-08T00:00:00Z"


def signed(artifact_id="guardrail-mapping", version="2026.09.1", kind="record", key_id="k1"):
    body = manifest(artifact_id=artifact_id, version=version, kind=kind, master_sha256=DIGEST,
                    agent_sha256="b" * 64, derived_from=DIGEST, content_digest="c" * 64,
                    published_at=PUBLISHED, key_id=key_id)
    return sign(body, PRIVATE)


def resolve_row(**kw):
    row = dict(artifact_id="guardrail-mapping", version="2026.09.1", kind="record",
               title="Risk mapping", master_ref="art://x/m.md", master_sha256=DIGEST,
               agent_sha256="b" * 64, derived_from=DIGEST, manifest_sha256="c" * 64,
               signature=signed(), key_id="k1", signed_at=PUBLISHED, published_at=PUBLISHED,
               ring=2, status="published")
    row.update(kw)
    return tuple(row.values())


class FakeCursor:
    def __init__(self, plan): self.plan, self.executed = plan, []
    def execute(self, sql, params=()): self.executed.append((sql, params)); self._sql = sql
    def fetchall(self):
        for fragment, rows in self.plan.items():
            if fragment in self._sql:
                return rows
        return []
    def __enter__(self): return self
    def __exit__(self, *a): return False


class FakeConn:
    def __init__(self, plan, log): self.plan, self.log = plan, log
    def cursor(self): return FakeCursor(self.plan)
    def commit(self): self.log.append("commit")
    def __enter__(self): return self
    def __exit__(self, *a): return False


def library(plan=None, **kw):
    log: list = []
    plan = plan or {}
    lib = PostgresReferenceLibrary(
        dsn="postgres://x", connect=lambda dsn: FakeConn(plan, log),
        ring=kw.pop("ring", 2), trust_keys=kw.pop("trust_keys", {"k1": PUBLIC}),
        embedder=kw.pop("embedder", HashEmbedder(model="test-embed", dim=8)), **kw)
    lib._log = log                                             # type: ignore[attr-defined]
    return lib


# ---------------------------------------------------------------- the port

def test_the_adapter_satisfies_the_port():
    assert isinstance(library(), ReferenceLibrary)


def test_trust_keys_parse_from_the_configured_string():
    assert _trust_keys("k1:AAA,k2:BBB") == {"k1": "AAA", "k2": "BBB"}
    assert _trust_keys("") == {}
    assert _trust_keys("nonsense") == {}


# ---------------------------------------------------------------- catalogue

def test_the_catalogue_maps_rows_to_heads():
    lib = library({"FROM ref_artifact a": [
        ("guardrail-mapping", "record", "risk-class", "Risk mapping", "Agent Council", "v1")]})
    heads = lib.catalogue()
    assert heads[0].artifact_id == "guardrail-mapping"
    assert heads[0].record_type == "risk-class"


def test_an_empty_catalogue_refuses_rather_than_answering_nothing():
    with pytest.raises(ReferenceUnavailable):
        library({}).catalogue()


# ---------------------------------------------------------------- pin and verification

def test_a_pin_resolves_verifies_and_records_its_entries():
    lib = library({"FROM ref_release r": [resolve_row()]})
    pin = lib.pin(["guardrail-mapping"])
    assert pin.version_of("guardrail-mapping").version == "2026.09.1"
    assert "commit" in lib._log


def test_an_artifact_with_no_release_for_this_ring_refuses():
    with pytest.raises(ReferenceUnavailable):
        library({"FROM ref_release r": []}).pin(["guardrail-mapping"])


def test_a_signature_that_does_not_verify_refuses_the_whole_pin():
    bad = resolve_row(signature=signed(version="a-different-version"))
    with pytest.raises(ArtifactUnverified) as e:
        library({"FROM ref_release r": [bad]}).pin(["guardrail-mapping"])
    assert "signature" in str(e.value)


def test_a_key_the_trust_store_does_not_hold_refuses():
    with pytest.raises(ArtifactUnverified) as e:
        library({"FROM ref_release r": [resolve_row()]}, trust_keys={}).pin(["guardrail-mapping"])
    assert "trust store" in str(e.value)


def test_a_draft_version_is_never_served_even_if_a_release_row_points_at_it():
    with pytest.raises(ArtifactUnverified) as e:
        library({"FROM ref_release r": [resolve_row(status="draft")]}).pin(["guardrail-mapping"])
    assert "draft" in str(e.value)


def test_verification_runs_on_every_pin_not_once_at_publish():
    """The property that catches a row edited in the database after it was published."""
    lib = library({"FROM ref_release r": [resolve_row()]})
    lib.pin(["guardrail-mapping"])
    lib.trust_keys = {}
    with pytest.raises(ArtifactUnverified):
        lib.pin(["guardrail-mapping"])


# ---------------------------------------------------------------- reads are pinned

def test_an_expired_pin_refuses_every_read():
    lib = library({"FROM ref_release r": [resolve_row()]}, pin_ttl_s=-1)
    pin = lib.pin(["guardrail-mapping"])
    with pytest.raises(PinExpired):
        lib.lookup(pin, record_type="risk-class", key={"risk_class": "E2"}, run=RUN)


def test_every_read_query_joins_the_pin():
    """An unpinned read must not be expressible — so the join is asserted, not assumed."""
    for sql in (PostgresReferenceLibrary._LOOKUP, PostgresReferenceLibrary._SEARCH,
                PostgresReferenceLibrary._RECORD):
        assert "ref_pin_entry" in sql and "pin_id = %s" in sql


# ---------------------------------------------------------------- lookup

def _pinned(lib):
    return lib.pin(["guardrail-mapping"])


def test_an_exact_lookup_maps_rows_and_citations():
    lib = library({
        "FROM ref_release r": [resolve_row()],
        "DISTINCT a.record_type": [("risk-class",)],
        "FROM ref_record r": [("guardrail-mapping", "2026.09.1", "rec-e2", "risk-class",
                               {"risk_class": "E2"}, {"mandatory": "G09"}, "Risk mapping",
                               "art://x/m.md", "k1")]})
    out = lib.lookup(_pinned(lib), record_type="risk-class", key={"risk_class": "E2"}, run=RUN)
    assert out.matched == 1
    assert out.records[0].body["mandatory"] == "G09"
    assert out.citations[0].master_ref == "art://x/m.md"


def test_a_miss_is_an_answer_and_is_still_recorded():
    lib = library({"FROM ref_release r": [resolve_row()],
                   "DISTINCT a.record_type": [("risk-class",)]})
    out = lib.lookup(_pinned(lib), record_type="risk-class", key={"risk_class": "E9"}, run=RUN)
    assert out.matched == 0
    inserted = [s for s, _ in _executed(lib) if "ref_consumption" in s]
    assert inserted


def test_an_unknown_record_type_refuses_and_names_the_known_ones():
    lib = library({"FROM ref_release r": [resolve_row()],
                   "DISTINCT a.record_type": [("risk-class",)]})
    with pytest.raises(UnknownRecordType) as e:
        lib.lookup(_pinned(lib), record_type="nope", key={}, run=RUN)
    assert "risk-class" in str(e.value)


def test_the_lookup_key_is_sent_as_json_for_containment():
    lib = library({"FROM ref_release r": [resolve_row()],
                   "DISTINCT a.record_type": [("risk-class",)]})
    lib.lookup(_pinned(lib), record_type="risk-class", key={"risk_class": "E2"}, run=RUN)
    params = [p for s, p in _executed(lib) if "FROM ref_record r" in s][0]
    assert json.loads(params[4]) == {"risk_class": "E2"}


def test_a_lookup_can_name_the_artifact_it_means():
    """A record type is a CLASSIFICATION, not an identity: two artifacts may publish the same one
    honestly — the family triggers and the component families both publish `family` — and a lookup
    on type alone returns both, interleaved, with different columns. The caller then indexes a
    column the other artifact does not have."""
    lib = library({"FROM ref_release r": [resolve_row()],
                   "DISTINCT a.record_type": [("family",)]})
    lib.lookup(_pinned(lib), record_type="family", key={}, run=RUN,
               artifact_id="family-triggers")
    sql, params = [(s, p) for s, p in _executed(lib) if "FROM ref_record r" in s][0]
    assert "r.artifact_id = %s" in sql
    assert params[2] == params[3] == "family-triggers"


def test_a_lookup_that_names_no_artifact_still_spans_the_type():
    """The old behaviour, kept for a caller that genuinely wants every artifact of a type."""
    lib = library({"FROM ref_release r": [resolve_row()],
                   "DISTINCT a.record_type": [("family",)]})
    lib.lookup(_pinned(lib), record_type="family", key={}, run=RUN)
    params = [p for s, p in _executed(lib) if "FROM ref_record r" in s][0]
    assert params[2] == "" and params[3] == ""


def test_a_truncated_lookup_is_at_least_ORDERED():
    """`LIMIT` with no `ORDER BY` lets Postgres return any N rows — the same "a truncated answer is
    indistinguishable from a thorough one" failure the ANN index was rejected for, on the exact
    side of the corpus."""
    lib = library({"FROM ref_release r": [resolve_row()],
                   "DISTINCT a.record_type": [("family",)]})
    lib.lookup(_pinned(lib), record_type="family", key={}, run=RUN)
    sql = [s for s, _ in _executed(lib) if "FROM ref_record r" in s][0]
    assert "ORDER BY" in sql


# ---------------------------------------------------------------- search fails closed

def test_search_without_an_embedder_refuses():
    lib = library({"FROM ref_release r": [resolve_row()]}, embedder=None)
    with pytest.raises(IndexUnavailable):
        lib.search(_pinned(lib), question="anything", run=RUN)


def test_an_unindexed_version_refuses_rather_than_returning_nothing():
    lib = library({"FROM ref_release r": [resolve_row()],
                   "FROM ref_index_state s": [("guardrail-mapping", "2026.09.1", 0,
                                               "test-embed", 8, None)]})
    with pytest.raises(IndexUnavailable) as e:
        lib.search(_pinned(lib), question="anything", run=RUN)
    assert "completed" in str(e.value)


def test_an_index_built_with_another_model_refuses():
    lib = library({"FROM ref_release r": [resolve_row()],
                   "FROM ref_index_state s": [("guardrail-mapping", "2026.09.1", 12,
                                               "some-other-model", 8, "2026-09-08")]})
    with pytest.raises(IndexUnavailable) as e:
        lib.search(_pinned(lib), question="anything", run=RUN)
    assert "some-other-model" in str(e.value)


def test_an_index_of_another_width_refuses():
    lib = library({"FROM ref_release r": [resolve_row()],
                   "FROM ref_index_state s": [("guardrail-mapping", "2026.09.1", 12,
                                               "test-embed", 1536, "2026-09-08")]})
    with pytest.raises(IndexUnavailable):
        lib.search(_pinned(lib), question="anything", run=RUN)


def test_a_healthy_index_searches_and_cites_its_anchor():
    lib = library({
        "FROM ref_release r": [resolve_row()],
        "FROM ref_index_state s": [("guardrail-mapping", "2026.09.1", 12, "test-embed", 8,
                                    "2026-09-08")],
        "FROM ref_passage g": [("guardrail-mapping", "2026.09.1", "psg-1", "some text",
                                ["Head", "Sub"], "Head > Sub", "Risk mapping", "art://x/m.md",
                                "k1", 0.87)]})
    out = lib.search(_pinned(lib), question="some text", run=RUN)
    assert out.passages[0].score == pytest.approx(0.87)
    assert out.citations[0].anchor == "Head > Sub"


def test_the_query_is_embedded_as_a_query_not_a_document():
    embedder = HashEmbedder(model="test-embed", dim=8)
    lib = library({"FROM ref_release r": [resolve_row()],
                   "FROM ref_index_state s": [("guardrail-mapping", "2026.09.1", 12,
                                               "test-embed", 8, "2026-09-08")]},
                  embedder=embedder)
    lib.search(_pinned(lib), question="anything", run=RUN)
    assert embedder.calls[-1][1] == "query"


# ---------------------------------------------------------------- attribution

def _executed(lib):
    """Every (sql, params) the library ran — the fake cursor records them per connection, so this
    replays through a shared log the fake keeps."""
    return lib._executed_log


@pytest.fixture(autouse=True)
def _capture(monkeypatch):
    """Collect executed statements across the short-lived fake connections."""
    original = PostgresReferenceLibrary._rows
    writes = PostgresReferenceLibrary._write

    def rows(self, sql, params=()):
        self.__dict__.setdefault("_executed_log", []).append((sql, tuple(params)))
        return original(self, sql, params)

    def write(self, statements):
        self.__dict__.setdefault("_executed_log", []).extend(
            (sql, tuple(params)) for sql, params in statements)
        return writes(self, statements)

    monkeypatch.setattr(PostgresReferenceLibrary, "_rows", rows)
    monkeypatch.setattr(PostgresReferenceLibrary, "_write", write)


def test_a_consumption_row_names_the_derived_field():
    lib = library({"FROM ref_release r": [resolve_row()],
                   "DISTINCT a.record_type": [("risk-class",)]})
    lib.lookup(_pinned(lib), record_type="risk-class", key={"risk_class": "E2"}, run=RUN)
    row = [p for s, p in _executed(lib) if "ref_consumption" in s][0]
    assert "criticality_class" in row


def test_consumers_maps_the_reverse_index():
    lib = library({"FROM ref_consumption": [
        ("wfr-1", "use_case_screening", "criticality_class", "guardrail-mapping", "2026.09.1",
         "lookup", "2026-09-08", "E2", True)]})
    out = lib.consumers(artifact_id="guardrail-mapping", version="2026.09.1")
    assert out[0].field == "criticality_class" and out[0].hit is True


# ---------------------------------------------------------------- the store itself being absent

def _broken(exc):
    def connect(dsn):
        raise exc
    return PostgresReferenceLibrary(dsn="postgres://x", connect=connect, ring=2,
                                    trust_keys={"k1": PUBLIC})


def test_a_corpus_whose_tables_do_not_exist_refuses_as_a_sentence():
    """Found LIVE, not by a test: the fake connection can never raise a driver error, so a psycopg
    `UndefinedTable` escaped the typed refusals and reached a caller as
    `relation "ref_artifact" does not exist`. Everything in this layer exists to give a caller a
    sentence it can act on, and that was not one."""
    from lab.core.reference.errors import CorpusUnreachable
    with pytest.raises(CorpusUnreachable) as e:
        _broken(RuntimeError('relation "ref_artifact" does not exist')).catalogue()
    assert "publish init" in str(e.value)
    assert "ref_artifact" in str(e.value), "the driver's own words survive — an operator needs them"


def test_an_unreachable_corpus_is_distinct_from_an_unpublished_one():
    """`ReferenceUnavailable` means nobody published it to your ring — a publisher's job.
    `CorpusUnreachable` means the store is not there — an operator's. Telling a caller to publish
    when the schema does not exist sends them to the wrong person."""
    from lab.core.reference.errors import CorpusUnreachable, ReferenceUnavailable
    assert not issubclass(CorpusUnreachable, ReferenceUnavailable)
    assert issubclass(CorpusUnreachable, ReferenceError)


def test_a_typed_refusal_is_never_re_wrapped_as_a_store_failure():
    """A signature that does not verify is not a database problem, and must not be reported as one."""
    lib = library({"FROM ref_release r": [resolve_row()]}, trust_keys={})
    with pytest.raises(ArtifactUnverified):
        lib.pin(["guardrail-mapping"])


def test_a_write_that_cannot_reach_the_store_refuses_the_same_way():
    from lab.core.reference.errors import CorpusUnreachable
    with pytest.raises(CorpusUnreachable):
        _broken(OSError("connection refused"))._write([("INSERT INTO ref_pin VALUES (1)", ())])
