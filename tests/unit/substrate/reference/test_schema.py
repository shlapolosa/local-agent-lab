

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
