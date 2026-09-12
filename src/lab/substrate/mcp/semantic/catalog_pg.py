"""The Catalog port over Postgres — two tables in the database semantic-mcp already reaches (`FABRIC_DB_URL`,
falling back to `DATABASE_URL` like the reference layer). Metadata only, BY DDL: there is no column a body
could go in, and `tests/unit/substrate/mcp/semantic/test_catalog_pg.py` reads the DDL to say so.

Same shape as `lab.substrate.reference.pg_library`: a `connect` seam so the adapter is tested against a
fake connection, one `_rows` / `_write` pair so every driver error has one shape, and a `build()` the
composition root calls with settings from `lab.platform.config`."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any, Callable, Sequence

from lab.core.semantic.fabric.catalog import CatalogEntry, pointer_key
from lab.platform import config

__all__ = ["PostgresCatalog", "MIGRATIONS", "migrations", "CatalogUnreachable", "build"]


INDEX = "fabric_embedding_hnsw_halfvec"
LEGACY_INDEX = "fabric_embedding_hnsw"          # over `vector` — cannot serve the halfvec expression; retired once


def _ranked_by(dim: int) -> str:
    """The ONE expression the index is built on and `similar` orders by — they must be byte-identical or
    the planner ignores the index and nothing fails."""
    return f"embedding::halfvec({int(dim)})"


def _index(dim: int) -> str:
    """hnsw over `halfvec`: pgvector indexes at most 2000 dims of `vector` but 4000 of `halfvec` (pgvector ≥ 0.7,
    the floor `ALTER EXTENSION vector UPDATE` applies), and a vendor model is 3072 wide — ONE statement for
    every width. Half precision costs nothing a facet-text index can measure. The name carries the
    definition, because `IF NOT EXISTS` matches by name and would keep a stale definition forever."""
    return f"CREATE INDEX IF NOT EXISTS {INDEX} ON fabric_embedding USING hnsw (({_ranked_by(dim)}) halfvec_cosine_ops)"


def migrations(dim: int) -> tuple[str, ...]:
    """The tables, with the embedding column DIMENSIONED so pgvector can index it (an undimensioned
    `VECTOR` is a sequential scan forever) — the dimension is the embedder's (`REFERENCE_EMBED_DIM`)."""
    return MIGRATIONS[:-1] + (MIGRATIONS[-1] % {"dim": int(dim)}, f"DROP INDEX IF EXISTS {LEGACY_INDEX}", _index(dim))


MIGRATIONS: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    "ALTER EXTENSION vector UPDATE",              # `halfvec` needs 0.7+; CREATE never upgrades an installed one
    """CREATE TABLE IF NOT EXISTS fabric_artifact (
         iri TEXT PRIMARY KEY,
         pointer JSONB NOT NULL,
         pointer_key TEXT NOT NULL,
         title TEXT NOT NULL DEFAULT '' CHECK (char_length(title) <= 300),
         document_type TEXT NOT NULL DEFAULT '',
         owner TEXT NOT NULL DEFAULT '',
         sensitivity_label TEXT NOT NULL DEFAULT '',
         state TEXT NOT NULL CHECK (state IN ('pending','in-review','published','withdrawn')),
         produced_by TEXT NOT NULL DEFAULT '',
         context TEXT NOT NULL DEFAULT '',
         source_kind TEXT NOT NULL DEFAULT '',
         baseline_version TEXT NOT NULL DEFAULT '',
         unassociated BOOLEAN NOT NULL DEFAULT FALSE,
         created_at TIMESTAMPTZ NOT NULL,
         updated_at TIMESTAMPTZ NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS fabric_artifact_pointer ON fabric_artifact (pointer_key)",
    """CREATE TABLE IF NOT EXISTS fabric_embedding (
         iri TEXT PRIMARY KEY REFERENCES fabric_artifact ON DELETE CASCADE,
         model TEXT NOT NULL,
         embedding VECTOR(%(dim)d) NOT NULL,
         updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
)

_COLUMNS = ("iri", "pointer", "pointer_key", "title", "document_type", "owner", "sensitivity_label", "state",
            "produced_by", "context", "source_kind", "baseline_version", "unassociated", "created_at", "updated_at")
