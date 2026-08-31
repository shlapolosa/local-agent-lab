"""Agent identity via Entra ID (MSAL client-credentials) — the docx pattern: one app
registration per agent, tokens from the real IdP, no static gateway keys in agent code.

agent_headers(prefix) returns the Authorization header for a given agent's gateway calls. The
prefix selects the agent's env credentials (default "EA_AGENT"; the Visio workflow uses
"BA_AGENT" and "ARCHITECT_AGENT"):
  - <PREFIX>_CLIENT_ID/SECRET set -> MSAL acquire_token_for_client (cached by MSAL,
    scope = <ENTRA_GATEWAY_AUDIENCE>/.default), i.e. an Entra JWT
  - otherwise                    -> the static virtual key <PREFIX>_KEY, local fallback
The gateway's custom auth (gateway/custom_auth.py) maps the JWT's app registration back to the
same virtual key, so governance (budgets/ACLs/spend) is identical either way. One app
registration ↔ one virtual key ↔ one agent.
"""
import os

_apps: dict = {}


def agent_token(prefix: str = "EA_AGENT") -> str | None:
    cid, secret = os.environ.get(f"{prefix}_CLIENT_ID"), os.environ.get(f"{prefix}_CLIENT_SECRET")
    if not (cid and secret):
        return None
    import msal
    if prefix not in _apps:
        _apps[prefix] = msal.ConfidentialClientApplication(
            cid, client_credential=secret,
            authority=f"https://login.microsoftonline.com/{os.environ['ENTRA_TENANT_ID']}")
    scope = os.environ["ENTRA_GATEWAY_AUDIENCE"].rstrip("/") + "/.default"
    result = _apps[prefix].acquire_token_for_client(scopes=[scope])
    if "access_token" not in result:
        raise RuntimeError(f"MSAL: {result.get('error')}: {result.get('error_description', '')[:200]}")
    return result["access_token"]


def agent_headers(prefix: str = "EA_AGENT") -> dict:
    tok = agent_token(prefix)
    if tok:
        return {"Authorization": f"Bearer {tok}"}
    return {"Authorization": f"Bearer {os.environ[f'{prefix}_KEY']}"}
