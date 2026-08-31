"""Developer login to the lab gateway with Entra — run this, sign in, and export the
printed variables. Works for BOTH client standards:
  OpenAI-style tools:   OPENAI_BASE_URL=http://127.0.0.1:4000/v1   OPENAI_API_KEY=<token>
  Claude Code:          ANTHROPIC_BASE_URL=http://127.0.0.1:4000   ANTHROPIC_AUTH_TOKEN=<token>
The gateway validates the token and JIT-provisions your personal virtual key (team
`developers`) on first use; `/model` and GET /v1/models then show your allowed models.
Tokens last ~1h; MSAL caches and refreshes silently while this shell helper is reused.
Usage: .venv/bin/python gateway/dev_login.py [--print-token]
"""
import os
import sys

import msal

TENANT = os.environ.get("ENTRA_TENANT_ID", "b911f4d4-de30-405f-96e9-bb1c773fe2ff")
CLIENT = os.environ["DEV_CLIENT_ID"]
AUD = os.environ["ENTRA_GATEWAY_AUDIENCE"]
CACHE = os.path.expanduser("~/.lab-dev-token.bin")

cache = msal.SerializableTokenCache()
if os.path.exists(CACHE):
    cache.deserialize(open(CACHE).read())
app = msal.PublicClientApplication(CLIENT, authority=f"https://login.microsoftonline.com/{TENANT}",
                                   token_cache=cache)
scopes = [f"{AUD}/access_as_user"]
result = None
for acct in app.get_accounts():
    result = app.acquire_token_silent(scopes, account=acct)
    if result:
        break
if not result:
    if "--print-token" in sys.argv:      # helper mode must NEVER block on interactive login
        sys.exit("no cached login — run gateway/dev_login.py interactively first")
    flow = app.initiate_device_flow(scopes=scopes)
    print(flow["message"], file=sys.stderr)
    result = app.acquire_token_by_device_flow(flow)
if "access_token" not in result:
    sys.exit(f"login failed: {result.get('error_description', result)[:300]}")
open(CACHE, "w").write(cache.serialize())
tok = result["access_token"]
if "--print-token" in sys.argv:
    print(tok)
else:
    gw = os.environ.get("GATEWAY_URL", "http://127.0.0.1:4000")
    print(f"# signed in as {result.get('id_token_claims', {}).get('preferred_username', '?')}")
    print(f"export OPENAI_BASE_URL={gw}/v1")
    print(f"export OPENAI_API_KEY={tok}")
    print(f"export ANTHROPIC_BASE_URL={gw}")
    print(f"export ANTHROPIC_AUTH_TOKEN={tok}")
