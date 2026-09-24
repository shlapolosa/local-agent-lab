"""Who is deciding — verified by Entra, not typed into a box.

`approvals.human_decision` refuses a BLANK actor and cannot check a present one, and until now the
actor was a sidebar text box defaulting to the shell user. So the question the audit log exists to
answer — who released this EA-repository write — was answered by whoever was at the keyboard. This
module makes that string an identity the tenant can vouch for.

(The phrasing above is deliberate: `test_di_boundaries` scans raw SOURCE for env reads, docstrings
included, so a module explaining why it does NOT read the environment must not quote the call.)

**Identity only, and that is not a limitation.** The review app is a trusted substrate component: it
reaches Redis and the object stores directly and never calls the gateway's `/api`. It could not use
a delegated token there anyway — `gateway/custom_auth.py` refuses one on every `/api` route, on the
grounds that "a signed-in person decides at the review app, which reaches the gate in-process". So
signing a human in changes what the LEDGER says, not what the app is allowed to call.

**Roles are this app's own vocabulary**, deliberately not `contracts.ApiRoles`. That class is the
REST ingress's, has exactly three values, and a governance test asserts every one of them maps to an
`apipolicy` operation — a role with no REST operation fails there as dead code. Admin, architect and
business are app roles on the review app's own registration.

The MSAL application is INJECTED (`SignIn.app`) rather than constructed here, so the flow is
testable without a tenant, a browser or a network.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from lab.platform import config

__all__ = ["ADMIN", "ARCHITECT", "BUSINESS", "ROLES", "Principal", "SignIn", "SignInError",
           "build", "configured"]

#: The app roles, as the registration declares them. One per thing a person may do, and the split is
#: the control: an architect confirms that a design conforms, a business owner authorises the spend,
#: and neither implies the other. Admin maintains the reference artifacts everything else reads.
ADMIN = "Lab.Admin"
ARCHITECT = "Lab.Architect"
BUSINESS = "Lab.Business"
ROLES: tuple[str, ...] = (ADMIN, ARCHITECT, BUSINESS)

#: What an interactive sign-in asks for. No API scope: this app authenticates a person, it does not
#: act on their behalf anywhere.
SCOPES: tuple[str, ...] = ("openid", "profile", "email")


class SignInError(RuntimeError):
    """Sign-in failed. Raised rather than returning None, because an empty principal would land as
    an anonymous session — the one outcome signing in exists to prevent."""


@dataclass(frozen=True)
class Principal:
    """The signed-in human, as the ledger will record them."""

    oid: str
    upn: str = ""
    name: str = ""
    roles: tuple[str, ...] = ()

    @classmethod
    def from_claims(cls, claims: Mapping[str, Any]) -> "Principal":
        oid = str(claims.get("oid") or claims.get("sub") or "").strip()
        if not oid:
            raise ValueError("a token with no subject identifies nobody — there is no anonymous "
                             "decider, so refusing the sign-in beats recording one")
        roles = tuple(str(r).strip() for r in (claims.get("roles") or ()) if str(r).strip())
        return cls(oid=oid,
                   upn=str(claims.get("preferred_username") or claims.get("upn") or "").strip(),
                   name=str(claims.get("name") or "").strip(), roles=roles)

    @property
    def actor(self) -> str:
        """What goes in the audit log. The UPN, because that is what a person is looked up by — not
        the oid, which is correct and unreadable, and not the display name, which is neither unique
        nor stable. Falls back to the oid rather than going blank: a guest token may carry no UPN,
        and `human_decision` refuses a blank actor, so the decision would be lost at the last
        step."""
        return self.upn or self.oid

    def holds_any(self, roles: Sequence[str] | Iterable[str]) -> bool:
        """Whether this person may reach something needing one of `roles`. An EMPTY requirement is
        open to any signed-in user — a page with no role named is not a page with no reader."""
        wanted = tuple(roles or ())
        return not wanted or bool(set(wanted) & set(self.roles))


@dataclass(frozen=True)
class SignIn:
    """One auth-code flow against one registration.

    `app` is anything with MSAL's two methods, so the flow is exercised without a tenant.
    """

    app: Any
    redirect_uri: str
    tenant: str = ""

    def login_url(self, state: str) -> str:
        """Where to send the browser. `state` is the CSRF defence — the callback is a plain GET on a
        URL anyone can construct, so the app has to recognise its own request coming back."""
        return self.app.get_authorization_request_url(
            list(SCOPES), state=state, redirect_uri=self.redirect_uri)

    def redeem(self, code: str) -> Principal:
        """The authorization code for the person it stands for.

        The ID TOKEN's claims, not an access token: this app authenticates, it does not call an API
        on anyone's behalf.
        """
        result = self.app.acquire_token_by_authorization_code(
            code, list(SCOPES), redirect_uri=self.redirect_uri) or {}
        if "id_token_claims" not in result:
            raise SignInError(f"{result.get('error', 'sign-in failed')}: "
                              f"{str(result.get('error_description', ''))[:200]}")
        claims = result["id_token_claims"]
        # The registration is single-tenant, so this is belt and braces — and it is the check that
        # matters if it ever stops being: a token can be cryptographically valid and from elsewhere.
        if self.tenant and str(claims.get("tid") or "") != self.tenant:
            raise SignInError(f"token is from tenant {claims.get('tid')!r}, not this one")
        try:
            return Principal.from_claims(claims)
        except ValueError as bad:
            raise SignInError(str(bad)) from bad


def configured() -> bool:
    """Whether SSO can run. EVERY part or none: a half-configured sign-in must not half-enable the
    gate, because the difference between "not set up" and "locked out" is what the password
    fallback exists to preserve."""
    return all((config.REVIEW_ENTRA_CLIENT_ID, config.REVIEW_ENTRA_CLIENT_SECRET,
                config.ENTRA_TENANT_ID, config.REVIEW_APP_URL))


def build() -> SignIn:
    """The configured flow. Imports MSAL lazily so a deployment without SSO neither needs the
    dependency at import time nor pays for it."""
    if not configured():
        raise SignInError("SSO is not configured — REVIEW_ENTRA_CLIENT_ID, "
                          "REVIEW_ENTRA_CLIENT_SECRET, ENTRA_TENANT_ID and REVIEW_APP_URL")
    import msal

    app = msal.ConfidentialClientApplication(
        config.REVIEW_ENTRA_CLIENT_ID, client_credential=config.REVIEW_ENTRA_CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{config.ENTRA_TENANT_ID}")
    return SignIn(app=app, redirect_uri=config.REVIEW_APP_URL, tenant=config.ENTRA_TENANT_ID)
