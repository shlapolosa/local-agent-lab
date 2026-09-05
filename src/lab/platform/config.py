"""One place for every address and secret the lab's processes need — so nothing assumes
"the other service is on this machine". Defaults are the local single-machine layout; a cloud
deployment sets the env vars (see deploy/ and .env.example).
"""
import os
from pathlib import Path

_e = os.environ.get

# --- where the tree is (paths, not URLs): the repo root and the git-ignored runtime dir ---
REPO_ROOT = Path(__file__).resolve().parents[3]            # src/lab/platform/config.py -> repo (editable install)
VAR_DIR = Path(_e("LAB_VAR_DIR") or REPO_ROOT / "var")     # logs/ run/ artifacts/ out/ inputs/ tools/ reference-sources/

# --- where things are (URLs as seen by the CALLER) ---
GATEWAY_URL      = _e("GATEWAY_URL", "http://127.0.0.1:4000")           # LiteLLM, for agents/clients
GATEWAY_MCP_URL  = _e("GATEWAY_MCP_URL", GATEWAY_URL.rstrip("/") + "/mcp/")
ADOIT_MCP_URL    = _e("ADOIT_MCP_URL", "http://127.0.0.1:9100/mcp")     # as seen by the gateway
SEMANTIC_MCP_URL = _e("SEMANTIC_MCP_URL", "http://127.0.0.1:9200/mcp")
STORAGE_MCP_URL  = _e("STORAGE_MCP_URL", "http://127.0.0.1:9300/mcp")   # read-only governed object store
WORKFLOW_MCP_URL = _e("WORKFLOW_MCP_URL", "http://127.0.0.1:9400/mcp")  # the front door's AGENT ingress
WORKFLOW_API_URL = _e("WORKFLOW_API_URL", "http://127.0.0.1:9400/api")  # ... and its REST one, for clients that are not agents
GRAPH_MCP_URL    = _e("GRAPH_MCP_URL", "http://127.0.0.1:9500/mcp")     # the COLLABORATION port (alias collab_mcp)
SPEECH_MCP_URL   = _e("SPEECH_MCP_URL", "http://127.0.0.1:9600/mcp")    # the SPEECH port (alias speech_mcp)
REVIEW_APP_URL   = _e("REVIEW_APP_URL", "http://127.0.0.1:8501")        # for humans (tool results, Telegram)
TELEGRAM_BOT_TOKEN = _e("TELEGRAM_BOT_TOKEN")                             # Telegram approval channel (plumbing;
TELEGRAM_CHAT_ID   = _e("TELEGRAM_CHAT_ID")                               #  unset = channel disabled)
TEAMS_WEBHOOK_URL  = _e("TEAMS_WEBHOOK_URL")                              # Teams approval channel: incoming
                                                                          #  webhook; unset = channel disabled
JAEGER_UI_URL    = _e("JAEGER_UI_URL", "http://127.0.0.1:16686")

# --- how servers listen ---
BIND_HOST = _e("BIND_HOST", "127.0.0.1")   # 0.0.0.0 in containers
ADOIT_MCP_PORT    = int(_e("ADOIT_MCP_PORT", "9100"))
SEMANTIC_MCP_PORT = int(_e("SEMANTIC_MCP_PORT", "9200"))
STORAGE_MCP_PORT  = int(_e("STORAGE_MCP_PORT", "9300"))
WORKFLOW_MCP_PORT = int(_e("WORKFLOW_MCP_PORT", "9400"))
GRAPH_MCP_PORT    = int(_e("GRAPH_MCP_PORT", "9500"))
SPEECH_MCP_PORT   = int(_e("SPEECH_MCP_PORT", "9600"))

# --- host tooling ---
# Rendering a .vsdx page to a picture needs LibreOffice on the HOST running storage-mcp. It is an
# optional capability: absent, the pipeline degrades to the structured parse (see render_vsdx).
SOFFICE_BIN = _e("SOFFICE_BIN")                      # override for an install off the standard paths

# --- trust between services ---
MCP_SHARED_SECRET = _e("MCP_SHARED_SECRET")          # gateway -> MCP servers bearer token; unset = open (local only)
REVIEW_APP_PASSWORD = _e("REVIEW_APP_PASSWORD")      # minimal gate when no identity-aware proxy fronts the app

