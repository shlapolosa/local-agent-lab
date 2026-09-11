"""Offline tests for deploy/railway.py's .env parsing + per-role env ALLOWLIST (B-H2, B-M4) and
scripts/e2e_smoke.py's env reader (B-M6). No Railway, no network: the module is imported without
RAILWAY_* credentials and every check runs against a temp .env / a fake env dict.

Env is pinned in a FIXTURE, never at import (tests/conftest.py: no module may leak its environment
into the shared process).

Run:  .venv/bin/python tests/deploy/test_railway_env.py      (also pytest-compatible)
"""
import importlib.util
import os
import re
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


railway = None                    # the module under test; loaded by `railway_module`


@pytest.fixture(scope="module", autouse=True)
def railway_module():
    """Importing deploy/railway.py must NOT require Railway credentials — e2e_smoke reuses its parser
    without them — so it is imported here with RAILWAY_* removed, in a fixture rather than at module
    import, and the environment is put back with the module."""
    global railway
    mp = pytest.MonkeyPatch()
    for k in ("RAILWAY_TOKEN", "RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID"):
        mp.delenv(k, raising=False)
    railway = _load("lab_railway", "deploy/railway.py")
    yield
    mp.undo()
    railway = None

ENV_TEXT = """\
# comment line
LITELLM_MASTER_KEY=sk-master
DATABASE_URL=postgresql://neon/db
ARTIFACTS_URL=$DATABASE_URL
UPLOADS_URL=${ARTIFACTS_URL}
GATEWAY_URL=http://127.0.0.1:4000
# CLOUD: GATEWAY_URL=https://gw.example   # the public domain
REDIS_URL=redis://127.0.0.1:6379/0
# CLOUD: REDIS_URL='redis://redis.railway.internal:6379/0'
QUOTED='{"a": "b #not-a-note"}'
DQUOTED="dq value"
NOTED=value   # an inline note
UNKNOWN_REF=$NOPE
EMPTY=
lowercase=ignored
NOT A LINE
"""


def _tmp_env(text=ENV_TEXT):
    d = tempfile.mkdtemp()
    p = os.path.join(d, ".env")
    with open(p, "w") as f:
        f.write(text)
    return p


# ---------------------------------------------------------------- parse_env / load_env_for_cloud
def test_cloud_override_wins_and_note_stripped():
    p = _tmp_env()
    cloud = railway.parse_env(p, cloud=True)
    local = railway.parse_env(p, cloud=False)
    assert cloud["GATEWAY_URL"] == "https://gw.example"          # `# CLOUD:` wins, inline note gone
    assert local["GATEWAY_URL"] == "http://127.0.0.1:4000"       # local profile ignores CLOUD lines
    assert cloud["REDIS_URL"] == "redis://redis.railway.internal:6379/0"   # quotes stripped on CLOUD lines
    assert local["REDIS_URL"] == "redis://127.0.0.1:6379/0"


def test_var_expansion_one_level_of_chaining():
    env = railway.load_env_for_cloud(_tmp_env())
    assert env["ARTIFACTS_URL"] == "postgresql://neon/db"        # $VAR
    assert env["UPLOADS_URL"] == "postgresql://neon/db"          # ${VAR} -> $VAR (chained, 2 passes)
    assert env["UNKNOWN_REF"] == "$NOPE"                         # unknown refs left untouched


def test_inline_note_and_quotes():
    env = railway.load_env_for_cloud(_tmp_env())
    assert env["NOTED"] == "value"                               # unquoted: trailing ` # note` stripped
    assert env["QUOTED"] == '{"a": "b #not-a-note"}'             # quoted: content intact, quotes gone
    assert env["DQUOTED"] == "dq value"


def test_empty_and_malformed_lines_dropped():
    env = railway.load_env_for_cloud(_tmp_env())
    assert "EMPTY" not in env
    assert "lowercase" not in env and "NOT A LINE" not in env


