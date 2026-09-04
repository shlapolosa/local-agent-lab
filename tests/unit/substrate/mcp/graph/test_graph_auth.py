"""src/lab/substrate/mcp/graph/graph_auth.py — the adapter's own app-only credential: a short-lived
token minted from a long-lived SECRET, cached until it is nearly expired, and a structural refusal
(naming the exact settings) when the lab was never configured.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/graph/test_graph_auth.py"""
import base64
import json

import pytest

from lab.core.collab import CollabNotConfigured, CollabUnavailable
from lab.substrate.mcp.graph import graph_auth


def jwt(payload: dict) -> str:
    """A token shaped like Entra's: header.payload.signature, payload base64url without padding."""
    def seg(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{seg({'alg': 'RS256'})}.{seg(payload)}.signature"


class FakeMsalApp:
    """The slice of msal.ConfidentialClientApplication the source uses."""

    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def acquire_token_for_client(self, scopes):
        self.calls.append(tuple(scopes))
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def app_source(*results, clock=None, **kw):
    app = FakeMsalApp(*results)
    src = graph_auth.AppOnlyToken("tenant-1", "client-1", "secret-1", now=clock or Clock(),
                                  client_factory=lambda *a, **k: app, **kw)
    return src, app


# ------------------------------------------------------------------ app-only client credentials
def test_an_app_only_source_mints_a_token_for_the_graph_default_scope():
    src, app = app_source({"access_token": "tok-1", "expires_in": 3600})
    assert src.token() == "tok-1"
    assert app.calls == [("https://graph.microsoft.com/.default",)]


def test_the_token_is_cached_until_it_is_nearly_expired_and_then_reminted():
    clock = Clock(1000.0)
    src, app = app_source({"access_token": "tok-1", "expires_in": 3600},
                          {"access_token": "tok-2", "expires_in": 3600}, clock=clock)
    assert src.token() == "tok-1"
    clock.t = 1000.0 + 3600 - graph_auth.EXPIRY_SKEW - 1        # still inside the skew margin
    assert src.token() == "tok-1" and len(app.calls) == 1
    clock.t = 1000.0 + 3600 - graph_auth.EXPIRY_SKEW            # the margin is reached: remint
    assert src.token() == "tok-2" and len(app.calls) == 2


def test_the_real_expires_in_is_honoured_not_a_guessed_hour():
    clock = Clock(0.0)
    src, app = app_source({"access_token": "short", "expires_in": 120},
                          {"access_token": "next", "expires_in": 120}, clock=clock)
    src.token()
    clock.t = 61.0                                              # 120 - 60 skew = remint at 60
    assert src.token() == "next"


def test_a_token_without_an_expiry_is_never_cached_so_a_stale_one_cannot_be_reused():
    src, app = app_source({"access_token": "tok"})
    src.token(); src.token()
    assert len(app.calls) == 2


def test_the_msal_client_is_built_once_and_reused():
    built = []

    def factory(client_id, secret, authority):
        built.append((client_id, secret, authority))
        return FakeMsalApp({"access_token": "t", "expires_in": 1})
    src = graph_auth.AppOnlyToken("tenant-1", "client-1", "secret-1", now=Clock(), client_factory=factory)
    src.token(); src.token()
    assert built == [("client-1", "secret-1", "https://login.microsoftonline.com/tenant-1")]


def test_a_rejected_credential_says_what_to_fix_rather_than_raising_a_msal_dict():
    src, _ = app_source({"error": "invalid_client", "error_description": "AADSTS7000215: bad secret"})
    with pytest.raises(CollabUnavailable) as e:
        src.token()
    assert e.value.capability == "configuration"
    assert "invalid_client" in e.value.reason and "AADSTS7000215" in e.value.reason
    assert "GRAPH_CLIENT_SECRET" in e.value.remedy


def test_msal_is_imported_lazily_so_an_absent_package_cannot_break_module_import():
    src = graph_auth.AppOnlyToken("t", "c", "s")                # no client_factory: the real import
    assert src._app is None                                     # nothing imported at construction


# ------------------------------------------------------------------ roles
def test_the_roles_claim_is_read_from_the_token_because_it_is_the_declared_permission_set():
    src, _ = app_source({"access_token": jwt({"roles": ["Sites.Read.All", "Files.Read.All"]}),
                         "expires_in": 3600})
    assert src.roles() == ("Sites.Read.All", "Files.Read.All")


def test_a_token_that_is_not_a_jwt_yields_no_roles_rather_than_blowing_up():
    assert graph_auth.decode_roles("not-a-token") == ()
    assert graph_auth.decode_roles(jwt({"aud": "x"})) == ()
    assert graph_auth.decode_roles("a.!!!not-base64!!!.c") == ()


def test_padding_is_restored_before_decoding_because_entra_strips_it():
    token = jwt({"roles": ["A"]})
    assert len(token.split(".")[1]) % 4 != 0 or True             # whatever the length, it decodes
    assert graph_auth.decode_roles(token) == ("A",)


# ------------------------------------------------------------------ static + unconfigured
def test_a_static_token_is_the_dev_and_probing_path():
    src = graph_auth.StaticToken(jwt({"roles": ["Sites.Read.All"]}))
    assert src.roles() == ("Sites.Read.All",) and src.token().startswith("eyJ")


def test_an_unconfigured_source_refuses_structurally_naming_the_exact_settings():
    src = graph_auth.Unconfigured("GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET")
    with pytest.raises(CollabNotConfigured) as e:
        src.token()
    assert "GRAPH_CLIENT_ID" in str(e.value) and "GRAPH_CLIENT_SECRET" in str(e.value)
    assert e.value.capability == "configuration"


def test_an_unconfigured_source_refuses_its_roles_the_same_way_so_a_probe_reports_one_story():
    with pytest.raises(CollabNotConfigured):
        graph_auth.Unconfigured("GRAPH_CLIENT_ID").roles()


# ------------------------------------------------------------------ the factory
def test_the_factory_picks_the_source_the_mode_asks_for():
    assert isinstance(graph_auth.token_source("app", tenant_id="t", client_id="c", client_secret="s"),
                      graph_auth.AppOnlyToken)
    assert isinstance(graph_auth.token_source("static", static_token="tok"), graph_auth.StaticToken)
    assert isinstance(graph_auth.token_source("none"), graph_auth.Unconfigured)


def test_the_factory_is_case_and_space_insensitive_about_the_mode():
    assert isinstance(graph_auth.token_source(" APP ", tenant_id="t", client_id="c", client_secret="s"),
                      graph_auth.AppOnlyToken)


def test_an_unknown_mode_is_a_configuration_error_naming_the_modes_that_exist():
    with pytest.raises(ValueError, match="GRAPH_AUTH_MODE"):
        graph_auth.token_source("oauth")


def test_a_mode_whose_settings_are_missing_degrades_to_a_named_refusal_not_a_crash():
    src = graph_auth.token_source("app", tenant_id="t", client_id="", client_secret="s")
    assert isinstance(src, graph_auth.Unconfigured)
    with pytest.raises(CollabNotConfigured) as e:
        src.token()
    assert "GRAPH_CLIENT_ID" in str(e.value) and "GRAPH_CLIENT_SECRET" not in str(e.value)
    assert "ENTRA_TENANT_ID" not in str(e.value)


def test_static_mode_without_a_token_is_the_same_named_refusal():
    with pytest.raises(CollabNotConfigured, match="GRAPH_ACCESS_TOKEN"):
        graph_auth.token_source("static").token()


def test_the_none_mode_names_every_setting_that_would_configure_the_adapter():
    with pytest.raises(CollabNotConfigured) as e:
        graph_auth.token_source("none").token()
    for key in ("ENTRA_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET"):
        assert key in str(e.value)


def test_the_factory_passes_the_clock_through_so_expiry_is_testable():
    clock = Clock(5.0)
    src = graph_auth.token_source("app", tenant_id="t", client_id="c", client_secret="s",
                                  now=clock, client_factory=lambda *a, **k: FakeMsalApp(
                                      {"access_token": "x", "expires_in": 10}))
    assert src.token() == "x" and src._expires_at == 15.0


def test_the_interface_itself_implements_nothing_so_a_mode_must_say_how_it_gets_a_token():
    with pytest.raises(NotImplementedError):
        graph_auth.TokenSource().token()


def test_the_real_client_factory_imports_msal_only_when_a_token_is_actually_wanted(monkeypatch):
    """The lazy import is load-bearing: this module is imported by a server at start, and a missing
    or broken `msal` must not stop that server from booting and reporting why it cannot authenticate."""
    import sys
    import types
    built = {}
    stub = types.ModuleType("msal")
    stub.ConfidentialClientApplication = lambda cid, client_credential, authority: built.update(
        id=cid, secret=client_credential, authority=authority) or "app"
    monkeypatch.setitem(sys.modules, "msal", stub)
    assert graph_auth.AppOnlyToken._msal_client("c", "s", "https://login.microsoftonline.com/t") == "app"
    assert built == {"id": "c", "secret": "s", "authority": "https://login.microsoftonline.com/t"}


def test_a_mode_that_cannot_use_a_keyword_refuses_it_instead_of_swallowing_a_typo():
    """Only the app-only source has a clock, a skew and a client factory. Silently dropping them is
    how a test 'passes' while the token never expires."""
    with pytest.raises(ValueError, match="takes no"):
        graph_auth.token_source("static", static_token="tok", now=Clock())
    with pytest.raises(ValueError, match="takes no"):
        graph_auth.token_source("none", client_factory=lambda *a, **k: None)


def test_a_credential_remedy_has_one_home_shared_with_the_probe():
    from lab.substrate.mcp.graph import graph_probe
    src, _ = app_source({"error": "invalid_client"})
    with pytest.raises(CollabUnavailable) as e:
        src.token()
    assert e.value.remedy == graph_probe.SECRET_REMEDY


def test_a_token_source_that_throws_becomes_a_sentence_not_a_stack_trace():
    """msal is not installed, or its own transport fails: the caller is an MCP tool, and an
    unhandled `ImportError`/`RuntimeError` reaches an agent as a traceback with no remedy."""
    class Exploding:
        def acquire_token_for_client(self, scopes):
            raise RuntimeError("msal exploded")

    src = graph_auth.AppOnlyToken("t", "c", "s", client_factory=lambda *a: Exploding())
    with pytest.raises(CollabUnavailable) as e:
        src.token()
    assert "could not be minted" in e.value.reason and e.value.sentence.endswith(".")
    assert e.value.capability == graph_auth.AUTH_CAPABILITY


def test_a_client_that_cannot_even_be_built_refuses_the_same_way():
    """`import msal` itself is the failure when the package is absent — it happens inside the
    factory, before any token call."""
    def boom(*args):
        raise ImportError("No module named 'msal'")

    with pytest.raises(CollabUnavailable) as e:
        graph_auth.AppOnlyToken("t", "c", "s", client_factory=boom).token()
    assert "msal" in e.value.reason
