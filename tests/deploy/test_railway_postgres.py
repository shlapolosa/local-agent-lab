"""Postgres moves INSIDE the substrate, beside Redis — for the same reason Redis did.

Redis Cloud's 30-client free cap was blown by LiteLLM alone; Neon's free-tier COMPUTE HOURS were
burned by those same pools keeping the endpoint from ever auto-suspending. Measured 19 Sep 2026:
~110 h against a 100 h allowance, after which every new connection was refused and every virtual
key returned 401 — the whole lab down, with only the master key (which needs no database lookup)
still answering. A managed database on a metered free tier is a cliff; one on the private network
beside the services that use it is not.

It carries TWO of Neon's three jobs — the LiteLLM registry and the reference corpus. The third,
the artifact store, is configuration: `artifacts.py` already dispatches on URL scheme and its own
docstring says "Railway Bucket now, Azure Blob later".
"""
import deploy.railway as R


def test_the_default_image_ships_pgvector_rather_than_hoping_the_base_has_it():
    """The corpus needs `CREATE EXTENSION vector` (schema.py's first statement). Railway's own
    Postgres template may or may not carry pgvector depending on version; defaulting to an image
    that GUARANTEES it removes the question. Discovering it missing at publish time would fail
    AFTER the migration rather than before it."""
    assert "pgvector" in R.PG_IMAGE
    assert ":pg" in R.PG_IMAGE, "pinned to a postgres major, never a moving tag"


def test_the_image_is_overridable_so_railways_own_postgres_can_be_used_instead():
    """Two deployment shapes, one code path: Railway's hosted template and our own pgvector image
    are both just an image on a service here. `LAB_PG_IMAGE` picks, so choosing between them is a
    setting rather than an edit — and swapping back is the same setting."""
    import os
    assert R.PG_IMAGE == (os.environ.get("LAB_PG_IMAGE") or R.PG_IMAGE_DEFAULT)
    assert "pgvector" in R.PG_IMAGE_DEFAULT


def test_it_listens_on_both_address_families():
    """Railway private DNS (*.railway.internal) is IPv6-only. Redis needed `--bind 0.0.0.0 ::` for
    exactly this, and the gateway's own IPv4-edge/IPv6-probe split is the same bug class. Postgres
    spells it `listen_addresses='*'`, which is all interfaces of BOTH families."""
    assert "listen_addresses" in R.PG_CMD and "'*'" in R.PG_CMD


def test_the_data_directory_is_on_a_volume():
    """Without it a redeploy is a data loss: the registry's keys and the whole published corpus."""
    assert R.PG_VOLUME == "/var/lib/postgresql/data"


def test_it_has_no_public_domain_and_is_reached_only_on_the_private_network():
    """The private network IS the trust boundary here, as for Redis and the embedder. A database
    on a public domain is a credential away from the internet."""
    assert R.PG_NAME not in R.SUBSTRATE or R.SUBSTRATE[R.PG_NAME].get("port") is None


def test_the_internal_dsn_names_the_service_not_a_vendor_host():
    """What every consumer's DATABASE_URL becomes. `postgres.railway.internal` is the service's own
    private name — the one thing that must change in `.env`, and the only thing."""
    dsn = R.pg_internal_dsn("secret", db="litellm")
    assert dsn.startswith("postgresql://")
    assert f"@{R.PG_NAME}.railway.internal:5432/litellm" in dsn
    assert "secret" in dsn


def test_the_password_is_never_defaulted_to_something_guessable():
    """A blank or well-known password on a database holding every virtual key is not a lab
    shortcut, it is the whole registry."""
    import pytest
    for bad in ("", "postgres", None):
        with pytest.raises(ValueError):
            R.pg_internal_dsn(bad, db="litellm")


