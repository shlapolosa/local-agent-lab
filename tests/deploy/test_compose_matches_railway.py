"""deploy/substrate/compose.yml is the SAME substrate topology as deploy/railway.py, on a plain Docker
host. It is documented as the portable deployment, so drift makes the docs lie: it had silently lost
workflow-mcp and both approval channels. This test is the ratchet — the same idea as the lab.sh
channel-table parity test. Offline, text-only: no Docker, no Railway."""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COMPOSE = os.path.join(ROOT, "deploy", "substrate", "compose.yml")


def _compose_services():
    """Top-level keys under `services:` — parsed by indentation so no yaml dependency is needed."""
    text = open(COMPOSE, encoding="utf-8").read()
    body = text.split("\nservices:\n", 1)[1]
    out = []
    for line in body.splitlines():
        if line and not line[0].isspace():
            break                                   # a new top-level block (networks:, volumes:)
        m = re.match(r"^  ([a-z][a-z0-9-]*):", line)
        if m:
            out.append(m.group(1))
    return set(out)


def _railway():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_rw", os.path.join(ROOT, "deploy", "railway.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_compose_carries_every_railway_substrate_service():
    rw = _railway()
    compose, railway = _compose_services(), set(rw.SUBSTRATE) | set(rw.CHANNELS) | {"redis", "jaeger"}
    missing = railway - compose
    assert not missing, f"deploy/substrate/compose.yml has drifted — add: {sorted(missing)}"


def test_compose_adds_nothing_railway_does_not_deploy():
    rw = _railway()
    compose, railway = _compose_services(), set(rw.SUBSTRATE) | set(rw.CHANNELS) | {"redis", "jaeger"}
    extra = compose - railway
    assert not extra, f"compose.yml deploys services railway.py does not: {sorted(extra)}"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
