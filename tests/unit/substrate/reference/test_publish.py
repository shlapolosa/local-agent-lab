"""The publisher — the only path content takes into the corpus.

Two properties carry the weight. The ORDER: a version is draft until its index exists, so a crashed
publish leaves nothing servable. And the DERIVATION: the agent-readable form comes from parsing the
master, so `derived_from = master_sha256` is a fact rather than a claim somebody made about two
files.
"""
import json
from datetime import timedelta

import pytest

from fixtures.embed import HashEmbedder
from lab.core.reference.manifest import generate_key, verify
from lab.core.reference.master import render
from lab.substrate.reference.publish import PublishError, Publisher

PRIVATE, PUBLIC = generate_key()

MASTER = render(title="Risk class mapping",
                headers=["risk_class", "mandatory"],
                rows=[["E2", "G09, G17"], ["E3", "G09, G16"]],
                meta={"Artifact": "guardrail-mapping", "Owner": "Agent Council"})

PROSE = render(title="Tradeoff catalogue", headers=[], rows=[],
               prose="## G23 versus at-least-once\n\nIdempotency plus a compensating action.")


class FakeStore:
    def __init__(self): self.put_calls = []
    def put(self, name, data, content_type="application/octet-stream"):
        self.put_calls.append((name, data, content_type))
        return f"art://fake/{name}"


class FakeCursor:
    def __init__(self, log, plan): self.log, self.plan = log, plan
    def execute(self, sql, params=()): self.log.append((sql, tuple(params))); self._sql = sql
    def executemany(self, sql, seq):
        self.batches.append((sql, len(seq)))
        for params in seq:
            self.log.append((sql, tuple(params)))
        self._sql = sql
    batches: list = []
    def fetchall(self):
        for fragment, rows in self.plan.items():
            if fragment in self._sql:
                return rows
        return []
    def __enter__(self): return self
    def __exit__(self, *a): return False


class FakeConn:
    def __init__(self, log, plan): self.log, self.plan = log, plan
    def cursor(self): return FakeCursor(self.log, self.plan)
    def commit(self): self.log.append(("COMMIT", ()))
    def __enter__(self): return self
    def __exit__(self, *a): return False


def publisher(tmp_path, plan=None, **kw):
    log: list = []
    p = Publisher(dsn="postgres://x", connect=lambda dsn: FakeConn(log, plan or {}),
                  signing_key=PRIVATE, key_id="k1", store=kw.pop("store", FakeStore()),
                  embedder=kw.pop("embedder", HashEmbedder(model="test-embed", dim=8)), **kw)
    p.log = log                                              # type: ignore[attr-defined]
    return p


