"""Agent identity via Entra ID (MSAL client-credentials) — the docx pattern: one app
registration per agent, tokens from the real IdP, no static gateway keys in agent code.

agent_headers() returns the Authorization header for gateway calls:
  - EA_AGENT_CLIENT_ID/SECRET set  -> MSAL acquire_token_for_client (cached by MSAL,
    scope = <ENTRA_GATEWAY_AUDIENCE>/.default), i.e. an Entra JWT
  - otherwise                      -> the static virtual key (EA_AGENT_KEY), local fallback
The gateway's custom auth (gateway/custom_auth.py) maps the JWT's app registration back to
the same virtual key, so governance (budgets/ACLs/spend) is identical either way.
"""
import os

_app = None


def agent_token() -> str | None:
    global _app
    cid, secret = os.environ.get("EA_AGENT_CLIENT_ID"), os.environ.get("EA_AGENT_CLIENT_SECRET")
    if not (cid and secret):
        return None
    import msal
    if _app is None:
        _app = msal.ConfidentialClientApplication(
            cid, client_credential=secret,
            authority=f"https://login.microsoftonline.com/{os.environ['ENTRA_TENANT_ID']}")
    scope = os.environ["ENTRA_GATEWAY_AUDIENCE"].rstrip("/") + "/.default"
    result = _app.acquire_token_for_client(scopes=[scope])
    if "access_token" not in result:
        raise RuntimeError(f"MSAL: {result.get('error')}: {result.get('error_description', '')[:200]}")
    return result["access_token"]


def agent_headers() -> dict:
    tok = agent_token()
    if tok:
        return {"Authorization": f"Bearer {tok}"}
    return {"Authorization": f"Bearer {os.environ['EA_AGENT_KEY']}"}