def test_postgres_comes_up_before_anything_that_reads_it():
    """Ordering is the contract: the gateway runs prisma at boot and an MCP server opens its pool
    on the first request. Starting them against a database that is not listening yet reproduces
    exactly the outage this migration exists to end."""
    import inspect
    src = inspect.getsource(R.substrate_up)
    assert "ensure_postgres(base)" in src
    assert src.index("ensure_postgres(base)") < src.index("for name, spec in table.items()")
    assert src.index("ensure_postgres(base)") < src.index("ensure_redis()")


def test_it_is_provisioned_only_when_configured_so_an_external_database_still_deploys():
    """Same idiom as `embedder_enabled`. A deployment may legitimately point DATABASE_URL at a
    database somebody else runs, and during the migration off Neon both are live at once — so the
    substrate must not start refusing for everyone the moment this service exists."""
    assert R.postgres_enabled({"LAB_PG_PASSWORD": "s3cret"}) is True
    assert R.postgres_enabled({"POSTGRES_PASSWORD": "s3cret"}) is True
    assert R.postgres_enabled({}) is False


# ---------------------------------------------------------------- the operator's way in


def test_the_operator_can_reach_it_because_publishing_cannot_move_into_the_cloud():
    """The reference publisher holds the Ed25519 signing SEED, and that seed deliberately never
    enters `.env` or `LAB_ENV` — "it belongs on the publishing workstation only". So publishing
    cannot be run as a Railway job, and the database must be reachable from the workstation.

    This is parity with what it replaces, not a new exposure: Neon was a public endpoint with
    password auth too. The proxy is TCP on the postgres port, the password is required and
    unguessable, and nothing else about the service is public.
    """
    assert R.PG_PROXY_PORT == 5432


def test_the_proxy_is_opt_in_so_a_deployment_that_does_not_need_it_has_no_public_database():
    """An operator publishes rarely. A database that is only ever read by services on the private
    network should not carry a public endpoint the rest of the time."""
    assert R.pg_proxy_wanted({"LAB_PG_PUBLIC": "1"}) is True
    assert R.pg_proxy_wanted({}) is False


def test_the_public_dsn_is_built_from_what_railway_returns_not_guessed():
    """Railway assigns the proxy host and a RANDOM external port; a hardcoded 5432 would connect
    to nothing, or worse, to something else."""
    dsn = R.pg_public_dsn("roundhouse.proxy.rlwy.net", 41234, "s3cret", db="litellm")
    assert dsn == "postgresql://postgres:s3cret@roundhouse.proxy.rlwy.net:41234/litellm"


def test_the_start_command_goes_THROUGH_the_images_entrypoint():
    """A Railway start command replaces the entrypoint and is exec'd directly — the same gotcha
    that makes `a && b` run only `a`. `postgres …` on its own therefore runs as ROOT, which
    Postgres refuses: "root execution of the PostgreSQL server is not permitted". The first deploy
    crash-looped on precisely that. The entrypoint runs initdb, applies POSTGRES_PASSWORD and
    re-execs as the postgres user, so it has to be named."""
    assert R.PG_CMD.startswith("docker-entrypoint.sh ")
    assert "postgres" in R.PG_CMD


# ---------------------------------------------------------------- the live run view


def test_the_live_view_holds_the_gate_and_redis_and_nothing_else():
    """It shows what is HAPPENING, never what a run produced — so it needs no store, no model and
    no EA credential. A public service with the narrowest possible slice."""
    env = set(R.ROLE_ENV["live"])
    assert {"REVIEW_APP_PASSWORD", "REDIS_URL"} <= env
    for forbidden in ("DATABASE_URL", "ARTIFACTS_URL", "MCP_SHARED_SECRET", "LITELLM_MASTER_KEY",
                      "OLLAMA_API_KEY", "ADOIT_PASSWORD", "S3_SECRET_ACCESS_KEY"):
        assert forbidden not in env, forbidden


def test_the_live_view_is_public_because_a_person_opens_it():
    assert R.SUBSTRATE["live"]["port"] == 10000
