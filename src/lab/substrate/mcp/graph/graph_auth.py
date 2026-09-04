"""The adapter's OWN identity: an app-only Microsoft Graph token, minted from a long-lived secret.

The lab's trust model gives this server its own credential rather than the caller's: the gateway
authenticates to every MCP server with one shared secret, so a server never learns who the caller
was and on-behalf-of is impossible without changing that hop. The consequence is worth stating
plainly — the app registration's permissions are the CEILING for every caller, per-caller narrowing
happens at the gateway with per-team tool permissions, and Graph's own audit shows the application,
not the person.

What is stored is a SECRET, never a token: client credentials mint access tokens that live about an
hour, carry a scope, and stop working when the app is disabled. On Azure this becomes a managed
identity and the secret disappears; that is the migration note, not today's work.

Three modes, chosen by `GRAPH_AUTH_MODE`, all behind one tiny interface (`token()` / `roles()`):

    app      client credentials against `<tenant>/.default` — the real path
    static   a token someone already obtained (`az account get-access-token`) — dev and probing
    none     no credential: every call refuses STRUCTURALLY, naming the exact settings that are
             missing, so an unconfigured lab reports a sentence instead of failing at import

`msal` is imported LAZILY inside the call (as `lab.workloads.identity` does) so importing this
module — which the server does at start — never depends on the package being installed. The token
cache honours the token's REAL `expires_in` with a skew margin, rather than assuming an hour: MSAL
caches too, but the cache is what makes `token()` cheap enough to call on every request, and the
margin is what stops a token expiring in flight.
"""
from __future__ import annotations

import base64
import json
import time
from typing import Callable

from lab.core.collab import CollabNotConfigured, CollabUnavailable
from lab.substrate.mcp.graph.graph_probe import SECRET_REMEDY

__all__ = ["SCOPE", "EXPIRY_SKEW", "AUTH_CAPABILITY", "decode_roles", "TokenSource", "AppOnlyToken",
           "StaticToken", "Unconfigured", "token_source", "MODES"]

SCOPE = "https://graph.microsoft.com/.default"   # app-only: the app's consented permissions, whole
EXPIRY_SKEW = 60.0                               # remint this many seconds early: never expire in flight
AUTH_CAPABILITY = "configuration"                # a credential failure is the lab's own side, not a grant
MODES = ("app", "static", "none")


def decode_roles(token: str) -> tuple[str, ...]:
    """The `roles` claim of an app-only token — the permissions the tenant has actually consented to,
    as the token itself declares them. Read WITHOUT verifying the signature on purpose: this is our
    own token, read to REPORT what we may do, never to authorise anything. Anything unreadable (a
    static token that is not a JWT, an opaque token) yields no roles rather than raising, because a
    capability probe must still render its table."""
    try:
        payload = token.split(".")[1]
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))   # Entra strips padding
        return tuple(json.loads(raw).get("roles") or ())
    except Exception:
        return ()


class TokenSource:
    """The interface every mode implements: a bearer token, and the roles it declares.

    `roles()` lives here once — it is `decode_roles(token())` for every mode, including the
    unconfigured one, where it correctly raises the same refusal `token()` does."""

    def token(self) -> str:
        raise NotImplementedError

    def roles(self) -> tuple[str, ...]:
        return decode_roles(self.token())