# ---------------------------------------------------------------- ROLE_ENV allowlist
FAKE = {
    # management / provisioning (never shipped)
    "RAILWAY_TOKEN": "t", "RAILWAY_PROJECT_ID": "p", "RAILWAY_ENVIRONMENT_ID": "e",
    "NEON_API_KEY": "n", "NEON_PROJECT_ID": "n", "NEON_ORG_ID": "n",
    "OCI_TENANCY_OCID": "o", "OCI_USER_OCID": "o", "OCI_KEY_FILE": "o",
    "ENTRA_GATEWAY_APP_ID": "a", "DEV_CLIENT_ID": "d", "VISIO_TEAM_ID": "v",
    "ARCHIMATE_SKILL_ID": "s", "VISIO_READER_SKILL_ID": "s",
    "EA_AGENT_KEY": "k", "EA_AGENT_CLIENT_ID": "k", "EA_AGENT_CLIENT_SECRET": "k",
    "REDIS_HOST": "h", "REDIS_PORT": "6379", "REDIS_PASSWORD": "pw",
    # gateway secrets
    "LITELLM_MASTER_KEY": "m", "LITELLM_MCP_CLIENT_TIMEOUT": "300", "LITELLM_MCP_TOOL_LISTING_TIMEOUT": "60",
    "DATABASE_URL": "pg", "OLLAMA_API_KEY": "ol", "ANTHROPIC_UPSTREAM_API_KEY": "an",
    "EMBED_URL": "emb", "PG_VECTOR_API_BASE": "pvb", "PG_VECTOR_API_KEY": "pvk", "REFERENCE_RING": "x", "REFERENCE_MCP_URL": "x", "REFERENCE_PROVIDER": "x",
    "MICROSOFT_CLIENT_ID": "mc", "MICROSOFT_CLIENT_SECRET": "ms", "MICROSOFT_TENANT": "mt",
    "PROXY_BASE_URL": "pb", "DEVELOPERS_TEAM_ID": "dt", "ENTRA_CLIENT_TO_KEY": "{}",
    "OTEL_EXPORTER": "otlp_http", "OTEL_ENDPOINT": "e", "OTEL_SERVICE_NAME": "litellm-gateway",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://jaeger:4318",
    # shared trust / coordinates
    "MCP_SHARED_SECRET": "sec", "BIND_HOST": "::",
    "ADOIT_MCP_URL": "u", "SEMANTIC_MCP_URL": "u", "STORAGE_MCP_URL": "u", "GRAPH_MCP_URL": "u",
    "GATEWAY_URL": "https://gw", "REVIEW_APP_URL": "https://rv", "JAEGER_UI_URL": "https://jg",
    "REDIS_URL": "redis://redis:6379/0", "ARTIFACTS_URL": "pg",
    # ADOIT
    "ADOIT_BASE_URL": "a", "ADOIT_USERNAME": "a", "ADOIT_PASSWORD": "a", "ADOIT_REPO_ID": "a",
    "ADOIT_REST_WRITE": "false",
    # bucket
    "S3_ENDPOINT": "s", "S3_REGION": "s", "S3_ACCESS_KEY_ID": "s", "S3_SECRET_ACCESS_KEY": "s",
    "S3_URL_STYLE": "path", "UPLOADS_URL": "s3://b/uploads", "RAILWAY_BUCKET_ID": "b",
    # review
    "REVIEW_APP_PASSWORD": "r",
    # workload
    "BA_AGENT_KEY": "b", "BA_AGENT_CLIENT_ID": "b", "BA_AGENT_CLIENT_SECRET": "b",
    "ARCHITECT_AGENT_KEY": "c", "ARCHITECT_AGENT_CLIENT_ID": "c", "ARCHITECT_AGENT_CLIENT_SECRET": "c",
    "ENTRA_TENANT_ID": "tid", "ENTRA_GATEWAY_AUDIENCE": "api://gw",
    "AGENT_RESPONSES_STORE": "false", "VISIO_DIAGRAM": "art://x/y.vsdx", "VISIO_REQUIREMENTS": "",
    "BA_MAX_DOC_CHARS": "60000", "BA_MODE": "json", "ARCHITECT_MODE": "json",
    "TELEGRAM_BOT_TOKEN": "tg", "TELEGRAM_CHAT_ID": "tg", "TEAMS_WEBHOOK_URL": "https://hook",
    "MEETING_WEBHOOK_URL": "https://flow.example/notify",
    # collaboration adapter (graph-mcp)
    "COLLAB_PROVIDER": "graph", "GRAPH_CLIENT_ID": "g", "GRAPH_CLIENT_SECRET": "g",
    "GRAPH_AUTH_MODE": "app", "GRAPH_BASE_URL": "https://graph.example", "GRAPH_MEETING_USER": "c@l",
    "GRAPH_NOTIFICATION_ALLOWLIST": "https://flow.example", "GRAPH_ALLOW_METERED": "false",
    "GRAPH_MCP_PORT": "9500",
}
MANAGEMENT = {k for k in FAKE if k.startswith(("RAILWAY_", "NEON_", "OCI_"))}


def _has(env, *prefixes):
    return sorted(k for k in env if k.startswith(prefixes))


