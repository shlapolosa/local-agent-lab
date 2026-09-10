"""The reference corpus's tables — one idempotent migration list, applied by the publisher only.

`lab_artifacts` is NOT extended, deliberately. It is the byte store, shared with uploads and
renders; the review app writes to it; its `put` mints a random id on purpose and it has no UPDATE
path. Adding version, signature and status columns there would give governance meaning to SVGs and
human uploads that have none, need an update path the store does not want, and make DR-03
unenforceable — the same table is written by the Submit page. So the BYTES of both forms live in
`lab_artifacts` through the existing `store()` port, and everything governed lives here.

A consequence worth stating: the reference server never opens an artifact. Publication explodes the
agent-readable form into rows, so the server needs no `ARTIFACTS_URL` and no bucket credential at
all — the smallest blast radius available for the service that answers "what does the rule say".

`ref_release` is keyed on (artifact, ring) rather than carrying a `status='current'` column,
because while a change rolls, ring 0 may resolve to v3 while ring 2 still resolves to v2 and BOTH
are the signed current version for whoever is asking. Resolution is then a single-row SELECT, and
supersede and roll-back are the same one-row UPDATE.
"""
from __future__ import annotations

__all__ = ["MIGRATIONS", "READER_GRANTS", "PUBLISHER_GRANTS", "ROLES",
           "apply_migrations"]