_SELECT = "SELECT " + ", ".join(_COLUMNS) + " FROM fabric_artifact"


class CatalogUnreachable(RuntimeError):
    """The database did not answer — never confused with an empty answer."""


def _iso(v: Any) -> str:
    return v.isoformat(timespec="seconds") if isinstance(v, datetime) else str(v or "")


def _entry(row: Sequence[Any]) -> CatalogEntry:
    r = dict(zip(_COLUMNS, row))
    pointer = r["pointer"] if isinstance(r["pointer"], dict) else json.loads(r["pointer"])
    return CatalogEntry(iri=r["iri"], pointer=pointer, title=r["title"], document_type=r["document_type"],
                        owner=r["owner"], sensitivity_label=r["sensitivity_label"], state=r["state"],
                        produced_by=r["produced_by"], context=r["context"], source_kind=r["source_kind"],
                        baseline_version=r["baseline_version"], unassociated=bool(r["unassociated"]),
                        created_at=_iso(r["created_at"]), updated_at=_iso(r["updated_at"]))


def _literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(str(float(v)) for v in vector) + "]"


class PostgresCatalog:
    """`connect(dsn)` is the seam: `psycopg.connect`, a pool's `connection`, or a fake. It is called per
    statement, so a pooled factory is what a hot path runs against a remote database."""

    def __init__(self, *, dsn: str, connect: Callable[..., Any], dim: int = 768) -> None:
        self.dsn = dsn
        self._connect = connect
        self.dim = int(dim)

    # ---------------------------------------------------------------- plumbing

    def _rows(self, sql: str, params: Sequence[Any] = ()) -> list[tuple]:
        try:
            with self._connect(self.dsn) as conn, conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                return list(cur.fetchall())
        except Exception as exc:                      # noqa: BLE001 — every driver error, one shape
            raise CatalogUnreachable(f"{type(exc).__name__}: {exc}") from exc

    def _write(self, statements: Sequence[tuple[str, Sequence[Any]]]) -> None:
        try:
            with self._connect(self.dsn) as conn, conn.cursor() as cur:
                for sql, params in statements:
                    cur.execute(sql, tuple(params))
                conn.commit()
        except Exception as exc:                      # noqa: BLE001
            raise CatalogUnreachable(f"{type(exc).__name__}: {exc}") from exc

    def ensure_schema(self) -> None:
        self._write([(sql, ()) for sql in migrations(self.dim)])
        self._migrate_width()

    def _migrate_width(self) -> None:
        """The embedder was switched (12 Sep 2026: 768 → 3072 under a live index) and `CREATE TABLE IF NOT
        EXISTS` cannot notice. Vectors are compared within ONE model's space, so the old rows answer nothing
        and cannot be widened; they are derived from the catalog, so they are dropped and the index rebuilt —
        LOUDLY, naming the one call that fills it again. Never a silent empty answer.
        Deliberately unlike the reference layer (undimensioned column, per-row model, no ANN index): the fabric
        wants the index, so a switch is a blackout the size of one `semantic_reindex`. Check-then-act across two
        connections — one replica today; a second one would need `pg_advisory_lock` around this."""
        rows = self._rows("SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                          "WHERE attrelid = 'fabric_embedding'::regclass AND attname = 'embedding'")
        declared = str(rows[0][0]) if rows else ""
        if not declared or declared == f"vector({self.dim})":
            return
        held = self._rows("SELECT COUNT(*) FROM fabric_embedding")
        self._write([("DELETE FROM fabric_embedding", ()),
                     (f"DROP INDEX IF EXISTS {INDEX}", ()),
                     (f"ALTER TABLE fabric_embedding ALTER COLUMN embedding TYPE VECTOR({self.dim})", ()),
                     (_index(self.dim), ())])
        print(f"fabric catalog: the index was {declared} and the embedder is {self.dim} wide — dropped "
              f"{held[0][0] if held else '?'} vector(s) of the old space; call semantic_reindex to fill it",
              file=sys.stderr, flush=True)

    # -------------------------------------------------------------------- port

    def get(self, iri: str) -> CatalogEntry | None:
        rows = self._rows(_SELECT + " WHERE iri = %s", (iri,))
        return _entry(rows[0]) if rows else None

    def by_pointer(self, key: str) -> CatalogEntry | None:
        rows = self._rows(_SELECT + " WHERE pointer_key = %s ORDER BY created_at LIMIT 1", (key,))
        return _entry(rows[0]) if rows else None

    _UPSERT = """
        INSERT INTO fabric_artifact (""" + ", ".join(_COLUMNS) + """)
        VALUES (""" + ", ".join(["%s"] * len(_COLUMNS)) + """)
        ON CONFLICT (iri) DO UPDATE SET
          pointer = EXCLUDED.pointer, pointer_key = EXCLUDED.pointer_key, title = EXCLUDED.title,
          document_type = EXCLUDED.document_type, owner = EXCLUDED.owner,
          sensitivity_label = EXCLUDED.sensitivity_label, state = EXCLUDED.state,
          produced_by = EXCLUDED.produced_by, context = EXCLUDED.context, source_kind = EXCLUDED.source_kind,
          baseline_version = EXCLUDED.baseline_version, unassociated = EXCLUDED.unassociated,
          updated_at = EXCLUDED.updated_at"""

    def put(self, entry: CatalogEntry) -> CatalogEntry:
        self._write([(self._UPSERT, (
            entry.iri, json.dumps(entry.pointer), pointer_key(entry.pointer), entry.title, entry.document_type,
            entry.owner, entry.sensitivity_label, entry.state, entry.produced_by, entry.context,
            entry.source_kind, entry.baseline_version, entry.unassociated, entry.created_at, entry.updated_at))])
        return entry

    def put_embedding(self, iri: str, vector: list[float], model: str) -> None:
        """ONE statement: the foreign key is the row check, so a missing row costs no second round-trip."""
        if len(vector) != self.dim:
            raise ValueError(f"the index holds {self.dim}-dimensional vectors, not {len(vector)}")
        try:
            self._write([("""
                INSERT INTO fabric_embedding (iri, model, embedding, updated_at) VALUES (%s, %s, %s::vector, now())
                ON CONFLICT (iri) DO UPDATE SET model = EXCLUDED.model, embedding = EXCLUDED.embedding,
                                                updated_at = now()""", (iri, model, _literal(vector)))])
        except CatalogUnreachable as exc:
            if "ForeignKey" in str(exc):
                raise LookupError(f"no catalog entry {iri}") from exc
            raise

    def embedding(self, iri: str) -> tuple[list[float], str] | None:
        rows = self._rows("SELECT embedding::text, model FROM fabric_embedding WHERE iri = %s", (iri,))
        if not rows:
            return None
        text, model = rows[0]
        return [float(v) for v in str(text).strip("[]").split(",") if v.strip()], model

    def similar(self, vector: list[float], limit: int = 5, *, exclude: str = "",
                model: str = "") -> list[tuple[str, float]]:
        """Nearest rows within ONE embedding space (`model`), by cosine, over the hnsw index."""
        if int(limit) <= 0:
            return []
        by, d = _ranked_by(self.dim), self.dim
        rows = self._rows(f"""
            SELECT iri, 1 - ({by} <=> %s::halfvec({d})) AS score FROM fabric_embedding
             WHERE iri <> %s AND (%s = '' OR model = %s)
             ORDER BY {by} <=> %s::halfvec({d}) LIMIT %s""",
                          (_literal(vector), exclude, model, model, _literal(vector), int(limit)))
        return [(r[0], float(r[1])) for r in rows]

    def unindexed(self, model: str) -> list[CatalogEntry]:
        rows = self._rows("SELECT " + ", ".join(f"a.{c}" for c in _COLUMNS) + """ FROM fabric_artifact a
             LEFT JOIN fabric_embedding e ON e.iri = a.iri AND e.model = %s
             WHERE e.iri IS NULL AND a.state <> 'withdrawn' ORDER BY a.created_at""", (model,))
        return [_entry(r) for r in rows]


def build(**overrides: Any) -> PostgresCatalog:
    """The container's factory. Settings come from `lab.platform.config`, the one env reader."""
    import psycopg

    options: dict[str, Any] = {"dsn": config.FABRIC_DB_URL, "connect": psycopg.connect,
                               "dim": config.REFERENCE_EMBED_DIM}
    options.update(overrides)
    return PostgresCatalog(**options)