def test_workload_receives_no_substrate_secrets():
    # Per-workload now: the shared list plus THIS process's own. One shared list meant the meeting
    # workload was handed the visio agents' client secrets, which is the blast radius this table
    # exists to prevent — so the visio slice is asserted here and the isolation below.
    env = railway.env_for_role("workload", FAKE, workload="visio")
    for k in ("LITELLM_MASTER_KEY", "OLLAMA_API_KEY", "ANTHROPIC_UPSTREAM_API_KEY", "MCP_SHARED_SECRET",
              "DATABASE_URL", "ARTIFACTS_URL", "UPLOADS_URL", "ADOIT_MCP_URL", "SEMANTIC_MCP_URL",
              "STORAGE_MCP_URL", "BIND_HOST", "REVIEW_APP_PASSWORD", "EA_AGENT_KEY", "ENTRA_CLIENT_TO_KEY"):
        assert k not in env, k
    assert not _has(env, "ADOIT_", "MICROSOFT_", "S3_", "TELEGRAM_", "REDIS_HOST", "REDIS_PASSWORD",
                    "GRAPH_", "COLLAB_")     # the collaboration credential is the substrate's alone
    for k in ("GATEWAY_URL", "REVIEW_APP_URL", "JAEGER_UI_URL", "REDIS_URL", "OTEL_EXPORTER_OTLP_ENDPOINT",
              "BA_AGENT_KEY", "BA_AGENT_CLIENT_ID", "BA_AGENT_CLIENT_SECRET",
              "ARCHITECT_AGENT_KEY", "ARCHITECT_AGENT_CLIENT_ID", "ARCHITECT_AGENT_CLIENT_SECRET",
              "ENTRA_TENANT_ID", "ENTRA_GATEWAY_AUDIENCE", "AGENT_RESPONSES_STORE",
              "VISIO_DIAGRAM", "BA_MAX_DOC_CHARS", "BA_MODE", "ARCHITECT_MODE"):
        assert k in env, k
    assert _has(env, "OTEL_")                               # tracing sink present ...
    assert "OTEL_SERVICE_NAME" not in env                   # ... but not the gateway's service name


def test_one_workload_never_receives_another_workloads_agent_credentials():
    """The shared list is what every workload needs; a process's own agents are its own. A single
    combined list handed the meeting workload BA_AGENT_CLIENT_SECRET, which it has no use for and
    should never be able to leak."""
    meeting = railway.env_for_role("workload", FAKE, workload="meeting")
    assert not _has(meeting, "BA_", "ARCHITECT_", "VISIO_")
    for k in ("GATEWAY_URL", "REDIS_URL", "REVIEW_APP_URL", "ENTRA_TENANT_ID"):
        assert k in meeting, k                              # the shared coordinates still arrive
    visio = railway.env_for_role("workload", FAKE, workload="visio")
    assert not _has(visio, "MEETING_")


def test_an_unregistered_workload_is_refused_rather_than_given_a_default():
    """Never ship an env by accident: a process with no allowlist row raises instead of quietly
    receiving only the shared keys (or, worse, everything)."""
    import pytest as _pytest
    with _pytest.raises(KeyError):
        railway.env_for_role("workload", FAKE, workload="not_a_process")


def test_gateway_receives_exactly_what_it_consumes():
    env = railway.env_for_role("gateway", FAKE)
    assert set(env) == {
        "LITELLM_MASTER_KEY", "LITELLM_MCP_CLIENT_TIMEOUT", "LITELLM_MCP_TOOL_LISTING_TIMEOUT",
        "DATABASE_URL", "OLLAMA_API_KEY", "ANTHROPIC_UPSTREAM_API_KEY", "MCP_SHARED_SECRET",
        "EMBED_URL", "PG_VECTOR_API_BASE", "PG_VECTOR_API_KEY",
        "ADOIT_MCP_URL", "SEMANTIC_MCP_URL", "STORAGE_MCP_URL", "GRAPH_MCP_URL", "REFERENCE_MCP_URL",
        "REDIS_URL",
        "OTEL_EXPORTER", "OTEL_ENDPOINT", "OTEL_SERVICE_NAME", "OTEL_EXPORTER_OTLP_ENDPOINT",
        "ENTRA_TENANT_ID", "ENTRA_GATEWAY_AUDIENCE", "ENTRA_CLIENT_TO_KEY", "DEVELOPERS_TEAM_ID",
        "MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET", "MICROSOFT_TENANT", "PROXY_BASE_URL",
    }
    # REDIS_HOST/PORT/PASSWORD stay out on purpose (litellm falls back to REDIS_URL — verified);
    # the ADOIT credentials never reach the gateway (only the adoit-mcp ADDRESS does).
    assert not _has(env, "REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD", "S3_", "BA_", "ARCHITECT_",
                    "ADOIT_BASE_URL", "ADOIT_USERNAME", "ADOIT_PASSWORD", "ADOIT_REPO_ID", "ADOIT_REST_WRITE")
    # the gateway learns the collaboration server's ADDRESS, never the credential behind it
    assert "GRAPH_CLIENT_SECRET" not in env and "GRAPH_CLIENT_ID" not in env


