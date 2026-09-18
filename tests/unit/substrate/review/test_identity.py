"""Who is deciding, verified rather than typed.

Every decision in the approval ledger today is self-asserted: `human_decision` refuses a BLANK
actor but cannot check a present one, and the actor is a sidebar text box defaulting to `$USER`.
So "who released this EA-repository write" — the question the audit log exists to answer — is
currently answered by whoever was at the keyboard.

This module is the seam that fixes it. It is deliberately free of Streamlit: an auth-code flow is a
URL, a redemption and a set of claims, and none of those need a web framework to be tested.
"""
import pytest

from lab.substrate.review import identity


class _App:
    """A stand-in for MSAL's ConfidentialClientApplication — the seam `build` takes."""

    def __init__(self, result=None):
        self.result = result if result is not None else {}
        self.asked = []

    def get_authorization_request_url(self, scopes, state=None, redirect_uri=None, **_):
        self.asked.append(("url", tuple(scopes), state, redirect_uri))
        return f"https://login.example/authorize?state={state}&redirect_uri={redirect_uri}"

    def acquire_token_by_authorization_code(self, code, scopes, redirect_uri=None, **_):
        self.asked.append(("redeem", code, tuple(scopes), redirect_uri))
        return self.result


CLAIMS = {"oid": "0000-abc", "preferred_username": "sme@doh.gov.ae", "name": "A Reviewer",
          "roles": ["Lab.Architect"], "tid": "tenant-1"}


def _signin(result=None, **kw):
    app = _App(result)
    return identity.SignIn(app=app, redirect_uri="https://review.example/", tenant="tenant-1",
                           **kw), app


# ---------------------------------------------------------------- the principal


def test_a_principal_carries_the_identity_the_ledger_needs():
    p = identity.Principal.from_claims(CLAIMS)
    assert p.oid == "0000-abc" and p.upn == "sme@doh.gov.ae" and p.name == "A Reviewer"
    assert p.roles == ("Lab.Architect",)


def test_the_actor_is_the_UPN_because_that_is_what_a_person_is_looked_up_by():
    """Not the oid, which is correct and unreadable, and not the display name, which is neither
    unique nor stable. A reader of the audit log has to be able to find the human."""
    assert identity.Principal.from_claims(CLAIMS).actor == "sme@doh.gov.ae"


def test_a_token_with_no_upn_falls_back_to_the_oid_rather_than_going_blank():
    """A guest or an app-only token may carry no `preferred_username`. A blank actor is refused by
    `approvals.human_decision`, so the decision would be lost at the last step — an unreadable
    actor beats none."""
    p = identity.Principal.from_claims({"oid": "0000-abc", "roles": []})
    assert p.actor == "0000-abc"


def test_a_principal_with_no_oid_at_all_is_refused():
    """There is no such thing as an anonymous decider. Better to fail the sign-in than to record
    one."""
    with pytest.raises(ValueError):
        identity.Principal.from_claims({"preferred_username": "nobody@x"})


@pytest.mark.parametrize("roles,wanted,allowed", [
    (["Lab.Admin"], ("Lab.Admin",), True),
    (["Lab.Architect", "Lab.Business"], ("Lab.Admin", "Lab.Architect"), True),
    (["Lab.Business"], ("Lab.Architect",), False),
    ([], ("Lab.Architect",), False),
    (["Lab.Architect"], (), True),            # a page that names no role is open to any signed-in user
])
def test_holds_any_is_the_whole_authorisation_rule(roles, wanted, allowed):
    assert identity.Principal.from_claims({"oid": "x", "roles": roles}).holds_any(wanted) is allowed


# ---------------------------------------------------------------- the flow


def test_the_login_url_asks_for_the_openid_scopes_and_carries_the_state():
    """`state` is the CSRF defence: the callback is a plain GET on a URL anyone can construct, so
    the app must recognise its own request coming back."""
    flow, app = _signin()
    url = flow.login_url("state-123")
    assert "state=state-123" in url
    kind, scopes, state, redirect = app.asked[0]
    assert kind == "url" and state == "state-123"
    assert set(scopes) >= {"openid", "profile"}
    assert redirect == "https://review.example/"


def test_redeeming_a_code_yields_the_principal_from_the_ID_TOKEN_claims():
    """The ID token, not the access token: this app authenticates a person, it does not call an API
    on their behalf — and `custom_auth` refuses a delegated token on /api anyway."""
    flow, app = _signin({"id_token_claims": CLAIMS})
    p = flow.redeem("the-code")
    assert p.actor == "sme@doh.gov.ae" and p.roles == ("Lab.Architect",)
    assert app.asked[-1][0] == "redeem" and app.asked[-1][1] == "the-code"


def test_a_failed_redemption_raises_with_the_reason_rather_than_returning_nobody():
    """Returning None would land as an anonymous session, which is the one outcome sign-in exists
    to prevent."""
    flow, _ = _signin({"error": "invalid_grant", "error_description": "code expired"})
    with pytest.raises(identity.SignInError) as e:
        flow.redeem("stale")
    assert "invalid_grant" in str(e.value)


def test_a_token_from_another_tenant_is_refused():
    """The registration is single-tenant, but the check is here too: a token that validates
    cryptographically and comes from elsewhere is exactly what a tenant check is for."""
    flow, _ = _signin({"id_token_claims": dict(CLAIMS, tid="somebody-else")})
    with pytest.raises(identity.SignInError) as e:
        flow.redeem("code")
    assert "tenant" in str(e.value).lower()


def test_a_principal_with_no_roles_signs_in_and_sees_nothing():
    """Deliberately NOT an error. Somebody who authenticates but was never granted a role should be
    told that, not shown a login failure they cannot act on — the fix is an assignment, and naming
    it is how they find out."""
    flow, _ = _signin({"id_token_claims": dict(CLAIMS, roles=[])})
    assert flow.redeem("code").roles == ()


# ---------------------------------------------------------------- configuration


def test_sign_in_is_configured_only_when_every_part_is_present(monkeypatch):
    """A half-configured SSO must not half-enable the gate: missing anything and the app keeps the
    password fallback, which is the difference between "not set up" and "locked out"."""
    parts = {"REVIEW_ENTRA_CLIENT_ID": "cid", "REVIEW_ENTRA_CLIENT_SECRET": "secret",
             "ENTRA_TENANT_ID": "tenant-1", "REVIEW_APP_URL": "https://review.example/"}
    for name, value in parts.items():
        monkeypatch.setattr(identity.config, name, value)
    assert identity.configured() is True
    for name in parts:                       # any one of them missing is not configured
        monkeypatch.setattr(identity.config, name, "")
        assert identity.configured() is False, name
        monkeypatch.setattr(identity.config, name, parts[name])


def test_build_refuses_rather_than_returning_an_unusable_flow(monkeypatch):
    monkeypatch.setattr(identity.config, "REVIEW_ENTRA_CLIENT_ID", "")
    with pytest.raises(identity.SignInError):
        identity.build()
