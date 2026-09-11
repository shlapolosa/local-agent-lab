"""The Postgres catalog adapter against a fake connection: the DDL holds no content column (NFR-2 as a
schema fact), the port's calls map to the statements they should, and a driver error has one shape."""
import re

import pytest

from lab.core.semantic.fabric.catalog import Catalog, CatalogEntry
from lab.substrate.mcp.semantic import catalog_pg
from lab.substrate.mcp.semantic.catalog_pg import MIGRATIONS, CatalogUnreachable, PostgresCatalog, migrations

P = {"source": "collab", "handle": "collab://s/d/i1", "version": "2"}
ROW = ("urn:fabric:artifact:A", P, "collab:collab://s/d/i1", "Notes", "", "", "", "pending", "", "", "collab",
       "", False, "2026-09-11T00:00:00+00:00", "2026-09-11T00:00:00+00:00")


class FakeCursor:
    def __init__(self, plan, log):
        self.plan, self.log = plan, log
    def execute(self, sql, params=()):
        self.log.append((" ".join(sql.split()), params)); self._sql = sql
    def fetchall(self):
        for fragment, rows in self.plan.items():
            if fragment in self._sql:
                return rows
        return []
    def __enter__(self): return self
    def __exit__(self, *a): return False


class FakeConn:
    def __init__(self, plan, log):
        self.plan, self.log = plan, log
    def cursor(self): return FakeCursor(self.plan, self.log)
    def commit(self): self.log.append("commit")
    def __enter__(self): return self
    def __exit__(self, *a): return False


def catalog(plan=None, dim=2):
    log: list = []
    c = PostgresCatalog(dsn="postgres://x", connect=lambda dsn: FakeConn(plan or {}, log), dim=dim)
    c.log = log        # type: ignore[attr-defined]
    return c


def test_the_adapter_satisfies_the_port():
    assert isinstance(catalog(), Catalog)


def test_the_ddl_has_no_column_a_body_could_go_in():
    """NFR-2 as a fact of the schema: every column is identity, custody, a facet, lifecycle or a time."""
    columns = set()
    for sql in MIGRATIONS:
        if "CREATE TABLE" in sql:
            body = sql.split("(", 1)[1]
            for line in body.splitlines():
                m = re.match(r"\s*([a-z_]+)\s+(TEXT|JSONB|BOOLEAN|TIMESTAMPTZ|VECTOR)\b", line)
                if m:
                    columns.add(m.group(1))
    assert columns >= {"iri", "pointer", "pointer_key", "title", "document_type", "owner", "state", "embedding"}
    assert not columns & {"body", "content", "text", "summary", "excerpt", "snippet", "html", "markdown"}
    assert any("char_length(title) <= 300" in sql for sql in MIGRATIONS)


def test_the_vector_column_is_dimensioned_and_indexed():
    ddl = migrations(768)
    assert any("VECTOR(768)" in sql for sql in ddl) and any("USING hnsw" in sql for sql in ddl)
    assert not any("%(dim)" in sql for sql in ddl)


def test_ensure_schema_applies_every_migration_and_commits():
    c = catalog(); c.ensure_schema()
    assert [s for s in c.log if s != "commit"].__len__() == len(migrations(2)) and c.log[-1] == "commit"


def test_get_and_by_pointer_map_a_row_to_an_entry():
    c = catalog({"WHERE iri": [ROW], "WHERE pointer_key": [ROW]})
    e = c.get("urn:fabric:artifact:A")
    assert isinstance(e, CatalogEntry) and e.title == "Notes" and e.pointer == P and e.unassociated is False
    assert c.by_pointer("collab:collab://s/d/i1").iri == "urn:fabric:artifact:A"
    assert catalog().get("urn:nope") is None and catalog().by_pointer("x") is None


def test_a_jsonb_pointer_may_arrive_as_text_and_timestamps_as_datetimes():
    from datetime import datetime, timezone
    row = list(ROW); row[1] = '{"source": "lab", "ref": "art://1/x"}'
    row[13] = datetime(2026, 9, 11, tzinfo=timezone.utc); row[14] = row[13]
    e = catalog({"WHERE iri": [tuple(row)]}).get("urn:fabric:artifact:A")
    assert e.pointer == {"source": "lab", "ref": "art://1/x"} and e.created_at == "2026-09-11T00:00:00+00:00"


def test_put_is_one_upsert_keyed_on_the_iri():
    c = catalog()
    e = CatalogEntry("urn:fabric:artifact:A", P, title="Notes", state="published")
    assert c.put(e) is e
    sql, params = c.log[0]
    assert sql.startswith("INSERT INTO fabric_artifact") and "ON CONFLICT (iri) DO UPDATE" in sql
    assert params[0] == e.iri and params[2] == "collab:collab://s/d/i1" and params[7] == "published"
    assert '"handle"' in params[1] and c.log[-1] == "commit"


def test_embeddings_are_pgvector_literals_and_need_a_row():
    # the fake answers by FIRST matching fragment, so the more specific statements come first
    c = catalog({"SELECT embedding": [("[0.5,0.5]", "m")],
                 "1 - (embedding": [("urn:fabric:artifact:B", 0.9), ("urn:fabric:artifact:C", 0.4)],
                 "WHERE iri": [ROW]})
    c.put_embedding("urn:fabric:artifact:A", [0.5, 0.5], "m")
    ins = next(s for s in c.log if isinstance(s, tuple) and "INSERT INTO fabric_embedding" in s[0])
    assert ins[1] == ("urn:fabric:artifact:A", "m", "[0.5,0.5]") and "::vector" in ins[0]
    assert c.embedding("urn:fabric:artifact:A") == ([0.5, 0.5], "m")
    assert c.similar([0.5, 0.5], limit=2, exclude="urn:fabric:artifact:A", model="m") == [
        ("urn:fabric:artifact:B", 0.9), ("urn:fabric:artifact:C", 0.4)]
    sim = next(s for s in c.log if isinstance(s, tuple) and "1 - (embedding" in s[0])
    assert "model = %s" in sim[0] and sim[1][2:4] == ("m", "m")
    assert c.similar([0.5, 0.5], limit=0) == []
    assert catalog().embedding("urn:x") is None
    with pytest.raises(ValueError, match="2-dimensional"):
        catalog().put_embedding("urn:fabric:artifact:A", [1.0], "m")


def test_a_missing_row_surfaces_as_lookup_error_from_the_foreign_key():
    """One statement, not get-then-insert: the FK is the row check, and its violation is the port's answer."""
    class ForeignKeyViolation(Exception):
        pass

    def connect(dsn):
        raise ForeignKeyViolation("fabric_embedding_iri_fkey")
    c = PostgresCatalog(dsn="postgres://x", connect=connect, dim=1)
    with pytest.raises(LookupError):
        c.put_embedding("urn:fabric:artifact:nope", [1.0], "m")


def test_a_driver_error_has_one_shape():
    def boom(dsn):
        raise OSError("connection refused")
    c = PostgresCatalog(dsn="postgres://x", connect=boom)
    with pytest.raises(CatalogUnreachable, match="OSError"):
        c.get("urn:x")
    with pytest.raises(CatalogUnreachable):
        c.put(CatalogEntry("urn:x", P))


def test_build_reads_the_configured_url_and_takes_overrides(monkeypatch):
    monkeypatch.setattr(catalog_pg.config, "FABRIC_DB_URL", "postgres://configured")
    c = catalog_pg.build()
    assert c.dsn == "postgres://configured" and callable(c._connect)
    assert catalog_pg.build(dsn="postgres://other").dsn == "postgres://other"