MIGRATIONS: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS vector",

    """CREATE TABLE IF NOT EXISTS ref_signing_key (
         key_id TEXT PRIMARY KEY,
         algorithm TEXT NOT NULL,
         public_key TEXT NOT NULL,
         valid_from TIMESTAMPTZ NOT NULL,
         revoked_at TIMESTAMPTZ)""",

    """CREATE TABLE IF NOT EXISTS ref_artifact (
         artifact_id TEXT PRIMARY KEY,
         kind TEXT NOT NULL CHECK (kind IN ('record','prose')),
         record_type TEXT,
         title TEXT NOT NULL,
         owner TEXT NOT NULL,
         CHECK ((kind = 'record') = (record_type IS NOT NULL)))""",

    # Append-only. `CHECK (derived_from = master_sha256)` is DR-02 as a database constraint: a row
    # whose agent-readable form was derived from a different master cannot exist.
    """CREATE TABLE IF NOT EXISTS ref_artifact_version (
         artifact_id TEXT NOT NULL REFERENCES ref_artifact,
         version TEXT NOT NULL,
         status TEXT NOT NULL CHECK (status IN ('draft','published','withdrawn')),
         master_ref TEXT NOT NULL,
         master_sha256 TEXT NOT NULL,
         agent_ref TEXT NOT NULL,
         agent_sha256 TEXT NOT NULL,
         derived_from TEXT NOT NULL,
         manifest_sha256 TEXT NOT NULL,
         signature TEXT NOT NULL,
         key_id TEXT NOT NULL REFERENCES ref_signing_key,
         signed_at TIMESTAMPTZ NOT NULL,
         published_at TIMESTAMPTZ NOT NULL,
         supersedes TEXT,
         PRIMARY KEY (artifact_id, version),
         CHECK (derived_from = master_sha256))""",

    # What makes "fail closed" checkable rather than hoped for: a search joins this and refuses on
    # a NULL completion, a zero count, or an embedding model/width that is not the query's.
    """CREATE TABLE IF NOT EXISTS ref_index_state (
         artifact_id TEXT NOT NULL,
         version TEXT NOT NULL,
         records INT NOT NULL DEFAULT 0,
         passages INT NOT NULL DEFAULT 0,
         embed_model TEXT,
         embed_dim INT,
         completed_at TIMESTAMPTZ,
         PRIMARY KEY (artifact_id, version),
         FOREIGN KEY (artifact_id, version)
           REFERENCES ref_artifact_version ON DELETE CASCADE)""",

    """CREATE TABLE IF NOT EXISTS ref_release (
         artifact_id TEXT NOT NULL,
         ring SMALLINT NOT NULL,
         version TEXT NOT NULL,
         released_at TIMESTAMPTZ NOT NULL,
         released_by TEXT NOT NULL,
         PRIMARY KEY (artifact_id, ring),
         FOREIGN KEY (artifact_id, version) REFERENCES ref_artifact_version)""",

    """CREATE TABLE IF NOT EXISTS ref_record (
         artifact_id TEXT NOT NULL,
         version TEXT NOT NULL,
         record_id TEXT NOT NULL,
         record_type TEXT NOT NULL,
         key JSONB NOT NULL,
         body JSONB NOT NULL,
         PRIMARY KEY (artifact_id, version, record_id),
         FOREIGN KEY (artifact_id, version)
           REFERENCES ref_artifact_version ON DELETE CASCADE)""",
    "CREATE INDEX IF NOT EXISTS ref_record_key ON ref_record USING GIN (key jsonb_path_ops)",
    "CREATE INDEX IF NOT EXISTS ref_record_type ON ref_record (record_type, artifact_id, version)",

    # `anchor` is the heading path a person searches the master for. `embed_model`/`embed_dim` are
    # per row so a query embedded by a different model is DETECTABLE rather than silently compared,
    # which is the whole difference between a vector store and a governed one.
    """CREATE TABLE IF NOT EXISTS ref_passage (
         artifact_id TEXT NOT NULL,
         version TEXT NOT NULL,
         passage_id TEXT NOT NULL,
         ordinal INT NOT NULL,
         heading_path TEXT[] NOT NULL,
         anchor TEXT NOT NULL,
         text TEXT NOT NULL,
         tokens INT NOT NULL,
         embed_model TEXT NOT NULL,
         embed_dim INT NOT NULL,
         embedding vector NOT NULL,
         PRIMARY KEY (artifact_id, version, passage_id),
         FOREIGN KEY (artifact_id, version)
           REFERENCES ref_artifact_version ON DELETE CASCADE)""",
    # NO approximate index, and this is a decision rather than an omission.
    #
    # It began as an HNSW index and failed on the live database: pgvector cannot index a column
    # with no declared width, and the width is deliberately undeclared so re-embedding at another
    # model's dimension needs no migration. The obvious repairs are both worse. Pinning
    # `vector(N)` puts one model's width into a migration and makes a model change a schema
    # change. Keeping HNSW makes the search APPROXIMATE — and an approximate result set is exactly
    # what this corpus refuses everywhere else: `IndexUnavailable` exists because a truncated
    # answer is indistinguishable from a thorough search that found little, and HNSW recall below
    # 1 reintroduces that through the back door, where "no guardrail matched" could be an index
    # artifact nobody can see.
    #
    # So: exact cosine, sequentially. The corpus is dozens of artifacts and hundreds of passages —
    # a scan is milliseconds, and the ordering is the true one. `ref_passage_scope` keeps the scan
    # to the pinned version rather than the whole table, which is where the real saving is. When a
    # corpus arrives that genuinely needs ANN, the answer is a dimensioned column per embedding
    # model, not an approximate index over an undimensioned one.
    "CREATE INDEX IF NOT EXISTS ref_passage_scope ON ref_passage (artifact_id, version)",

    """CREATE TABLE IF NOT EXISTS ref_pin (
         pin_id TEXT PRIMARY KEY,
         ring SMALLINT NOT NULL,
         pinned_at TIMESTAMPTZ NOT NULL,
         expires_at TIMESTAMPTZ NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ref_pin_entry (
         pin_id TEXT NOT NULL REFERENCES ref_pin ON DELETE CASCADE,
         artifact_id TEXT NOT NULL,
         version TEXT NOT NULL,
         PRIMARY KEY (pin_id, artifact_id),
         FOREIGN KEY (artifact_id, version) REFERENCES ref_artifact_version)""",

    # DR-06 / FR-44 / FR-45. `field` is the DERIVED FIELD, not just the run: "which field was this
    # consulted for" is what makes the reverse index worth having at review.
    """CREATE TABLE IF NOT EXISTS ref_consumption (
         id BIGSERIAL PRIMARY KEY,
         run_id TEXT NOT NULL,
         process TEXT NOT NULL,
         field TEXT NOT NULL,
         artifact_id TEXT NOT NULL,
         version TEXT NOT NULL,
         mode TEXT NOT NULL CHECK (mode IN ('lookup','search','record')),
         locator TEXT,
         query_digest TEXT NOT NULL,
         hit BOOLEAN NOT NULL,
         pin_id TEXT NOT NULL,
         consulted_at TIMESTAMPTZ NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS ref_consumption_reverse ON ref_consumption "
    "(artifact_id, version, consulted_at DESC)",
    "CREATE INDEX IF NOT EXISTS ref_consumption_run ON ref_consumption (run_id, field)",

    # ---- added after fifty artifacts were already published: ALTERs, never a rewritten CREATE.
    #
    # `retrieval` is how a CONSUMER reads the artifact — whole / key / vector — declared on the
    # artifact so no caller infers it from size (see `lab.core.reference.model.Retrieval`). Every
    # existing artifact defaults to `key`, the exact read it has always had. Postgres has no
    # `ADD CONSTRAINT IF NOT EXISTS`, so each constraint looks itself up in `pg_constraint` first;
    # a second `init` must survive the first one's work.
    # On the ARTIFACT (the current declaration, what the catalogue lists) AND on the VERSION (what
    # a pin froze): `ref_artifact_version` is append-only so that a pin means something, and a mode
    # only on the artifact row would be the one attribute of a pinned version a re-publish could
    # rewrite — flipping a released `key` version to `vector` would fail every search under every
    # pin in that ring until the index it never had was built.
    "ALTER TABLE ref_artifact ADD COLUMN IF NOT EXISTS retrieval TEXT NOT NULL DEFAULT 'key'",
    "ALTER TABLE ref_artifact_version ADD COLUMN IF NOT EXISTS retrieval TEXT NOT NULL "
    "DEFAULT 'key'",
    """DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ref_artifact_retrieval_check')
          THEN ALTER TABLE ref_artifact ADD CONSTRAINT ref_artifact_retrieval_check
               CHECK (retrieval IN ('whole','key','vector'));
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_constraint
                          WHERE conname = 'ref_artifact_version_retrieval_check')
          THEN ALTER TABLE ref_artifact_version ADD CONSTRAINT ref_artifact_version_retrieval_check
               CHECK (retrieval IN ('whole','key','vector'));
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ref_artifact_prose_is_vector')
          THEN ALTER TABLE ref_artifact ADD CONSTRAINT ref_artifact_prose_is_vector
               CHECK (kind <> 'prose' OR retrieval = 'vector');
          END IF;
        END $$""",
    # A passage derived FROM a record names it, so a semantic hit over a record artifact resolves
    # to the exact row. NULL for prose passages; the composite FK is skipped on NULL (MATCH SIMPLE).
    "ALTER TABLE ref_passage ADD COLUMN IF NOT EXISTS record_id TEXT",
    """DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ref_passage_record_fk')
          THEN ALTER TABLE ref_passage ADD CONSTRAINT ref_passage_record_fk
               FOREIGN KEY (artifact_id, version, record_id)
               REFERENCES ref_record (artifact_id, version, record_id) ON DELETE CASCADE;
          END IF;
        END $$""",
)

#: DR-03 as a GRANT rather than a convention. The server is configured with the reader role, so a
#: compromised server cannot write a shared artifact — the database refuses. Directly testable: the
#: integration suite asserts `InsufficientPrivilege` on an INSERT into `ref_record`.
_READ_TABLES = ("ref_signing_key", "ref_artifact", "ref_artifact_version", "ref_index_state",
                "ref_release", "ref_record", "ref_passage")
_WRITE_TABLES = _READ_TABLES + ("ref_pin", "ref_pin_entry", "ref_consumption")

#: The two roles the grants below name. Created HERE, idempotently, because a GRANT to a role that
#: does not exist is an error and `--grants` was therefore unrunnable on a fresh database — which
#: is the only database anybody runs it on. DR-03 ("no instance writes to a shared store") rests
#: entirely on these two roles existing and differing, so creating them is part of the schema, not
#: a prerequisite an operator is expected to have guessed.
#:
#: NOLOGIN and no password: they are privilege SETS, granted to whatever login role a deployment
#: already has. That keeps the credential story unchanged — no new secret to distribute — and
#: leaves "which role does reference-mcp connect as" a deployment decision rather than one this
#: migration takes on the tenant's behalf.
ROLES: tuple[str, ...] = tuple(
    f"""DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
            CREATE ROLE {role} NOLOGIN;
          END IF;
        END $$"""
    for role in ("lab_reference_reader", "lab_reference_publisher"))

READER_GRANTS: tuple[str, ...] = tuple(
    [f"GRANT SELECT ON {t} TO lab_reference_reader" for t in _READ_TABLES]
    + [f"GRANT SELECT, INSERT ON {t} TO lab_reference_reader"
       for t in ("ref_pin", "ref_pin_entry", "ref_consumption")]
    + ["GRANT USAGE, SELECT ON SEQUENCE ref_consumption_id_seq TO lab_reference_reader"])

PUBLISHER_GRANTS: tuple[str, ...] = tuple(
    f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO lab_reference_publisher"
    for t in _WRITE_TABLES)


def apply_migrations(connection, *, grants: bool = False) -> int:
    """Run every migration in order. Idempotent — each statement is `IF NOT EXISTS` or a GRANT."""
    statements = MIGRATIONS + (ROLES + READER_GRANTS + PUBLISHER_GRANTS if grants else ())
    with connection.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
    connection.commit()
    return len(statements)
