"""TDD: the workflow config contract is built in ONE place (review A-F12 — host and DevUI had drifted:
DevUI lacked `run_id`, both carried a dead `outdir`). Offline: no gateway, no LLM."""


from lab.workloads.visio_to_archimate.workflow import make_cfg
from lab.platform import config

REQUIRED = {"ba_cred", "ar_cred", "traceparent", "ba_headers", "ar_headers", "mcp_url", "schema",
            "tracer", "root_ctx", "run_id"}


def _build(**over):
    base = dict(ba_cred="ba-key", ar_cred="ar-key", traceparent={"traceparent": "00-abc-def-01"},
                schema={"type": "object"}, tracer=object(), root_ctx=None)
    base.update(over)
    return make_cfg(**base)


def test_contract_keys_and_no_dead_keys():
    cfg = _build(run_id="run-1")
    assert set(cfg) == REQUIRED, set(cfg) ^ REQUIRED
    assert "outdir" not in cfg                      # dead key removed (A-F12 / §5)


def test_headers_carry_bearer_and_traceparent():
    cfg = _build()
    assert cfg["ba_headers"]["Authorization"] == "Bearer ba-key"
    assert cfg["ar_headers"]["Authorization"] == "Bearer ar-key"
    assert cfg["ba_headers"]["traceparent"] == "00-abc-def-01"
    assert cfg["ar_headers"]["traceparent"] == "00-abc-def-01"
    assert cfg["traceparent"] is not cfg["ba_headers"]   # headers are copies, not the shared dict


def test_mcp_url_defaults_to_config_and_can_be_overridden():
    assert _build()["mcp_url"] == config.GATEWAY_MCP_URL
    assert _build(mcp_url="http://gw.example/mcp/")["mcp_url"] == "http://gw.example/mcp/"


def test_run_id_is_optional_for_hosts_with_their_own_live_view():
    assert _build()["run_id"] is None                # DevUI: per-session cfg, per-run ids impossible
    assert _build(run_id="abc")["run_id"] == "abc"   # host/consumer: keyed by trace id


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
