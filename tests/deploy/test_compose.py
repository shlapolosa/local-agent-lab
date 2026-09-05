"""deploy/substrate/compose.yml — the cloud topology on any Docker host.

WHY THIS FILE NEEDS A TEST AT ALL. Nothing else reads it: `lab.sh` runs the stack on one machine and
`deploy/railway.py` deploys it to Railway, so a broken compose file is invisible to every other test
and to every deploy — until someone follows the README and runs `docker compose up`. That is exactly
what happened: a service was added referencing YAML anchors (`*svc`, `*env`) that were never defined,
and because an undefined alias is a COMPOSER error, PyYAML refuses the whole document. Not one
service — every service, including ones untouched for weeks. It shipped in a commit whose tests were
all green.

Two invariants, both cheap:
  1. the document parses (which is what catches an undefined or misspelled anchor);
  2. it describes the SAME topology as `deploy/railway.py`, so the two deployment descriptions of one
     system cannot drift apart silently.
"""
import os
import sys

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COMPOSE = os.path.join(ROOT, "deploy", "substrate", "compose.yml")
sys.path.insert(0, os.path.join(ROOT, "deploy"))
import railway  # noqa: E402

# Provisioned differently on Railway (a managed image service and a volume) but ordinary containers
# here, so they are in compose and not in SUBSTRATE. Named rather than skipped, so adding a third
# third-party dependency is a deliberate edit.
THIRD_PARTY = {"redis", "jaeger"}


@pytest.fixture(scope="module")
def compose():
    """Parsing IS the test for anchors: `<<: *nope` raises ComposerError here, not a warning."""
    with open(COMPOSE) as fh:
        return yaml.safe_load(fh)


def test_the_file_parses_so_every_anchor_it_references_exists(compose):
    assert compose["services"], "a compose file that parses to no services is not a topology"


def test_it_describes_the_same_substrate_as_the_railway_deployer(compose):
    """One system, two deployment descriptions. A service added to one and forgotten in the other is
    a stack that behaves differently depending on where it runs."""
    assert set(compose["services"]) == set(railway.SUBSTRATE) | set(railway.CHANNELS) | THIRD_PARTY


def test_every_lab_service_gets_the_shared_environment(compose):
    """A service that writes its own `environment:` REPLACES the merged one — YAML `<<` does not deep
    merge — so a service needing one extra variable must re-merge `*env`. Forgetting that silently
    drops Redis, the gateway URL and tracing, and the symptom appears at runtime as a service that
    cannot find anything."""
    for name, svc in compose["services"].items():
        if name in THIRD_PARTY:
            continue
        env = svc.get("environment") or {}
        missing = {"REDIS_URL", "REDIS_HOST", "GATEWAY_URL", "BIND_HOST"} - set(env)
        assert not missing, (f"{name} lost {sorted(missing)} — it overrides `environment` without "
                             "re-merging *env, so it falls back to the machine-local .env value, "
                             "which inside a container points at the container itself")


def test_a_service_that_adds_one_variable_still_has_the_shared_ones(compose):
    """The regression that started this file, pinned directly."""
    speech = compose["services"]["speech-mcp"]["environment"]
    assert "AUDIO_EXTRACT_BIN" in speech, "its own extra variable"
    assert speech["REDIS_URL"] and speech["GATEWAY_URL"], "and everything the others get"


def test_every_service_runs_this_repo_s_image_or_is_named_third_party(compose):
    for name, svc in compose["services"].items():
        if name in THIRD_PARTY:
            assert svc.get("image"), f"{name} is third-party and must pin an image"
        else:
            assert svc.get("build") or svc.get("image"), name
