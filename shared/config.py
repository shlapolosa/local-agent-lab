"""One place for every address and secret the lab's processes need — so nothing assumes
"the other service is on this machine". Defaults are the local single-machine layout; a cloud
deployment sets the env vars (see deploy/ and .env.example).
"""
import os

_e = os.environ.get

# --- where things are (URLs as seen by the CALLER) ---
GATEWAY_URL      = _e("GATEWAY_URL", "http://127.0.0.1:4000")           # LiteLLM, for agents/clients
GATEWAY_MCP_URL  = _e("GATEWAY_MCP_URL", GATEWAY_URL.rstrip("/") + "/mcp/")
ADOIT_MCP_URL    = _e("ADOIT_MCP_URL", "http://127.0.0.1:9100/mcp")     # as seen by the gateway
SEMANTIC_MCP_URL = _e("SEMANTIC_MCP_URL", "http://127.0.0.1:9200/mcp")
STORAGE_MCP_URL  = _e("STORAGE_MCP_URL", "http://127.0.0.1:9300/mcp")   # read-only governed object store
REVIEW_APP_URL   = _e("REVIEW_APP_URL", "http://127.0.0.1:8501")        # for humans (tool results, Telegram)
JAEGER_UI_URL    = _e("JAEGER_UI_URL", "http://127.0.0.1:16686")

# --- how servers listen ---
BIND_HOST = _e("BIND_HOST", "127.0.0.1")   # 0.0.0.0 in containers
ADOIT_MCP_PORT    = int(_e("ADOIT_MCP_PORT", "9100"))
SEMANTIC_MCP_PORT = int(_e("SEMANTIC_MCP_PORT", "9200"))
STORAGE_MCP_PORT  = int(_e("STORAGE_MCP_PORT", "9300"))

# --- trust between services ---
MCP_SHARED_SECRET = _e("MCP_SHARED_SECRET")          # gateway -> MCP servers bearer token; unset = open (local only)
REVIEW_APP_PASSWORD = _e("REVIEW_APP_PASSWORD")      # minimal gate when no identity-aware proxy fronts the app

# --- state that must be reachable from every host ---
REDIS_URL = _e("REDIS_URL") or f"redis://{_e('REDIS_HOST', '127.0.0.1')}:{_e('REDIS_PORT', '6379')}/0"
ARTIFACTS_URL = _e("ARTIFACTS_URL") or _e("DATABASE_URL") or f"file://{os.path.abspath('artifacts')}"
# Submitted INPUTS (uploads) may live in a bucket while renders stay in Postgres: s3://bucket[/prefix]
# — only the review app (writes) and storage-mcp (reads) get this + the S3_* credentials. Unset =
# same store as ARTIFACTS_URL, so local dev needs no S3 at all.
UPLOADS_URL = _e("UPLOADS_URL") or ARTIFACTS_URL
S3_ENDPOINT = _e("S3_ENDPOINT")                       # e.g. Railway Bucket endpoint; unset = AWS
S3_REGION = _e("S3_REGION")
S3_ACCESS_KEY_ID = _e("S3_ACCESS_KEY_ID")
S3_SECRET_ACCESS_KEY = _e("S3_SECRET_ACCESS_KEY")
S3_URL_STYLE = _e("S3_URL_STYLE", "path")             # path | virtual (Railway reports urlStyle)


def public_url(kind: str) -> str:
    return {"review": REVIEW_APP_URL, "jaeger": JAEGER_UI_URL, "gateway": GATEWAY_URL}[kind]