def master_file(tmp_path, body=MASTER, name="guardrail-mapping.md"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def sql_of(pub):
    return [s for s, _ in pub.log]


# ---------------------------------------------------------------- the derivation is real

def test_the_agent_form_is_derived_from_the_parsed_master(tmp_path):
    pub = publisher(tmp_path)
    out = pub.publish("guardrail-mapping", master_path=master_file(tmp_path), version="v1",
                      kind="record", owner="Agent Council", record_type="risk-class",
                      key_fields=["risk_class"])
    assert out["entries"] == 2, "both rows of the master became records"


def test_derived_from_equals_the_master_hash(tmp_path):
    """DR-02. The manifest refuses to be built otherwise, so this asserts the publisher passes the
    master's own hash rather than anything it computed separately."""
    import hashlib
    path = master_file(tmp_path)
    out = publisher(tmp_path).publish("guardrail-mapping", master_path=path, version="v1",
                                      kind="record", owner="x", record_type="risk-class",
                                      key_fields=["risk_class"])
    assert out["manifest"]["derived_from"] == out["manifest"]["master_sha256"]
    assert out["manifest"]["master_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_signature_verifies_against_the_published_manifest(tmp_path):
    from lab.core.reference.manifest import manifest
    out = publisher(tmp_path).publish("guardrail-mapping", master_path=master_file(tmp_path),
                                      version="v1", kind="record", owner="x",
                                      record_type="risk-class", key_fields=["risk_class"])
    body = manifest(artifact_id="guardrail-mapping", version="v1", kind="record", key_id="k1",
                    **out["manifest"])
    assert verify(body, out["signature"], PUBLIC) is True


def test_the_signature_does_not_cover_a_tampered_agent_form(tmp_path):
    """The operational property: a row edited in the database after publication is detectable."""
    from lab.core.reference.manifest import manifest
    out = publisher(tmp_path).publish("guardrail-mapping", master_path=master_file(tmp_path),
                                      version="v1", kind="record", owner="x",
                                      record_type="risk-class", key_fields=["risk_class"])
    tampered = manifest(artifact_id="guardrail-mapping", version="v1", kind="record", key_id="k1",
                        **{**out["manifest"], "content_digest": "f" * 64})
    assert verify(tampered, out["signature"], PUBLIC) is False


def test_both_forms_are_stored_so_a_citation_can_open_the_master(tmp_path):
    store = FakeStore()
    pub = publisher(tmp_path, store=store)
    out = pub.publish("guardrail-mapping", master_path=master_file(tmp_path), version="v1",
                      kind="record", owner="x", record_type="risk-class",
                      key_fields=["risk_class"])
    assert out["master_ref"].endswith(".md") and out["agent_ref"].endswith(".json")
    assert {c[2] for c in store.put_calls} == {"text/markdown", "application/json"}


# ---------------------------------------------------------------- the order is the safety property

def test_a_version_is_draft_until_its_index_exists(tmp_path):
    """A crashed publish must leave nothing servable, so the insert says draft and a LATER
    statement promotes it."""
    pub = publisher(tmp_path)
    pub.publish("guardrail-mapping", master_path=master_file(tmp_path), version="v1",
                kind="record", owner="x", record_type="risk-class", key_fields=["risk_class"])
    statements = sql_of(pub)
    insert = next(i for i, s in enumerate(statements) if "INSERT INTO ref_artifact_version" in s)
    index = next(i for i, s in enumerate(statements) if "ref_index_state" in s)
    promote = next(i for i, s in enumerate(statements) if "status = 'published'" in s)
    assert "'draft'" in statements[insert]
    assert insert < index < promote


def test_publishing_never_releases(tmp_path):
    """Publishing is safe; releasing changes what every open run reads. Collapsing them would make
    each publish an immediate production change."""
    pub = publisher(tmp_path)
    pub.publish("guardrail-mapping", master_path=master_file(tmp_path), version="v1",
                kind="record", owner="x", record_type="risk-class", key_fields=["risk_class"])
    assert not any("ref_release" in s for s in sql_of(pub))


def test_the_whole_publish_is_one_transaction(tmp_path):
    pub = publisher(tmp_path)
    pub.publish("guardrail-mapping", master_path=master_file(tmp_path), version="v1",
                kind="record", owner="x", record_type="risk-class", key_fields=["risk_class"])
    assert sum(1 for s, _ in pub.log if s == "COMMIT") == 1


# ---------------------------------------------------------------- refusals

def test_a_record_artifact_without_its_natural_key_refuses(tmp_path):
    with pytest.raises(PublishError) as e:
        publisher(tmp_path).publish("m", master_path=master_file(tmp_path), version="v1",
                                    kind="record", owner="x")
    assert "key_fields" in str(e.value)


def test_a_master_that_derives_nothing_refuses(tmp_path):
    empty = master_file(tmp_path, render(title="Empty", headers=["a"], rows=[]), "empty.md")
    with pytest.raises(PublishError) as e:
        publisher(tmp_path).publish("empty", master_path=empty, version="v1", kind="record",
                                    owner="x", record_type="t", key_fields=["a"])
    assert "derived nothing" in str(e.value)


def test_a_prose_artifact_without_an_embedder_refuses_rather_than_indexing_nothing(tmp_path):
    """Publishing it unindexed would create a version reference_search must refuse forever — a
    silent hole in the corpus that looks published."""
    path = master_file(tmp_path, PROSE, "tradeoffs.md")
    with pytest.raises(PublishError) as e:
        publisher(tmp_path, embedder=None).publish("tradeoffs", master_path=path, version="v1",
                                                   kind="prose", owner="x")
    assert "REFERENCE_EMBED_MODEL" in str(e.value)


def test_an_unknown_kind_refuses(tmp_path):
    with pytest.raises(PublishError):
        publisher(tmp_path).publish("m", master_path=master_file(tmp_path), version="v1",
                                    kind="pictures", owner="x")


# ---------------------------------------------------------------- prose

def test_a_prose_artifact_is_chunked_and_embedded_as_documents(tmp_path):
    embedder = HashEmbedder(model="test-embed", dim=8)
    pub = publisher(tmp_path, embedder=embedder)
    out = pub.publish("tradeoffs", master_path=master_file(tmp_path, PROSE, "t.md"),
                      version="v1", kind="prose", owner="x")
    assert out["entries"] >= 1
    assert embedder.calls[-1][1] == "document"
    assert any("ref_passage" in s for s in sql_of(pub))


def test_the_index_state_records_the_model_that_embedded_it(tmp_path):
    pub = publisher(tmp_path, embedder=HashEmbedder(model="test-embed", dim=8))
    pub.publish("tradeoffs", master_path=master_file(tmp_path, PROSE, "t.md"), version="v1",
                kind="prose", owner="x")
    params = [p for s, p in pub.log if "ref_index_state" in s][0]
    assert params[4] == "test-embed" and params[5] == 8


# ---------------------------------------------------------------- release and the soak

def test_the_pilot_ring_accepts_a_release_immediately(tmp_path):
    out = publisher(tmp_path).release("m", "v1", ring=0, actor="ops")
    assert out["ring"] == 0


def test_a_wider_ring_is_refused_before_the_soak(tmp_path):
    from datetime import datetime, timezone
    pub = publisher(tmp_path, plan={"FROM ref_release": [(datetime.now(timezone.utc),)]},
                    soak=timedelta(days=1))
    with pytest.raises(PublishError) as e:
        pub.release("m", "v1", ring=1, actor="ops")
    assert "soak" in str(e.value)


def test_a_roll_back_is_never_rate_limited(tmp_path):
    from datetime import datetime, timezone
    pub = publisher(tmp_path, plan={"FROM ref_release": [(datetime.now(timezone.utc),)]})
    assert pub.release("m", "v1", ring=2, actor="ops", rollback=True)["ring"] == 2


# ---------------------------------------------------------------- inspect

def test_verify_reports_a_version_whose_key_is_not_in_the_trust_store(tmp_path):
    pub = publisher(tmp_path, plan={"FROM ref_artifact_version v": [
        ("m", "v1", "record", "a" * 64, "b" * 64, "a" * 64, "c" * 64, "sig", "k9", "t", None)]})
    out = pub.verify()
    assert out[0]["ok"] is False and "trust store" in out[0]["why"]


def test_list_reports_status_and_the_rings_a_version_reached(tmp_path):
    pub = publisher(tmp_path, plan={"FROM ref_artifact_version v": [
        ("m", "v1", "published", "k1", "0,1")]})
    assert pub.list()[0]["rings"] == [0, 1]


def test_the_trust_record_carries_only_public_material(tmp_path):
    pub = publisher(tmp_path)
    pub.trust(PUBLIC)
    params = [p for s, p in pub.log if "ref_signing_key" in s][0]
    assert PUBLIC in params
    assert PRIVATE not in json.dumps([str(p) for p in params])


# ---------------------------------------------------------------- migrations

def test_the_migrations_are_idempotent_and_create_the_governed_tables():
    from lab.substrate.reference.schema import MIGRATIONS, apply_migrations
    log: list = []
    conn = FakeConn(log, {})
    first = apply_migrations(conn)
    second = apply_migrations(conn)
    assert first == second == len(MIGRATIONS)
    statements = " ".join(s for s, _ in log)
    for table in ("ref_artifact_version", "ref_record", "ref_passage", "ref_consumption",
                  "ref_release", "ref_index_state", "ref_pin_entry", "ref_signing_key"):
        assert table in statements
    assert "IF NOT EXISTS" in statements, "re-running init must not fail on an existing corpus"


def test_the_grants_give_the_reader_no_way_to_write_a_shared_artifact():
    """DR-03 as a GRANT. The reader may record its own pins and consumption — those are its own
    rows — but it can never insert a record, a passage or a release."""
    from lab.substrate.reference.schema import READER_GRANTS
    grants = " ".join(READER_GRANTS)
    for shared in ("ref_record", "ref_passage", "ref_release", "ref_artifact_version"):
        assert f"GRANT SELECT ON {shared} TO lab_reference_reader" in grants
        assert f"INSERT ON {shared}" not in grants
    for own in ("ref_pin", "ref_consumption"):
        assert f"GRANT SELECT, INSERT ON {own} TO lab_reference_reader" in grants


def test_applying_grants_is_opt_in():
    from lab.substrate.reference.schema import MIGRATIONS, apply_migrations
    log: list = []
    assert apply_migrations(FakeConn(log, {}), grants=True) > len(MIGRATIONS)


# ---------------------------------------------------------------- the CLI shell

def _cli(monkeypatch, publisher_obj):
    from lab.substrate.reference import publish as P
    monkeypatch.setattr(P, "_publisher", lambda *a, **k: publisher_obj)
    return P


def test_the_cli_publishes_from_a_master(tmp_path, monkeypatch, capsys):
    pub = publisher(tmp_path)
    P = _cli(monkeypatch, pub)
    code = P.main(["publish", "guardrail-mapping", "--master", str(master_file(tmp_path)),
                   "--version", "v1", "--kind", "record", "--owner", "Agent Council",
                   "--record-type", "risk-class", "--key-fields", "risk_class"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["entries"] == 2


def test_the_cli_releases_to_a_ring(tmp_path, monkeypatch, capsys):
    P = _cli(monkeypatch, publisher(tmp_path))
    assert P.main(["release", "m", "v1", "--ring", "0", "--actor", "ops"]) == 0
    assert json.loads(capsys.readouterr().out)["ring"] == 0


def test_the_cli_lists_what_is_published(tmp_path, monkeypatch, capsys):
    pub = publisher(tmp_path, plan={"FROM ref_artifact_version v": [
        ("guardrail-mapping", "v1", "published", "k1", "0,1")]})
    P = _cli(monkeypatch, pub)
    assert P.main(["list"]) == 0
    assert "guardrail-mapping" in capsys.readouterr().out


def test_the_cli_runs_init(tmp_path, monkeypatch, capsys):
    P = _cli(monkeypatch, publisher(tmp_path))
    assert P.main(["init"]) == 0
    assert "statements applied" in capsys.readouterr().out


def test_verify_exits_non_zero_when_a_version_cannot_be_verified(tmp_path, monkeypatch, capsys):
    """An operator runs this after a restore. It has to FAIL loudly, or a corrupted corpus looks
    like a healthy one to whoever is checking."""
    pub = publisher(tmp_path, plan={"FROM ref_artifact_version v": [
        ("m", "v1", "record", "a" * 64, "b" * 64, "a" * 64, "c" * 64, "sig", "k9", "t", None)]})
    P = _cli(monkeypatch, pub)
    assert P.main(["verify"]) == 1
    assert "FAIL" in capsys.readouterr().err


def test_verify_exits_zero_on_a_healthy_corpus(tmp_path, monkeypatch, capsys):
    P = _cli(monkeypatch, publisher(tmp_path, plan={"FROM ref_artifact_version v": []}))
    assert P.main(["verify"]) == 0
    assert "ok" in capsys.readouterr().out


def test_init_registers_the_public_half_of_the_key_that_will_sign():
    """Without it the very next command fails on a foreign key nobody would connect to a trust
    store — measured on the live database, on the first real publish. The key is DERIVED from the
    seed rather than read from configuration, so a mismatched pair cannot survive to the point
    where a reader reports a perfectly good artifact as tampered with."""
    from lab.core.reference.manifest import generate_key, public_key_of

    private, public = generate_key()
    log: list = []
    p = Publisher(dsn="postgres://x", connect=lambda dsn: FakeConn(log, {}),
                  signing_key=private, key_id="k7")
    p.init()

    # INSERT, not every statement naming the table — the CREATE TABLE in the migrations mentions
    # it too, and matching that would assert the schema exists rather than the key was recorded.
    written = [(sql, params) for sql, params in log
               if "INSERT INTO ref_signing_key" in sql]
    assert written, "init must seed the trust store"
    assert written[0][1][0] == "k7" and written[0][1][2] == public
    assert public_key_of(private) == public


# ---------------------------------------------------------------- retrieval mode

MAP = render(title="Capability map", headers=["id", "parent", "level", "path", "definition"],
             rows=[["L1", "-", "1", "Care", "Delivering care"],
                   ["L2", "L1", "2", "Care > Triage", "Sorting by urgency"]],
             meta={"Artifact": "capability-map", "Owner": "BA Guild"})


def _publish_map(pub, tmp_path, **kw):
    return pub.publish("capability-map", master_path=master_file(tmp_path, MAP, "map.md"),
                       version="v1", kind="record", owner="x", record_type="capability",
                       key_fields=["id", "parent", "level"], **kw)


def test_an_artifact_that_declares_no_mode_gets_its_kind_s_default(tmp_path):
    pub = publisher(tmp_path)
    pub.publish("guardrail-mapping", master_path=master_file(tmp_path), version="v1",
                kind="record", owner="x", record_type="risk-class", key_fields=["risk_class"])
    assert [p for s, p in pub.log if "INSERT INTO ref_artifact " in s][0][-1] == "key"
    pub = publisher(tmp_path)
    pub.publish("tradeoffs", master_path=master_file(tmp_path, PROSE, "t.md"), version="v1",
                kind="prose", owner="x")
    assert [p for s, p in pub.log if "INSERT INTO ref_artifact " in s][0][-1] == "vector"


def test_a_vector_mode_record_artifact_writes_one_passage_per_record_naming_it(tmp_path):
    """The capability map is exact (children by parent, leaves by level) AND searchable. Both
    forms come from the same derived records, and each passage carries its record's id so a
    relevance hit resolves to the row an exact read would return."""
    pub = publisher(tmp_path)
    out = _publish_map(pub, tmp_path, retrieval="vector", text_fields=["path", "definition"])
    record_ids = [p[2] for s, p in pub.log if "INSERT INTO ref_record" in s]
    passages = [p for s, p in pub.log if "INSERT INTO ref_passage" in s]
    assert len(record_ids) == 2 and len(passages) == 2
    assert [p[-1] for p in passages] == record_ids, "each passage names its record"
    assert passages[0][6] == "Care. Delivering care"
    assert out["retrieval"] == "vector" and out["passages"] == 2
    params = [p for s, p in pub.log if "ref_index_state" in s][0]
    assert params[2] == 2 and params[3] == 2 and params[4] == "test-embed"


def test_records_are_inserted_before_the_passages_that_reference_them(tmp_path):
    pub = publisher(tmp_path)
    _publish_map(pub, tmp_path, retrieval="vector")
    statements = sql_of(pub)
    last_record = max(i for i, s in enumerate(statements) if "INSERT INTO ref_record" in s)
    first_passage = min(i for i, s in enumerate(statements) if "INSERT INTO ref_passage" in s)
    assert last_record < first_passage


def test_a_key_mode_record_artifact_writes_no_passage_and_needs_no_embedder(tmp_path):
    pub = publisher(tmp_path, embedder=None)
    out = _publish_map(pub, tmp_path)
    assert not any("ref_passage" in s for s in sql_of(pub)) and out["passages"] == 0


def test_a_vector_mode_record_artifact_without_an_embedder_refuses(tmp_path):
    with pytest.raises(PublishError) as e:
        _publish_map(publisher(tmp_path, embedder=None), tmp_path, retrieval="vector")
    assert "REFERENCE_EMBED_MODEL" in str(e.value)


def test_prose_declared_as_an_exact_read_refuses(tmp_path):
    with pytest.raises(PublishError) as e:
        publisher(tmp_path).publish("t", master_path=master_file(tmp_path, PROSE, "t.md"),
                                    version="v1", kind="prose", owner="x", retrieval="key")
    assert "prose" in str(e.value)


def test_an_unknown_retrieval_mode_refuses_naming_the_three(tmp_path):
    with pytest.raises(PublishError) as e:
        _publish_map(publisher(tmp_path), tmp_path, retrieval="fuzzy")
    assert "whole" in str(e.value) and "vector" in str(e.value)


def test_a_re_publish_updates_the_artifact_s_declared_mode(tmp_path):
    """The mode is the artifact's CURRENT declaration, not frozen with its first version."""
    pub = publisher(tmp_path)
    _publish_map(pub, tmp_path, retrieval="whole")
    sql = [s for s, _ in pub.log if "INSERT INTO ref_artifact " in s][0]
    assert "retrieval = EXCLUDED.retrieval" in sql


def test_the_version_row_carries_the_mode_it_was_published_with(tmp_path):
    """So a pin freezes the mode with the version, and a later re-publish under another mode
    changes only what the catalogue says the artifact is NOW."""
    pub = publisher(tmp_path)
    _publish_map(pub, tmp_path, retrieval="vector")
    sql, params = [(s, p) for s, p in pub.log if "INSERT INTO ref_artifact_version" in s][0]
    assert "retrieval" in sql and params[-1] == "vector"


# ---------------------------------------------------------------- a workbook master, by reference

def test_a_workbook_in_the_store_publishes_by_ref_and_keeps_that_ref_as_the_master(tmp_path):
    """The licensed workbook lives ONLY in the private store. It is read from there, hashed,
    derived through the semantic layer's parser, and the citation opens the same bytes — the
    publisher stores no second copy of it."""
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "wbfixture", Path(__file__).resolve().parents[2] / "core" / "reference" / "test_workbook.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)

    class RefStore(FakeStore):
        def get(self, ref): return fixture.workbook()

    store = RefStore()
    pub = publisher(tmp_path, store=store)
    out = pub.publish("capability-map-test", master_ref="art://abc/test.xlsx",
                      master_format="workbook", scheme="test-scheme", version="v1",
                      kind="record", owner="BA Guild", record_type="capability",
                      key_fields=["id", "parent", "level"], retrieval="vector",
                      text_fields=["path", "definition"])
    assert out["entries"] == 5 and out["passages"] == 5
    assert out["master_ref"] == "art://abc/test.xlsx"
    assert [c[0] for c in store.put_calls] == ["capability-map-test.json"], "no second workbook"
    keys = [json.loads(p[4]) for s, p in pub.log if "INSERT INTO ref_record" in s]
    assert all(set(k) == {"id", "parent", "level"} for k in keys)
    assert sum(1 for k in keys if k["parent"] == "-") == 2, "two roots"
    passage = [p for s, p in pub.log if "INSERT INTO ref_passage" in s][2]
    assert passage[6] == "Care Delivery > Triage > Urgent triage. The urgent path"


def test_a_workbook_master_needs_its_scheme(tmp_path):
    class RefStore(FakeStore):
        def get(self, ref): return b"not read"
    with pytest.raises(PublishError) as e:
        publisher(tmp_path, store=RefStore()).publish(
            "m", master_ref="art://x/y.xlsx", master_format="workbook", version="v1",
            kind="record", owner="x", record_type="capability", key_fields=["id"])
    assert "--scheme" in str(e.value)


def test_a_master_is_a_path_or_a_ref_exactly_one(tmp_path):
    with pytest.raises(PublishError):
        publisher(tmp_path).publish("m", version="v1", kind="record", owner="x",
                                    record_type="t", key_fields=["a"])
    with pytest.raises(PublishError):
        publisher(tmp_path).publish("m", master_path=master_file(tmp_path),
                                    master_ref="art://x/y", version="v1", kind="record",
                                    owner="x", record_type="t", key_fields=["a"])


def test_an_unknown_master_format_refuses(tmp_path):
    with pytest.raises(PublishError):
        publisher(tmp_path).publish("m", master_path=master_file(tmp_path), master_format="pdf",
                                    version="v1", kind="record", owner="x", record_type="t",
                                    key_fields=["a"])


def test_a_transaction_sends_each_run_of_identical_statements_as_one_batch():
    """A 1,700-passage map took ~25 minutes to write AFTER embedding (10 Sep 2026): one INSERT
    per Neon round trip. Consecutive statements with the same SQL now go as one `executemany`,
    which psycopg pipelines; the transaction boundary and the order are unchanged."""
    log, cur_batches = [], []
    class Cur(FakeCursor):
        batches = cur_batches
    class Conn(FakeConn):
        def cursor(self): return Cur(self.log, self.plan)
    pub = Publisher(dsn="x", connect=lambda dsn: Conn(log, {}), signing_key=PRIVATE, key_id="k",
                    store=FakeStore())
    pub._tx([("INSERT a", (1,)), ("INSERT a", (2,)), ("INSERT a", (3,)), ("UPDATE b", (9,)),
             ("INSERT a", (4,))])
    assert cur_batches == [("INSERT a", 3)], "a run batches; a lone statement is a plain execute"
    assert [p for sql, p in log if sql == "INSERT a"] == [(1,), (2,), (3,), (4,)]
    assert log[-1] == ("COMMIT", ()) and log.index(("UPDATE b", (9,))) < log.index(("INSERT a", (4,)))
