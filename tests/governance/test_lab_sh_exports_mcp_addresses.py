"""Every gateway-registered MCP server's address must be EXPORTED by lab.sh.

This exists because of a real failure caught only by a live call. `config/litellm-config.yaml`
resolves each server's url through `os.environ/<NAME>_MCP_URL`. A default in `lab.platform.config`
does NOT help the gateway: LiteLLM reads the PROCESS environment, so a name that lab.sh never
exports resolves to nothing and the gateway silently publishes ZERO tools for that server. It looks
exactly like a missing grant, which is the most expensive way to misdiagnose it — CLAUDE.md records
the same trap costing a debugging session once already.

Offline and text-only: it reads lab.sh and the gateway config, exactly as the channel parity test
reads lab.sh's own table.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAB_SH = os.path.join(ROOT, "lab.sh")
CONFIG = os.path.join(ROOT, "config", "litellm-config.yaml")


def _registered_env_names() -> set[str]:
    """Every address the gateway config dereferences — for an MCP server OR a pass-through route.

    Both are the same trap: a name the gateway resolves from the PROCESS environment. Miss one and
    the server silently publishes nothing, or the route 502s, and in both cases it looks like a
    grant problem rather than a missing variable.
    """
    text = open(CONFIG, encoding="utf-8").read()
    return set(re.findall(r"os\.environ/([A-Z0-9_]+_(?:MCP|API)_URL)", text))


def _exported_names() -> set[str]:
    """Every address lab.sh puts into the process environment. Same pattern as the registered side —
    they must widen together, or the test passes while the gap it exists to catch is real."""
    text = open(LAB_SH, encoding="utf-8").read()
    return set(re.findall(r"([A-Z0-9_]+_(?:MCP|API)_URL)=", text))


def test_every_registered_mcp_server_address_is_exported_by_lab_sh():
    registered, exported = _registered_env_names(), _exported_names()
    assert registered, "no gateway-dereferenced addresses found — the parser is wrong"
    missing = sorted(registered - exported)
    assert not missing, (
        f"{missing} are dereferenced by config/litellm-config.yaml but never exported by lab.sh. "
        "The gateway reads the PROCESS environment, so an MCP server publishes ZERO tools and a "
        "pass-through route fails — both of which look like a grant problem rather than a missing "
        "variable. Add it to lab.sh's export line.")


def test_the_gateway_role_receives_every_registered_address_in_the_cloud():
    """The same invariant on the deployed side: `deploy/railway.py` must hand the gateway role every
    address it dereferences, or the cloud gateway publishes zero tools for that server."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("railway", os.path.join(ROOT, "deploy", "railway.py"))
    railway = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(railway)
    allowed = railway.ROLE_ENV["gateway"]
    missing = [n for n in sorted(_registered_env_names())
               if not any(n == a or (a.endswith("*") and n.startswith(a[:-1])) for a in allowed)]
    assert not missing, f"{missing} are not in ROLE_ENV['gateway'] — the cloud gateway cannot resolve them"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
