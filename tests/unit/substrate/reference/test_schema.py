

# ------------------------------------------------- what a live `init --grants` found

def test_the_roles_the_grants_name_are_created_by_the_migration():
    """`--grants` was unrunnable on a fresh database — the only kind anybody runs it on — because a
    GRANT to a role that does not exist is an error. DR-03 rests entirely on these two roles
    existing and differing, so creating them is part of the schema rather than a prerequisite an
    operator was expected to guess."""
    from lab.substrate.reference.schema import PUBLISHER_GRANTS, READER_GRANTS, ROLES
    created = " ".join(ROLES)
    for grant in READER_GRANTS + PUBLISHER_GRANTS:
        role = grant.rsplit(" TO ", 1)[1].strip()
        assert f"CREATE ROLE {role} " in created, f"{role} is granted to but never created"


def test_the_roles_are_created_idempotently():
    """`init` is re-run whenever the schema changes; the second run must not fail on a role the
    first one made."""
    from lab.substrate.reference.schema import ROLES
    for statement in ROLES:
        assert "IF NOT EXISTS" in statement


def test_the_roles_cannot_log_in():
    """They are privilege SETS granted to whatever login role a deployment already has — so there
    is no new credential to distribute, and "which role does reference-mcp connect as" stays a
    deployment decision rather than one this migration takes on the tenant's behalf."""
    from lab.substrate.reference.schema import ROLES
    assert all("NOLOGIN" in s for s in ROLES)


def test_no_approximate_index_is_created_over_the_embeddings():
    """An HNSW index cannot be built on an undimensioned column — which is how this was found — but
    the deeper reason it is absent is that HNSW is APPROXIMATE. This corpus refuses truncated
    answers everywhere else (`IndexUnavailable` exists precisely because a short result set is
    indistinguishable from a thorough search that found little), and recall below 1 would
    reintroduce exactly that where nobody could see it."""
    from lab.substrate.reference.schema import MIGRATIONS
    sql = " ".join(MIGRATIONS).lower()
    assert "hnsw" not in sql and "ivfflat" not in sql
    # ... but the scan must still be scoped to the pinned version rather than the whole table.
    assert "ref_passage_scope" in sql


# ------------------------------------------------- retrieval mode and record-backed passages

def test_the_retrieval_mode_is_a_column_added_idempotently_to_an_existing_corpus():
    """The corpus already holds fifty artifacts; a mode they did not declare arrives as an ALTER
    that a second `init` survives, defaulting every existing artifact to the exact read it has
    always had."""
    from lab.substrate.reference.schema import MIGRATIONS
    alters = [s for s in MIGRATIONS if "ALTER TABLE ref_artifact " in s]
    assert any("retrieval" in s and "IF NOT EXISTS" in s and "DEFAULT 'key'" in s for s in alters)
    sql = " ".join(MIGRATIONS)
    assert "'whole'" in sql and "'vector'" in sql, "the three modes are a CHECK, not a convention"
    assert "kind <> 'prose' OR retrieval = 'vector'" in sql, "prose can only be searched"


def test_a_passage_may_name_the_record_it_was_derived_from():
    from lab.substrate.reference.schema import MIGRATIONS
    assert any("ALTER TABLE ref_passage ADD COLUMN IF NOT EXISTS record_id" in s
               for s in MIGRATIONS)
    assert any("ref_passage_record_fk" in s and "REFERENCES ref_record" in s for s in MIGRATIONS)


def test_every_constraint_added_after_the_fact_checks_for_itself_first():
    """Postgres has no `ADD CONSTRAINT IF NOT EXISTS`, so each one is guarded by a lookup in
    `pg_constraint` — the second `init` must not fail on the first one's work."""
    from lab.substrate.reference.schema import MIGRATIONS
    for statement in MIGRATIONS:
        if "ADD CONSTRAINT" in statement:
            assert "pg_constraint" in statement and "IF NOT EXISTS" in statement, statement


def test_the_version_table_carries_the_mode_too_because_a_pin_freezes_versions():
    from lab.substrate.reference.schema import MIGRATIONS
    assert any("ALTER TABLE ref_artifact_version ADD COLUMN IF NOT EXISTS retrieval" in s
               for s in MIGRATIONS)
    assert "ref_artifact_version_retrieval_check" in " ".join(MIGRATIONS)
