"""Binding a substrate service to the network.

`refuse_open` is the lab's loudest small guard: a service that binds past loopback with no credential
is ungoverned, and that must fail at START rather than serve. It had no test of its own until the
fabric app made its meaning load-bearing — the guard asserts "I bind open AND I check a bearer", so a
service that checks a DIFFERENT credential must be able to say which, or the guard passes on a secret
nobody enforces.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/test_netbind.py
"""
import pytest

from lab.platform import config
from lab.substrate import netbind


@pytest.fixture
def bound(monkeypatch):
    def set(host, secret="", *, attr="MCP_SHARED_SECRET"):
        monkeypatch.setattr(config, "BIND_HOST", host)
        monkeypatch.setattr(config, attr, secret, raising=False)
    return set


@pytest.mark.parametrize("host", netbind.LOOPBACK)
def test_a_loopback_service_needs_no_credential(bound, host):
    bound(host)
    netbind.refuse_open("svc")


def test_an_open_service_with_no_credential_refuses_to_start(bound):
    bound("0.0.0.0")
    with pytest.raises(SystemExit) as refusal:
        netbind.refuse_open("svc")
    assert "svc" in str(refusal.value) and "MCP_SHARED_SECRET" in str(refusal.value)


def test_an_open_service_that_holds_the_shared_secret_starts(bound):
    bound("0.0.0.0", "shh")
    netbind.refuse_open("svc")


def test_a_service_may_name_the_credential_it_actually_enforces(bound):
    """The fabric app checks its OWN key, so the shared secret being present says nothing about
    whether that app is gated — and it must still refuse when its own key is missing."""
    bound("0.0.0.0", "shh")
    with pytest.raises(SystemExit) as refusal:
        netbind.refuse_open("fabric-app", credential="", credential_name="FABRIC_APP_KEY")
    assert "FABRIC_APP_KEY" in str(refusal.value)
    netbind.refuse_open("fabric-app", credential="its-own", credential_name="FABRIC_APP_KEY")