def test_adoit_mcp_receives_exactly_what_it_consumes():
    env = railway.env_for_role("adoit-mcp", FAKE)
    assert set(env) == {
        "ADOIT_BASE_URL", "ADOIT_USERNAME", "ADOIT_PASSWORD", "ADOIT_REPO_ID", "ADOIT_REST_WRITE",
        "MCP_SHARED_SECRET", "BIND_HOST", "REDIS_URL", "ARTIFACTS_URL", "DATABASE_URL",
        "REVIEW_APP_URL", "OTEL_EXPORTER_OTLP_ENDPOINT",
    }


def test_the_front_door_holds_redis_and_two_links_and_no_store():
    """The role that carries the process tools AND the approval gate: Redis is its ONLY backend, and
    the two URLs are addresses a reviewer follows — never a store or bucket credential."""
    env = railway.env_for_role("workflow-frontdoor", FAKE)
    assert set(env) == {"MCP_SHARED_SECRET", "BIND_HOST", "REDIS_URL",
                        "REVIEW_APP_URL", "JAEGER_UI_URL", "OTEL_EXPORTER_OTLP_ENDPOINT"}
    assert not _has(env, "ARTIFACTS_URL", "DATABASE_URL", "UPLOADS_URL", "S3_", "ADOIT_", "LITELLM_")


def test_graph_mcp_holds_its_provider_credential_the_bucket_and_nothing_else():
    """The COLLABORATION adapter: its own app-only credential, the upload store it streams fetched
    content into, tracing — and, since the fabric, Redis: its `/notifications` route turns a provider's
    change notification into an `ArtifactChanged` on `fabric:events`. No gateway or model secret, no
    ADOIT credential — and its own secret must not leak to any other role."""
    env = railway.env_for_role("graph-mcp", FAKE, s3=True)
    assert set(env) == {
        "MCP_SHARED_SECRET", "BIND_HOST", "COLLAB_PROVIDER", "ENTRA_TENANT_ID",
        "GRAPH_MCP_URL", "GRAPH_MCP_PORT", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET",
        "GRAPH_AUTH_MODE", "GRAPH_BASE_URL", "GRAPH_MEETING_USER",
        "GRAPH_NOTIFICATION_ALLOWLIST", "GRAPH_ALLOW_METERED",
        "ARTIFACTS_URL", "OTEL_EXPORTER_OTLP_ENDPOINT", "REDIS_URL",
        "S3_ENDPOINT", "S3_REGION", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_URL_STYLE",
        "UPLOADS_URL"}
    # DATABASE_URL is the LiteLLM key/spend store's DSN — the most sensitive secret in the substrate,
    # and this role has no use for it (ARTIFACTS_URL already carries the expanded value it falls back to)
    assert "DATABASE_URL" not in env
    assert not _has(env, "ADOIT_", "LITELLM_", "OLLAMA_", "BA_", "ARCHITECT_", "MICROSOFT_")
    for role in railway.ROLE_ENV:
        if role != "graph-mcp":
            assert "GRAPH_CLIENT_SECRET" not in railway.env_for_role(role, FAKE, s3=True), role


def test_semantic_mcp_is_credential_free():
    """No upstream credential ever: the fabric's index posts to the GATEWAY (a coordinate, and a virtual key
    when one is configured — `REFERENCE_EMBED_KEY`, like reference-mcp), never to a model provider."""
    env = railway.env_for_role("semantic-mcp", FAKE)
    assert set(env) == {"MCP_SHARED_SECRET", "BIND_HOST", "ARTIFACTS_URL", "DATABASE_URL",
                        "OTEL_EXPORTER_OTLP_ENDPOINT", "GATEWAY_URL"}
    assert not _has(env, "ADOIT_", "LITELLM_", "OLLAMA_", "ANTHROPIC_", "GRAPH_", "ENTRA_")


