"""deploy/topology.py — what runs and with which environment, for EVERY deploy target.

The two targets (Railway = dev, Azure = prod) differ in how a service is ADDRESSED and in which
profile it is configured from; the roles, allowlists and coordinates they compute must not.
"""
import importlib.util
import os
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location("lab_deploy_topology", os.path.join(ROOT, "deploy", "topology.py"))
topology = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(topology)


def _write(text):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "f")
    with open(p, "w") as f:
        f.write(text)
    return p


# ------------------------------------------------------------------ the production overlay
def test_an_overlay_wins_over_the_cloud_profile_and_is_expanded_after_merging():
    base = _write("DATABASE_URL=postgresql://local\n# CLOUD: DATABASE_URL=postgresql://railway\n"
                  "ARTIFACTS_URL=$DATABASE_URL\nKEEP=same\n")
    overlay = _write("DATABASE_URL=postgresql://azure\n")
    env = topology.parse_env(base, cloud=True, overlay=overlay)
    assert env["DATABASE_URL"] == "postgresql://azure"
    assert env["ARTIFACTS_URL"] == "postgresql://azure", "a $ref resolves against the MERGED profile"
    assert env["KEEP"] == "same"


def test_an_empty_overlay_value_removes_a_key_from_the_pool():
    """Prod has no bucket: an overlay line `S3_ENDPOINT=` must take the dev bucket's credential OUT,
    not leave it shipping to prod services."""
    base = _write("# CLOUD: S3_ENDPOINT=https://bucket.railway\nOTHER=x\n")
    overlay = _write("S3_ENDPOINT=\n")
    pool = topology.load_env_for_cloud(base, overlay=overlay)
    assert "S3_ENDPOINT" not in pool and pool["OTHER"] == "x"


def test_no_overlay_is_exactly_the_cloud_profile():
    base = _write("A=1\n# CLOUD: A=2\n")
    assert topology.load_env_for_cloud(base) == topology.load_env_for_cloud(base, overlay=None) == {"A": "2"}


# ------------------------------------------------------------------ coordinates by network
def test_every_server_the_substrate_addresses_has_a_listen_port():
    for name in ("adoit-mcp", "semantic-mcp", "storage-mcp", "workflow-frontdoor", "graph-mcp", "speech-mcp",
                 "reference-mcp", "decision-mcp", "valuation-mcp", "gateway", "review"):
        assert isinstance(topology.SERVICE_PORTS[name], int)
    assert set(topology.SERVICE_PORTS) <= set(topology.SUBSTRATE), "a port for a service nobody deploys"


def test_the_same_role_gets_the_same_keys_on_every_network():
    """Only the VALUES of coordinates differ between targets; which keys a role receives must not."""
    base = {"MCP_SHARED_SECRET": "s", "REDIS_URL": "redis://r", "DATABASE_URL": "pg://x"}
    other = topology.Network(bind_host="0.0.0.0", address=lambda svc, port: f"http://{svc}")
    for name, spec in topology.SUBSTRATE.items():
        a = topology.substrate_env(name, spec, base, topology.RAILWAY_NET)
        b = topology.substrate_env(name, spec, base, other)
        assert set(a) == set(b), name


def test_a_network_decides_how_a_service_is_reached_and_where_it_binds():
    net = topology.Network(bind_host="0.0.0.0", address=lambda svc, port: f"http://{svc}")
    env = topology.substrate_env("gateway", topology.SUBSTRATE["gateway"], {"MCP_SHARED_SECRET": "s"}, net)
    assert env["SEMANTIC_MCP_URL"] == "http://semantic-mcp/mcp"
    assert env["WORKFLOW_API_URL"] == "http://workflow-frontdoor/api"
    assert env["PG_VECTOR_API_BASE"] == "http://reference-mcp", "an ORIGIN: the client appends the path"
    mcp = topology.substrate_env("semantic-mcp", topology.SUBSTRATE["semantic-mcp"], {}, net)
    assert mcp["BIND_HOST"] == "0.0.0.0"


def test_railway_coordinates_are_unchanged_by_the_move():
    env = topology.substrate_env("gateway", topology.SUBSTRATE["gateway"], {"MCP_SHARED_SECRET": "s"},
                                 topology.RAILWAY_NET)
    assert env["SEMANTIC_MCP_URL"] == "http://semantic-mcp.railway.internal:9200/mcp"
    semantic = topology.substrate_env("semantic-mcp", topology.SUBSTRATE["semantic-mcp"], {}, topology.RAILWAY_NET)
    assert semantic["GATEWAY_URL"] == "http://gateway.railway.internal:4000"
    assert env["EMBED_URL"] == "http://embedder.railway.internal:11434"


# ------------------------------------------------------------------ stream consumers
def test_every_long_lived_workload_consumes_the_request_stream_under_its_own_group():
    """The group is the service name — the same value ProcessSpec.group declares (parity-tested in
    tests/governance), which is what a scale rule on the request stream must name."""
    for spec in topology.WORKLOADS.values():
        if spec.get("restart") == "ALWAYS":
            assert topology.workload_group(spec) == spec["service"]
    assert topology.REQUEST_STREAM == "workflow:requests"