# --- ADOIT write policy ---
# The hosted Community Edition (adoit-ce.boc-cloud.com) BLOCKS REST write verbs at its edge proxy
# (POST/PATCH/DELETE -> a "URL not available" page; reads work). So the default write path is the
# human-gated FILE-IMPORT (ArchiMate XML for views+creates; Excel for object create/update). The
# granular REST write facade (adoit_rest.create/patch/delete/relation) is built and grounded but stays
# DORMANT until a full/licensed ADOIT tenant (or Azure/Foundry target) is reachable — flip this then.
def _bool(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")

ADOIT_REST_WRITE = _bool(_e("ADOIT_REST_WRITE"))     # false on CE; true only against a write-capable tenant

# --- state that must be reachable from every host ---
REDIS_URL = _e("REDIS_URL") or f"redis://{_e('REDIS_HOST', '127.0.0.1')}:{_e('REDIS_PORT', '6379')}/0"
ARTIFACTS_URL = _e("ARTIFACTS_URL") or _e("DATABASE_URL") or f"file://{VAR_DIR / 'artifacts'}"
# Submitted INPUTS (uploads) may live in a bucket while renders stay in Postgres: s3://bucket[/prefix]
# — only the review app (writes) and storage-mcp (reads) get this + the S3_* credentials. Unset =
# same store as ARTIFACTS_URL, so local dev needs no S3 at all.
UPLOADS_URL = _e("UPLOADS_URL") or ARTIFACTS_URL
S3_ENDPOINT = _e("S3_ENDPOINT")                       # e.g. Railway Bucket endpoint; unset = AWS
S3_REGION = _e("S3_REGION")
S3_ACCESS_KEY_ID = _e("S3_ACCESS_KEY_ID")
S3_SECRET_ACCESS_KEY = _e("S3_SECRET_ACCESS_KEY")
S3_URL_STYLE = _e("S3_URL_STYLE", "path")             # path | virtual (Railway reports urlStyle)

# --- artifact size policy (the streaming write path: a Teams meeting recording is 100s of MB) ---
# Deployment policy, not domain logic: the ceiling depends on the bucket/database tier, so it lives
# here as the DEFAULT and enters each Store through its constructor (`max_bytes=`), never read there.
ARTIFACT_MAX_BYTES = int(_e("ARTIFACT_MAX_BYTES") or 5 * 1024 ** 3)             # 5 GiB — any backend
# Postgres holds the object INLINE in a bytea column: the row is materialised in RAM on both sides
# (and PostgreSQL's own bytea ceiling is 1 GB), so the inline store refuses anything larger and says
# to configure a bucket. 64 MiB comfortably covers what this backend exists for (specs, XML, SVG,
# XLSX) on an 8 GB machine, and is far below the point where a bytea row becomes the wrong answer.
ARTIFACT_INLINE_MAX_BYTES = int(_e("ARTIFACT_INLINE_MAX_BYTES") or 64 * 1024 ** 2)   # 64 MiB — postgres

# --- licensed reference workbooks (BA Guild): never in the repo; a directory outside the tree or var/ ---
REFERENCE_MODELS_DIR = _e("REFERENCE_MODELS_DIR") or str(VAR_DIR / "reference-sources")

# --- collaboration provider (Microsoft Graph adapter: src/lab/substrate/mcp/graph/) ---
# WHICH adapter the substrate wires behind the vendor-neutral `collab_mcp` port. The name is a key
# in `lab.substrate.container.COLLAB_PROVIDERS`, so adding a second collaboration platform is one
# registry entry plus its own `GRAPH_*`-equivalent settings — never an edit in the server.
COLLAB_PROVIDER = _e("COLLAB_PROVIDER", "graph")       # THE default lives here, nowhere else

# The tenant is the lab's existing Entra tenant — there is no second tenant setting. What differs
# from an agent app registration is only what it is GRANTED: Microsoft Graph APPLICATION permissions
# instead of the gateway's own app roles. The adapter authenticates app-only: the caller's credential
# authorises the call to the MCP server, the server's own identity authorises the call to Graph, so
# the app's permissions are the ceiling for every caller and per-caller narrowing is done at the
# gateway with per-team tool permissions.
ENTRA_TENANT_ID = _e("ENTRA_TENANT_ID", "")           # shared with the gateway's JWT validation
GRAPH_BASE_URL = _e("GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0")
GRAPH_AUTH_MODE = _e("GRAPH_AUTH_MODE", "app")        # app (client credentials) | static (a token) | none
GRAPH_CLIENT_ID = _e("GRAPH_CLIENT_ID")               # the app registration holding the Graph grants
GRAPH_CLIENT_SECRET = _e("GRAPH_CLIENT_SECRET")       # a long-lived SECRET, never a long-lived token
GRAPH_ACCESS_TOKEN = _e("GRAPH_ACCESS_TOKEN")         # mode=static only: a token from `az`, for probing
GRAPH_MEETING_USER = _e("GRAPH_MEETING_USER")         # whose calendar/meetings app-only reads default to
# …and the full set that may be read at all. App-only reaches every mailbox the Teams application
# access policy covers, so this is a BOUND on the `organizer` argument, not just a default. Unset =
# GRAPH_MEETING_USER alone.
GRAPH_MEETING_USERS = tuple(u.strip() for u in (_e("GRAPH_MEETING_USERS") or "").split(",") if u.strip())
GRAPH_MAX_FETCH_BYTES = int(_e("GRAPH_MAX_FETCH_BYTES") or 2 * 1024 ** 3)   # 2 GiB — a long recording
# Change-notification destinations: egress to a caller-supplied URL, so an EMPTY list REFUSES every
# subscription rather than allowing all. Comma-separated URL prefixes.
GRAPH_NOTIFICATION_ALLOWLIST = tuple(u.strip() for u in (_e("GRAPH_NOTIFICATION_ALLOWLIST") or "").split(",") if u.strip())
# Metering: since 25 Aug 2025 the Teams Graph APIs are NO LONGER metered and the `model` parameter is
# ignored (https://learn.microsoft.com/graph/metered-api-list — only driveItem:assignSensitivityLabel
# remains billed). What this flag still gates is the TENANT-WIDE meeting feeds
# (/communications/onlineMeetings/getAllRecordings|getAllTranscripts and subscriptions on them), which
# are BETA-only, unbounded in blast radius, and the historical metered surface — off by default.
GRAPH_ALLOW_METERED = _bool(_e("GRAPH_ALLOW_METERED"))


# --- speech (the SPEECH port; the alias is `speech_mcp`, the SERVICE and its credential are the vendor) ---
# Same shape as the collaboration port: one registry key picks the adapter, and adding a provider is
# a registry entry plus its own settings — never an edit in the server.
SPEECH_PROVIDER = _e("SPEECH_PROVIDER", "munsit")
MUNSIT_API_KEY = _e("MUNSIT_API_KEY")                 # the provider credential; only speech-mcp gets it
MUNSIT_BASE_URL = _e("MUNSIT_BASE_URL", "https://api.munsit.com/api/v1")
# A meeting recording is VIDEO and every speech provider we surveyed takes audio only, so the audio
# has to be extracted first. This is a HOST TOOL, exactly like SOFFICE_BIN for document rendering:
# `ffmpeg` in a container, `afconvert` on macOS (built in, nothing to install). Unset disables
# extraction, and a video input then fails with a sentence naming the missing tool.
AUDIO_EXTRACT_BIN = _e("AUDIO_EXTRACT_BIN", "")

# Which languages a meeting actually uses, as a HINT to the speech provider. Both together is what
# selects a model able to transcribe speech that switches language MID-SENTENCE; declaring one when
# two are spoken is what makes an engine translate or transliterate the switch instead.
MEETING_LANGUAGES = tuple(l.strip() for l in _e("MEETING_LANGUAGES", "ar,en").split(",") if l.strip())

# This replica's name INSIDE its consumer group — stable per replica, so its pending list survives a
# restart. Not a process selector: two replicas of one process are "1" and "2", and another
# process's "1" does not collide because the GROUP differs.
WF_CONSUMER = _e("WF_CONSUMER", "1")

# The model that writes the minutes — OURS, through the gateway, never the transcription vendor's.
MINUTES_AGENT_MODEL = _e("MINUTES_AGENT_MODEL", "kimi-k3")
# The gateway's upstream implements only the NON-stateful Responses flavour, so a stateful turn comes
# back empty and full context is resent each turn. Set true only against a Responses-stateful backend.
AGENT_RESPONSES_STORE = _e("AGENT_RESPONSES_STORE", "false").lower() == "true"