class AppOnlyToken(TokenSource):
    """Client credentials: `tenant`/`client_id`/`client_secret` -> a token for `scope`, cached until
    `EXPIRY_SKEW` seconds before the expiry the IdP actually reported.

    `now` and `client_factory` are injected so expiry and failure are testable without a tenant or
    the `msal` package."""

    def __init__(self, tenant_id: str, client_id: str, client_secret: str, scope: str = SCOPE,
                 now: Callable[[], float] = time.time, skew: float = EXPIRY_SKEW,
                 client_factory: Callable[..., object] | None = None) -> None:
        self.tenant_id, self.client_id, self.client_secret = tenant_id, client_id, client_secret
        self.scope, self._now, self._skew = scope, now, skew
        self._factory, self._app = client_factory, None
        self._token, self._expires_at = "", 0.0

    def _client(self):
        if self._app is None:
            factory = self._factory or self._msal_client
            self._app = factory(self.client_id, self.client_secret,
                                f"https://login.microsoftonline.com/{self.tenant_id}")
        return self._app

    @staticmethod
    def _msal_client(client_id, client_secret, authority):
        import msal                                    # lazy: importing this module must not need it
        return msal.ConfidentialClientApplication(client_id, client_credential=client_secret,
                                                  authority=authority)

    def token(self) -> str:
        if self._token and self._now() + self._skew < self._expires_at:
            return self._token
        try:
            result = self._client().acquire_token_for_client(scopes=[self.scope]) or {}
        except Exception as e:
            # `msal` absent (the lazy import fails HERE), or its own transport failing. The caller is
            # an MCP tool, so an unhandled ImportError/URLError would reach an agent as a traceback
            # with no remedy — the one thing this module exists to prevent.
            raise CollabUnavailable(AUTH_CAPABILITY,
                                    f"the app-only credential could not be minted: {e}",
                                    SECRET_REMEDY) from e
        if "access_token" not in result:
            raise CollabUnavailable(
                AUTH_CAPABILITY,
                f"Microsoft Graph refused the app-only credential: "
                f"{result.get('error', 'unknown error')}: {str(result.get('error_description', ''))[:200]}",
                SECRET_REMEDY)
        self._token = result["access_token"]
        # No expiry reported -> do not cache at all: a token of unknown lifetime is worse than a call.
        self._expires_at = self._now() + float(result["expires_in"]) if result.get("expires_in") else 0.0
        return self._token


class StaticToken(TokenSource):
    """A token someone already holds (`az account get-access-token --resource https://graph.microsoft.com`).
    Dev and live probing only: it expires and nothing here can renew it."""

    def __init__(self, token: str) -> None:
        self._token = token

    def token(self) -> str:
        return self._token


class Unconfigured(TokenSource):
    """No credential — every call refuses with a sentence naming the settings that are missing.

    This is the whole point of having a mode for it: an unconfigured lab must fail at the CALL, with
    a remedy, not at import with a `KeyError` in a server that then will not start."""

    def __init__(self, *settings: str) -> None:
        self.settings = tuple(settings)

    def token(self) -> str:
        names = ", ".join(self.settings)
        # Named as ONE thing (a credential) so the sentence reads whole however many keys are missing.
        raise CollabNotConfigured(f"the Microsoft Graph credential ({names})",
                                  f"set {names} — see the collaboration provisioning runbook")


def token_source(mode: str = "app", *, tenant_id: str = "", client_id: str = "", client_secret: str = "",
                 static_token: str = "", **kwargs) -> TokenSource:
    """The one place a mode becomes an object. A mode whose settings are incomplete degrades to
    `Unconfigured` naming EXACTLY the missing ones — never a half-built client that fails later with
    a stack trace instead of an instruction. `kwargs` (scope/now/skew/client_factory) reach the
    app-only source."""
    chosen = (mode or "").strip().lower()
    if chosen not in MODES:
        raise ValueError(f"GRAPH_AUTH_MODE={mode!r} is not one of {MODES}")
    extra = {k: v for k, v in kwargs.items() if v is not None}
    if chosen != "app" and extra:
        # Only the app-only source has a clock, a skew and a client factory. Swallowing them would
        # hide a typo'd keyword until someone wondered why the token never expired.
        raise ValueError(f"GRAPH_AUTH_MODE={chosen} takes no {sorted(extra)}")
    if chosen == "none":
        return Unconfigured("ENTRA_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET")
    if chosen == "static":
        return StaticToken(static_token) if static_token else Unconfigured("GRAPH_ACCESS_TOKEN")
    missing = [name for name, value in (("ENTRA_TENANT_ID", tenant_id), ("GRAPH_CLIENT_ID", client_id),
                                        ("GRAPH_CLIENT_SECRET", client_secret)) if not value]
    return Unconfigured(*missing) if missing else AppOnlyToken(tenant_id, client_id, client_secret, **kwargs)
