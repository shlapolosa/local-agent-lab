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