def test_storage_mcp_and_review_s3_gating():
    s3 = {"S3_ENDPOINT", "S3_REGION", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_URL_STYLE", "UPLOADS_URL"}
    assert set(railway.S3_KEYS) == s3
    st = railway.env_for_role("storage-mcp", FAKE, s3=True)
    assert set(st) == s3 | {"MCP_SHARED_SECRET", "BIND_HOST", "ARTIFACTS_URL", "DATABASE_URL",
                            "BA_MAX_DOC_CHARS", "OTEL_EXPORTER_OTLP_ENDPOINT"}
    assert not (set(railway.env_for_role("storage-mcp", FAKE, s3=False)) & s3)   # flag off -> none
    rv = railway.env_for_role("review", FAKE, s3=True)
    assert set(rv) == s3 | {"REVIEW_APP_PASSWORD", "REDIS_URL", "ARTIFACTS_URL", "DATABASE_URL", "JAEGER_UI_URL",
                            "REFERENCE_PROVIDER", "REFERENCE_MCP_URL", "REFERENCE_RING", "MCP_SHARED_SECRET"}
    assert "RAILWAY_BUCKET_ID" not in rv
    # the SUBSTRATE table itself: only services flagged s3 can ever see the bucket credentials
    for name, spec in railway.SUBSTRATE.items():
        got = set(railway.env_for_role(name, FAKE, s3=spec.get("s3"))) & s3
        assert (got == s3) if spec.get("s3") else (not got), name
    # no ROLE_ENV pattern may grant S3 keys on its own (the flag is the only route)
    for role, pats in railway.ROLE_ENV.items():
        assert not (set(railway.env_for_role(role, FAKE, s3=False)) & s3), role


def test_a_channel_receives_only_its_own_settings_and_the_links_it_shows_a_human():
    """An approval channel notifies a human and records the decision — nothing else. So: its own
    credential, Redis (the approvals streams), the link(s) it puts in front of the reviewer, and the
    tracing sink. No store, no bucket, no gateway/model/ADOIT secret — and not the OTHER channel's
    credential either."""
    tg = railway.env_for_role("telegram", FAKE)
    assert set(tg) == {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "REDIS_URL", "REVIEW_APP_URL",
                       "OTEL_EXPORTER_OTLP_ENDPOINT"}
    tm = railway.env_for_role("teams", FAKE)
    assert set(tm) == {"TEAMS_WEBHOOK_URL", "REDIS_URL", "REVIEW_APP_URL", "JAEGER_UI_URL",
                       "OTEL_EXPORTER_OTLP_ENDPOINT"}     # + the trace link its card offers
    for role, env in (("telegram", tg), ("teams", tm)):
        assert not _has(env, "DATABASE_URL", "ARTIFACTS_URL", "UPLOADS_URL", "S3_", "ADOIT_", "LITELLM_",
                        "OLLAMA_", "ANTHROPIC_", "MCP_SHARED_SECRET", "BA_", "ARCHITECT_", "ENTRA_",
                        "MICROSOFT_", "GATEWAY_URL", "REVIEW_APP_PASSWORD"), role
    assert "TEAMS_WEBHOOK_URL" not in tg and "TELEGRAM_BOT_TOKEN" not in tm


def test_the_meeting_notifier_gets_redis_and_one_url_and_nothing_else():
    """It reads a finished run's state and POSTs ids, names, links and counts to ONE configured URL.
    It never opens an artifact it announces, never calls the provider and never calls the gateway —
    so it holds no store, no bucket, no Graph credential and no model key. Announcing a result is
    the least privileged thing in the substrate, and its env should show that."""
    env = railway.env_for_role("meeting-notifier", FAKE)
    assert set(env) == {"REDIS_URL", "MEETING_WEBHOOK_URL", "OTEL_EXPORTER_OTLP_ENDPOINT"}
    assert not _has(env, "DATABASE_URL", "ARTIFACTS_URL", "UPLOADS_URL", "S3_", "GRAPH_", "SPEECH_",
                    "ADOIT_", "LITELLM_", "OLLAMA_", "ANTHROPIC_", "MCP_SHARED_SECRET", "ENTRA_",
                    "GATEWAY_URL", "TEAMS_WEBHOOK_URL", "TELEGRAM_")


def test_a_channel_is_a_substrate_service_only_while_it_is_configured():
    """An unconfigured channel exits immediately by design, so it is never deployed (lab.sh skips it
    for the same reason). Partial settings do not count."""
    assert set(railway.CHANNELS) == {"telegram", "teams"}
    assert set(railway.substrate_services({})) == set(railway.SUBSTRATE)
    assert set(railway.substrate_services({"TELEGRAM_BOT_TOKEN": "t"})) == set(railway.SUBSTRATE)
    both = railway.substrate_services(FAKE)
    assert set(both) == set(railway.SUBSTRATE) | {"telegram", "teams"}
    for name, spec in railway.CHANNELS.items():
        assert spec["cmd"] == f"python -m lab.substrate.channels.{name}"
        assert spec["port"] is None and spec["restart"] == "ALWAYS"   # a loop, and nothing calls it
        assert not spec.get("s3")
    # deploy order + what down/status walk: redis first, jaeger last, a channel in between when it is
    # configured OR still deployed (settings removed from .env must not orphan a running service)
    assert railway.substrate_names({}) == ["redis", "embedder"] + list(railway.SUBSTRATE) + ["local-agent-lab"]
    assert railway.substrate_names({}, {"teams": "svc-teams"}) == \
        ["redis", "embedder"] + list(railway.SUBSTRATE) + ["teams", "local-agent-lab"]
    assert railway.substrate_names(FAKE)[-3:] == ["telegram", "teams", "local-agent-lab"]


def test_every_key_a_channel_is_gated_on_is_actually_shipped_to_it():
    """The deploy GATE (`requires`) and the credential GRANT (ROLE_ENV) are two lists of the same
    keys. A channel whose token is required to deploy it but stripped by the allowlist would be
    deployed and then exit immediately — silently, since the "not configured" line never prints."""
    for name, spec in railway.CHANNELS.items():
        granted = railway.env_for_role(name, {k: "x" for k in spec["requires"]})
        assert set(granted) == set(spec["requires"]), name


def test_the_two_runners_agree_on_what_a_channel_is():
    """`lab.sh` (local) and `deploy/railway.py` (cloud) each hold the channel table in their own
    language. A channel that runs locally but is never deployed — or one whose module path or
    required settings drift between them — is a silently unattended approval gate, and no compiler
    spans the two. This is the check that does."""
    sh = open(os.path.join(ROOT, "lab.sh")).read()
    block = sh.split("for_each_channel()", 1)[1].split("\n}", 1)[0]
    rows = re.findall(r'^\s*"\$1"\s+(\S+)\s+(\S+)\s+"([^"]*)"', block, re.M)
    assert rows, "lab.sh no longer declares its channels as a table — the parity check is blind"
    assert {n: (m, tuple(v.split())) for n, m, v in rows} == \
        {n: (s["cmd"].split()[-1], tuple(s["requires"])) for n, s in railway.CHANNELS.items()}
    for name in railway.CHANNELS:                      # start/status/stop all walk the ONE table
        assert f"for_each_channel {name}" not in sh    # (no per-channel call sites)
    assert sh.count("for_each_channel ") >= 3          # start_channel, channel_status, stop_channel


def test_the_two_runners_agree_on_the_always_on_daemons():
    """The same check for the daemons — the channels' unconditional siblings. A daemon that runs
    locally but is never deployed is work silently not being done: an approved question that starts
    no run, or minutes nobody is told about. Both were hand-rolled here twice before there was a
    table to compare, which is precisely why one of them was missing from `lab.sh` entirely."""
    sh = open(os.path.join(ROOT, "lab.sh")).read()
    block = sh.split("for_each_daemon()", 1)[1].split("\n}", 1)[0]
    rows = re.findall(r'^\s*"\$1"\s+(\S+)\s+(\S+)\s+"([^"]*)"', block, re.M)
    assert rows, "lab.sh no longer declares its daemons as a table — the parity check is blind"
    local = {n: m for n, m, _ready in rows}
    cloud = {n: s["cmd"].split()[-1] for n, s in railway.SUBSTRATE.items()
             if n in local or n in ("continuations", "meeting-notifier")}
    assert local == cloud, "a daemon runs in one runner and not the other, or from a different module"
    for name in local:                                # start/down/status all walk the ONE table
        assert f"for_each_daemon {name}" not in sh    # (no per-daemon call sites)
    assert sh.count("for_each_daemon ") >= 3          # start_daemon, daemon_status, stop_daemon


def test_down_stops_every_workload_not_just_the_first_one():
    """`down` walks the workload table. It used to hold a hand-typed service list beside a `pkill`
    that named ONE workload module by hand, so the other two consumers survived a `down` as orphans
    still reading `workflow:requests`."""
    sh = open(os.path.join(ROOT, "lab.sh")).read()
    down = sh.split("\ndown() {", 1)[1].split("\n}", 1)[0]
    assert "for_each_workload stop_workload" in down and "for_each_daemon stop_daemon" in down
    for module in (s["cmd"].split()[-1] for s in railway.WORKLOADS.values()):
        assert module not in down, f"{module} is named by hand in down() instead of coming from the table"


def test_no_role_receives_management_or_unknown_keys():
    for role in railway.ROLE_ENV:
        env = railway.env_for_role(role, FAKE)
        assert not (set(env) & MANAGEMENT), role
        for k in ("ENTRA_GATEWAY_APP_ID", "DEV_CLIENT_ID", "VISIO_TEAM_ID", "ARCHIMATE_SKILL_ID",
                  "VISIO_READER_SKILL_ID", "EA_AGENT_KEY", "EA_AGENT_CLIENT_SECRET"):
            assert k not in env, (role, k)
    for third_party in ("redis", "jaeger", "embedder"):
        assert railway.env_for_role(third_party, FAKE) == {}, third_party
    assert set(railway.ROLE_ENV) >= set(railway.SUBSTRATE) | {"workload", "redis", "jaeger", "embedder"}


def test_unknown_role_rejected():
    try:
        railway.env_for_role("nope", FAKE)
        assert False, "unknown role accepted"
    except KeyError:
        pass


# ---------------------------------------------------------------- e2e_smoke env reader
def test_e2e_smoke_reader_reuses_parser():
    p = _tmp_env()
    for k in ("ARTIFACTS_URL", "GATEWAY_URL", "NOTED", "E2E_ENV_PROFILE"):
        os.environ.pop(k, None)
    smoke = _load("lab_e2e_smoke", "scripts/e2e_smoke.py")     # import must NOT run the checks
    env = smoke._load_env(p)
    assert env["ARTIFACTS_URL"] == "postgresql://neon/db"        # $VAR expanded
    assert env["NOTED"] == "value"                               # note stripped
    assert env["GATEWAY_URL"] == "http://127.0.0.1:4000"         # default profile = local values
    os.environ["E2E_ENV_PROFILE"] = "cloud"
    try:
        assert smoke._load_env(p)["GATEWAY_URL"] == "https://gw.example"
    finally:
        del os.environ["E2E_ENV_PROFILE"]
    os.environ["GATEWAY_URL"] = "http://override:1"
    try:
        assert smoke._load_env(p)["GATEWAY_URL"] == "http://override:1"   # process env wins
    finally:
        del os.environ["GATEWAY_URL"]
    assert not hasattr(smoke, "redisok")                         # dead name gone (B-M6)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ---------------------------------------------------------------- /api authorisation in the cloud
def test_the_gateway_role_carries_what_api_authorisation_needs():
    """The REST front door's per-operation role check runs in the GATEWAY process
    (lab.substrate.gateway.custom_auth against lab.substrate.apipolicy), not in the front door — the
    pass-through replaces the caller's Authorization, so identity does not survive the hop. That makes
    these three settings load-bearing for /api and not only for agent authentication: without them
    `_validate` cannot verify a token, and every /api call fails closed. Failing closed is correct,
    but a silently broken connector is not, so pin the allowlist."""
    gw = set(railway.ROLE_ENV["gateway"])
    assert {"ENTRA_TENANT_ID", "ENTRA_GATEWAY_AUDIENCE", "ENTRA_CLIENT_TO_KEY"} <= gw
    assert "WORKFLOW_API_URL" in gw, "the pass-through target"


def test_no_other_role_is_handed_the_app_to_key_mapping():
    """ENTRA_CLIENT_TO_KEY pairs every app registration with its virtual key. Only the process that
    validates tokens needs it; anywhere else it is a list of live credentials."""
    for role, keys in railway.ROLE_ENV.items():
        if role != "gateway":
            assert "ENTRA_CLIENT_TO_KEY" not in set(keys), role


# ------------------------------------------------------- the lanes must survive the deploy
def test_speech_mcp_receives_every_provider_credential_it_can_be_asked_to_build():
    """The failure this prevents reports SUCCESS while doing nothing.

    `configure()` strips whatever a role's allowlist does not name. speech-mcp can be asked for ANY
    registered provider — that is what a lane is — so a credential missing from this list does not
    error: the adapter reports `SpeechNotConfigured`, the lane is SKIPPED by name, and a
    four-provider comparison quietly returns one provider's answer while every service reports
    healthy. Exactly the declared-but-never-applied class the image tag and the team grants both
    belonged to.

    Derived from the registry rather than listed here, so a fifth provider cannot be added without
    its key reaching the one service that needs it.
    """
    from lab.substrate import container
    allowed = railway.ROLE_ENV["speech-mcp"]
    for provider in container.SPEECH_PROVIDERS:
        setting = provider.split("-")[0].upper()          # soniox-en is served by SONIOX_*
        assert any(p.rstrip("*") == f"{setting}_" or p == f"{setting}_API_KEY" for p in allowed), \
            f"speech-mcp may be asked for {provider!r} but {setting}_* is stripped from its env"


def test_the_front_door_is_told_which_lanes_to_fan_out_into():
    """`workflows.lanes_for` reads SPEECH_LANES, and the fan-out happens in the front door — both
    its REST route and its MCP submit. Strip the setting and every meeting silently runs ONE lane,
    which looks exactly like a working single-provider deployment."""
    assert "SPEECH_LANES" in railway.ROLE_ENV["workflow-frontdoor"]


def test_a_workload_still_receives_no_provider_credential_of_any_kind():
    """A lane is chosen by NAME and served by the substrate. No workload may hold a vendor key —
    adding three providers must not have widened that."""
    for workload in ("meeting", "minutes"):
        env = railway.env_for_role("workload", FAKE, workload=workload)
        for leaked in ("MUNSIT_API_KEY", "ELEVENLABS_API_KEY", "ASSEMBLYAI_API_KEY",
                       "SONIOX_API_KEY"):
            assert leaked not in env, f"the {workload} workload must never hold {leaked}"


# ------------------------------------------------- what CD deploys, and where that list comes from

def test_ci_derives_the_workload_list_rather_than_carrying_its_own():
    """A new business process used to ship its substrate on push and its HOST only when somebody
    remembered to edit the workflow file — a second place declaring what `WORKLOADS` declares."""
    ci = open(os.path.join(ROOT, ".github", "workflows", "image.yml")).read()
    assert "workload list" in ci, "CD must ask the deploy CLI which workloads exist"
    assert "for w in visio meeting minutes" not in ci, "a hardcoded list is the drift itself"


def test_workload_list_names_every_long_lived_host_and_no_one_shot_job():
    listed = sorted(n for n, w in railway.WORKLOADS.items() if w.get("restart") == "ALWAYS")
    # Every use-case host is deployable by CD, which is the point of this change.
    assert {"usecase-screening", "usecase-design", "usecase-investment",
            "usecase-provisioning"} <= set(listed)
    # ... and a one-shot job is not run on every push, because that is not a deployment.
    one_shot = [n for n, w in railway.WORKLOADS.items() if w.get("restart") != "ALWAYS"]
    assert not (set(one_shot) & set(listed)), one_shot


def test_listing_the_workloads_needs_no_railway_credential():
    """CD must be able to ask what it should deploy without first holding the token that deploys."""
    source = open(os.path.join(ROOT, "deploy", "railway.py")).read()
    assert "offline = cmd ==" in source and '"list"' in source


def test_the_signing_seed_and_the_publish_dsn_reach_no_container():
    """`REFERENCE_*` as a glob would match both. Neither is in `.env` today, so the private seed
    staying out of every container rested on nobody adding a line — which is the shape of guarantee
    this file exists to replace."""
    never = ("REFERENCE_SIGNING_KEY", "REFERENCE_PUBLISH_DB_URL")
    for role, allowed in railway.ROLE_ENV.items():
        for secret in never:
            assert not any(secret == a or (a.endswith("*") and secret.startswith(a[:-1]))
                           for a in allowed), f"{role} would receive {secret}"


def test_only_the_corpus_server_receives_the_reader_dsn():
    """A reader dsn is a credential. decision-mcp reads the corpus THROUGH the gateway and has no
    business holding one."""
    for role, allowed in railway.ROLE_ENV.items():
        if role == "reference-mcp":
            continue
        assert "REFERENCE_DB_URL" not in allowed, role


def test_the_gateway_is_pointed_at_the_corpus_facade_with_the_shared_secret():
    """The vector_store_registry's provider reads PG_VECTOR_API_BASE / PG_VECTOR_API_KEY from the
    gateway's process env (LiteLLM resolves no os.environ/ on that path). Derived here from the
    reference-mcp address and MCP_SHARED_SECRET — never a second secret to rotate."""
    env = railway.substrate_env("gateway", railway.SUBSTRATE["gateway"],
                                {**FAKE, "MCP_SHARED_SECRET": "shh"})
    assert env["PG_VECTOR_API_BASE"] == "http://reference-mcp.railway.internal:9700"
    assert env["PG_VECTOR_API_KEY"] == "shh"
    assert "/v1/" not in env["PG_VECTOR_API_BASE"], "an ORIGIN — the client appends the path"


def test_the_gateway_reaches_the_substrate_s_own_embedder_over_the_private_network():
    """The embedding model is a third-party image service beside Redis: internal only, no
    credential, and the gateway's model_list resolves its address from EMBED_URL."""
    env = railway.substrate_env("gateway", railway.SUBSTRATE["gateway"], FAKE)
    assert env["EMBED_URL"] == "http://embedder.railway.internal:11434"
    assert railway.EMBED_NAME == "embedder" and railway.EMBED_IMAGE.startswith("ollama/ollama:")
    assert "[::]" in railway.EMBED_CMD, "Railway private DNS is IPv6-only: the model must bind ::"
    assert railway.EMBED_MODEL in railway.EMBED_CMD, "the model is pulled at start, onto the volume"
    assert railway.EMBED_NAME in railway.substrate_names(FAKE)


def test_the_derivation_servers_read_the_corpus_through_reference_mcp_and_hold_no_dsn():
    """A pure derivation holds no reader credential; its provider is `mcp`, its address the corpus
    server's, its bearer the substrate's shared secret."""
    for role in ("decision-mcp", "valuation-mcp", "review"):
        env = railway.substrate_env(role, railway.SUBSTRATE[role], FAKE)
        assert env["REFERENCE_PROVIDER"] == "mcp", role
        assert env["REFERENCE_MCP_URL"].startswith("http://reference-mcp.railway.internal")
        assert "REFERENCE_DB_URL" not in env, role
        if role != "review":                       # review holds the LiteLLM DSN for artifacts, not the corpus
            assert "DATABASE_URL" not in env, role


def test_the_embedder_serves_a_query_beside_a_publish_batch_not_behind_it():
    """ollama serialises requests by default: during the v0.28 publish every live relevance query
    queued behind a 32-text batch (~90 s) and the matcher's search timed out (11 Sep 2026)."""
    assert "OLLAMA_NUM_PARALLEL=4" in railway.EMBED_CMD
