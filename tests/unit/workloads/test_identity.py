"""Offline tests for src/lab/workloads/identity.py — agent_headers(prefix): MSAL client-credentials (an Entra
JWT) when <PREFIX>_CLIENT_ID/SECRET are set, else the durable virtual key <PREFIX>_KEY.
`msal.ConfidentialClientApplication` is a recording fake; env values are set here — never read
from the real .env.

Run: `.venv/bin/python tests/unit/workloads/test_identity.py`  (also pytest-compatible).
"""
import os


import msal  # (installed; only its class is faked)

from lab.workloads import identity

TENANT, AUD = "tenant-fake-0001", "api://lab-gateway-fake/"


class FakeApp:
    instances = []

    def __init__(self, client_id, client_credential=None, authority=None, **kw):
        self.client_id, self.secret, self.authority = client_id, client_credential, authority
        self.calls, self.result = [], {"access_token": f"jwt-for-{client_id}"}
        FakeApp.instances.append(self)

    def acquire_token_for_client(self, scopes):
        self.calls.append(scopes)
        return self.result


def _env(**pairs):
    """Set the prefix credentials for a test (None = unset); returns a restore function."""
    saved = {k: os.environ.get(k) for k in pairs}
    for k, v in pairs.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    def restore():
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return restore


def _setup():
    identity._apps.clear()
    FakeApp.instances.clear()
    real = msal.ConfidentialClientApplication
    msal.ConfidentialClientApplication = FakeApp
    return lambda: setattr(msal, "ConfidentialClientApplication", real)


def test_fallback_to_durable_key_without_client_credentials():
    undo_msal = _setup()
    restore = _env(EA_AGENT_CLIENT_ID=None, EA_AGENT_CLIENT_SECRET=None, EA_AGENT_KEY="sk-ea-durable",
                   BA_AGENT_CLIENT_ID="only-id-no-secret", BA_AGENT_CLIENT_SECRET=None, BA_AGENT_KEY="sk-ba")
    try:
        assert identity.agent_token() is None
        assert identity.agent_headers() == {"Authorization": "Bearer sk-ea-durable"}
        assert identity.agent_token("BA_AGENT") is None                 # id without secret = no MSAL
        assert identity.agent_headers("BA_AGENT") == {"Authorization": "Bearer sk-ba"}
        assert FakeApp.instances == []                                  # MSAL never touched
    finally:
        restore()
        undo_msal()


def test_msal_client_credentials_path_and_app_cache():
    undo_msal = _setup()
    restore = _env(ENTRA_TENANT_ID=TENANT, ENTRA_GATEWAY_AUDIENCE=AUD,
                   ARCHITECT_AGENT_CLIENT_ID="arch-client", ARCHITECT_AGENT_CLIENT_SECRET="arch-secret",
                   ARCHITECT_AGENT_KEY="sk-arch-durable")
    try:
        h = identity.agent_headers("ARCHITECT_AGENT")
        assert h == {"Authorization": "Bearer jwt-for-arch-client"}     # the JWT, not the durable key
        app = FakeApp.instances[0]
        assert app.client_id == "arch-client" and app.secret == "arch-secret"
        assert app.authority == f"https://login.microsoftonline.com/{TENANT}"
        assert app.calls == [["api://lab-gateway-fake/.default"]]       # audience rstrip('/') + /.default
        identity.agent_headers("ARCHITECT_AGENT")
        assert len(FakeApp.instances) == 1 and len(app.calls) == 2       # one app per prefix, reused
        assert identity._apps["ARCHITECT_AGENT"] is app
    finally:
        restore()
        undo_msal()


def test_msal_error_raises_runtime_error_with_reason():
    undo_msal = _setup()
    restore = _env(ENTRA_TENANT_ID=TENANT, ENTRA_GATEWAY_AUDIENCE=AUD,
                   BA_AGENT_CLIENT_ID="ba-client", BA_AGENT_CLIENT_SECRET="ba-secret", BA_AGENT_KEY="sk-ba")
    try:
        identity.agent_token("BA_AGENT")                                # builds + caches the app
        FakeApp.instances[0].result = {"error": "invalid_client",
                                       "error_description": "AADSTS7000215: Invalid client secret " * 20}
        try:
            identity.agent_headers("BA_AGENT")
        except RuntimeError as e:
            msg = str(e)
            assert msg.startswith("MSAL: invalid_client: AADSTS7000215")
            assert len(msg) < 260                                       # description truncated to 200
        else:
            raise AssertionError("MSAL failure must raise, never fall back to the durable key")
        FakeApp.instances[0].result = {}                                # no token, no error fields
        try:
            identity.agent_token("BA_AGENT")
        except RuntimeError as e:
            assert str(e) == "MSAL: None: "
        else:
            raise AssertionError("expected RuntimeError")
    finally:
        restore()
        undo_msal()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
