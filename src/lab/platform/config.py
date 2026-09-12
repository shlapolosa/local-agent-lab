"""One place for every address and secret the lab's processes need — so nothing assumes
"the other service is on this machine". Defaults are the local single-machine layout; a cloud
deployment sets the env vars (see deploy/ and .env.example).
"""
import json
import os
from pathlib import Path

_e = os.environ.get


def _mapping(name: str) -> dict:
    """A JSON object from the environment, or EMPTY. Same contract as `_rows`: empty is a real
    answer, and the code that reads it must say so rather than substitute a number."""
    try:
        value = json.loads(_e(name) or "{}")
        return dict(value) if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _rows(name: str) -> tuple[dict, ...]:
    """A JSON array of objects from the environment, or EMPTY when it is unset or malformed.

    Empty is a real answer here and the callers are built for it: a policy table nobody has
    configured must make the code that reads it escalate, never fall back to a default that looks
    like a decision somebody took."""
    try:
        value = json.loads(_e(name) or "[]")
        return tuple(r for r in value if isinstance(r, dict))
    except (TypeError, ValueError):
        return ()

# --- where the tree is (paths, not URLs): the repo root and the git-ignored runtime dir ---
REPO_ROOT = Path(__file__).resolve().parents[3]            # src/lab/platform/config.py -> repo (editable install)
VAR_DIR = Path(_e("LAB_VAR_DIR") or REPO_ROOT / "var")     # logs/ run/ artifacts/ out/ inputs/ tools/ reference-sources/

# --- where things are (URLs as seen by the CALLER) ---
GATEWAY_URL      = _e("GATEWAY_URL", "http://127.0.0.1:4000")           # LiteLLM, for agents/clients
#: The internet-reachable gateway, when there is one. Separate from GATEWAY_URL deliberately: a
#: caller OUTSIDE this machine — a Power Automate flow, a CI job publishing agent cards — cannot
#: reach 127.0.0.1, and defaulting to it is a silent no-op rather than an error.
PUBLIC_GATEWAY_URL = _e("PUBLIC_GATEWAY_URL", "")
GATEWAY_MCP_URL  = _e("GATEWAY_MCP_URL", GATEWAY_URL.rstrip("/") + "/mcp/")
ADOIT_MCP_URL    = _e("ADOIT_MCP_URL", "http://127.0.0.1:9100/mcp")     # as seen by the gateway
SEMANTIC_MCP_URL = _e("SEMANTIC_MCP_URL", "http://127.0.0.1:9200/mcp")
STORAGE_MCP_URL  = _e("STORAGE_MCP_URL", "http://127.0.0.1:9300/mcp")   # read-only governed object store
WORKFLOW_MCP_URL = _e("WORKFLOW_MCP_URL", "http://127.0.0.1:9400/mcp")  # the front door's AGENT ingress
WORKFLOW_API_URL = _e("WORKFLOW_API_URL", "http://127.0.0.1:9400/api")  # ... and its REST one, for clients that are not agents
GRAPH_MCP_URL    = _e("GRAPH_MCP_URL", "http://127.0.0.1:9500/mcp")     # the COLLABORATION port (alias collab_mcp)
SPEECH_MCP_URL   = _e("SPEECH_MCP_URL", "http://127.0.0.1:9600/mcp")    # the SPEECH port (alias speech_mcp)
REFERENCE_MCP_URL = _e("REFERENCE_MCP_URL", "http://127.0.0.1:9700/mcp")  # the governed CORPUS (alias reference_mcp)
EMBED_URL = _e("EMBED_URL", "http://127.0.0.1:11434")   # the substrate's embedding model (Ollama API); the gateway's model_list points here
DECISION_MCP_URL = _e("DECISION_MCP_URL", "http://127.0.0.1:9800/mcp")    # the CAFÉ derivations (alias decision_mcp)
VALUATION_MCP_URL = _e("VALUATION_MCP_URL", "http://127.0.0.1:9900/mcp")  # cost and benefit (alias valuation_mcp)
REVIEW_APP_URL   = _e("REVIEW_APP_URL", "http://127.0.0.1:8501")        # for humans (tool results, Telegram)
TELEGRAM_BOT_TOKEN = _e("TELEGRAM_BOT_TOKEN")                             # Telegram approval channel (plumbing;
TELEGRAM_CHAT_ID   = _e("TELEGRAM_CHAT_ID")                               #  unset = channel disabled)
TEAMS_WEBHOOK_URL  = _e("TEAMS_WEBHOOK_URL")                              # Teams approval channel: incoming
                                                                          #  webhook; unset = channel disabled
# Where the meeting notifier POSTs. A Power Automate "when a webhook request is received" flow
# that posts into the meeting's own chat — Graph refuses to let an application post one, so
# something holding a person's connection must. Unset = the notifier logs what it would say,
# which is what makes the whole path testable without a tenant.
MEETING_WEBHOOK_URL = _e("MEETING_WEBHOOK_URL", "")
# Where a submitter is told what became of their use case. Unset = the notifier logs
# what it WOULD post, which is how to watch it before wiring a destination.
USECASE_WEBHOOK_URL = _e("USECASE_WEBHOOK_URL")
# WHICH COMMIT this container is, baked into the image by CI (deploy/Dockerfile ARG LAB_BUILD_SHA).
# The image TAG says what a service was ASKED to run; this says what it actually IS, and the two
# disagree the moment anything pulls a mutable tag — which is how a workload came to call a tool the
# gateway had renamed. Empty outside a CI-built image (a local run, a repo build), and empty is an
# honest answer: this machine's code is whatever is checked out.
BUILD_SHA = _e("LAB_BUILD_SHA", "")


def build_id() -> str:
    """What a service prints so a person reading a log can tell which build produced it."""
    return f"build={BUILD_SHA[:7]}" if BUILD_SHA else "build=dev"


JAEGER_UI_URL    = _e("JAEGER_UI_URL", "http://127.0.0.1:16686")

# --- how servers listen ---
BIND_HOST = _e("BIND_HOST", "127.0.0.1")   # 0.0.0.0 in containers
ADOIT_MCP_PORT    = int(_e("ADOIT_MCP_PORT", "9100"))
SEMANTIC_MCP_PORT = int(_e("SEMANTIC_MCP_PORT", "9200"))
STORAGE_MCP_PORT  = int(_e("STORAGE_MCP_PORT", "9300"))
WORKFLOW_MCP_PORT = int(_e("WORKFLOW_MCP_PORT", "9400"))
GRAPH_MCP_PORT    = int(_e("GRAPH_MCP_PORT", "9500"))
SPEECH_MCP_PORT   = int(_e("SPEECH_MCP_PORT", "9600"))
REFERENCE_MCP_PORT = int(_e("REFERENCE_MCP_PORT", "9700"))
DECISION_MCP_PORT = int(_e("DECISION_MCP_PORT", "9800"))
VALUATION_MCP_PORT = int(_e("VALUATION_MCP_PORT", "9900"))

# --- local policy the published framework deliberately leaves to the tenant ---
#: The delegation-of-authority bands: [{"limit": 50000, "authority": "delivery lead"}, …, the last
#: with "limit": null. UNSET by default and that is correct — `lab.core.usecase.authority` escalates
#: rather than routing a real funding decision by a threshold this lab invented.
DELEGATION_AUTHORITY = _rows("DELEGATION_AUTHORITY")

#: Which capability matcher step 5 runs. `leaves` measured 0.88 precision against the drill's 0.17
#: on a blind-adjudicated referral-triage case; the drill remains the fallback for a corpus whose
#: leaves will not fit in one prompt. See `lab.workloads.usecase.coverage`.
COVERAGE_MATCHER = _e("COVERAGE_MATCHER", "leaves")

#: Finance's reference VALUES, which `seed/benefit_drivers.json` says are held in their own
#: registries and are not published with the framework. They live beside the price sheet — on
#: valuation-mcp, the server finance owns — rather than being passed in by every caller. Unset
#: means the driver that needs them is `requires_input`, and the refusal says the registry is not
#: configured rather than naming a role as though one had been consulted.
ROLE_RATES = _mapping("ROLE_RATES")           # {"nurse": 120.0, "clinician": 300.0}
ERROR_COSTS = _mapping("ERROR_COSTS")         # {"missed referral": 4200.0}

# --- the governed reference corpus (signed, versioned artifacts read under a pin) ---
# The server runs as a READER role: DR-03 says no instance writes to a shared store under any
# condition, and a Postgres GRANT is the only form of that rule the server cannot talk its way out
# of. The publisher's DSN and the signing key live with the operator CLI and never reach a service.
REFERENCE_PROVIDER = _e("REFERENCE_PROVIDER", "postgres")
REFERENCE_DB_URL = _e("REFERENCE_DB_URL") or _e("DATABASE_URL", "")
REFERENCE_RING = int(_e("REFERENCE_RING", "2"))          # 0 pilot · 1 · 2 general
REFERENCE_PIN_TTL_S = int(_e("REFERENCE_PIN_TTL_S", "86400"))
REFERENCE_RING_SOAK_S = int(_e("REFERENCE_RING_SOAK_S", "86400"))
# Public key material only — `key_id:base64,...`. The PRIVATE seed must never appear here or in
# LAB_ENV: a signature made with a key everyone with repo admin holds proves nothing.
REFERENCE_TRUST_KEYS = _e("REFERENCE_TRUST_KEYS", "")
REFERENCE_EMBED_MODEL = _e("REFERENCE_EMBED_MODEL", "")   # empty = semantic search is unavailable
# The served model's NATIVE width (nomic-embed-text: 768), never a truncation: exact cosine over a
# few thousand passages makes width free, and one fewer thing to keep in step. A governance test
# holds this default to the gateway's `output_vector_size` for the model.
REFERENCE_EMBED_DIM = int(_e("REFERENCE_EMBED_DIM", "768"))
REFERENCE_EMBED_KEY = _e("REFERENCE_EMBED_KEY", "")       # a VIRTUAL key; the upstream one is the gateway's
# The PUBLISHER's three. They are read here because config is the one env reader, but no service is
# granted them: `ROLE_ENV["reference-mcp"]` lists neither, so in a deployed service all three are
# empty and the CLI refuses to run. REFERENCE_SIGNING_KEY is the private seed and belongs on the
# publishing workstation ALONE — in LAB_ENV it would prove nothing beyond repo admin, which is
# everyone who could have edited the row it is meant to protect.
REFERENCE_SIGNING_KEY = _e("REFERENCE_SIGNING_KEY", "")
REFERENCE_KEY_ID = _e("REFERENCE_KEY_ID", "k1")
REFERENCE_PUBLISH_DB_URL = _e("REFERENCE_PUBLISH_DB_URL") or _e("DATABASE_URL", "")


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
#: The licensed reference workbooks, as `art://` refs, comma-separated. They cannot travel in the
#: image: this repository is PUBLIC, and the BA Guild models are licensed — so the derived content
#: cannot be committed either. They travel the way every other piece of content in this lab travels,
#: by reference through the private artifact store, and the substrate materialises them at startup.
#: Unset means the local directory, which is how a workstation with the workbooks already works.
REFERENCE_MODELS_REFS = tuple(r.strip() for r in _e("REFERENCE_MODELS_REFS", "").split(",")
                              if r.strip())

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
ENTRA_GATEWAY_AUDIENCE = _e("ENTRA_GATEWAY_AUDIENCE", "")   # api://… — the scope an agent asks for
#: Entra app id -> virtual key, the mapping the gateway turns a validated JWT into a key with. Empty
#: is a real answer: a deployment where no agent has a registration yet still runs on durable keys.
ENTRA_CLIENT_TO_KEY = _mapping("ENTRA_CLIENT_TO_KEY")

# --- where an agent's A2A card is published; unset = nowhere, and it says so ---
# The card itself is portable (the A2A spec, with the Entra identity in `securitySchemes` — the same
# block APIM's validate-jwt checks). Only the DESTINATION is platform-specific, so it is the one
# thing configured: `litellm` today, `none`/unset to publish nothing at all, an APIM or static-file
# adapter later. THE default lives here, nowhere else.
AGENT_REGISTRY = _e("AGENT_REGISTRY", "")
#: The admin credential that publication needs. Deliberately absent from `container.CONFIG_KEYS`, so
#: it can never reach a workload — publication runs in CI, where this key already lives.
LITELLM_MASTER_KEY = _e("LITELLM_MASTER_KEY", "")
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
# Graph's SIMPLE upload ceiling. Above it an upload needs a resumable session, which is a lot of
# machinery for the documents this lab writes back — so the adapter refuses instead, naming this
# setting. 4 MiB is the provider's own limit for the simple path.
GRAPH_MAX_UPLOAD_BYTES = int(_e("GRAPH_MAX_UPLOAD_BYTES", str(4 * 1024 * 1024)))
# The WRITE identity, separate from GRAPH_CLIENT_* on purpose: the read app holds only read
# grants and its name says so, and a credential that can also overwrite anything it can see
# should be held by the one service that writes, not by every read path. Unset = the reader
# is used, which simply means uploads refuse for want of the permission.
GRAPH_WRITER_CLIENT_ID = _e("GRAPH_WRITER_CLIENT_ID", "")
GRAPH_WRITER_CLIENT_SECRET = _e("GRAPH_WRITER_CLIENT_SECRET", "")

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
# The LANES every meeting runs in. Empty (the default) = no fan-out: one run, the configured
# provider, exactly as before. Set it to several providers and each meeting produces one full
# pipeline per provider — its own transcript, its own speaker question, its own minutes and its own
# files. That is N times the provider spend and N times the human tagging, and it sends every
# recording to N vendors, so it is opt-in by configuration rather than a default.
SPEECH_LANES = tuple(x.strip().lower() for x in _e("SPEECH_LANES", "").split(",") if x.strip())
MUNSIT_API_KEY = _e("MUNSIT_API_KEY")                 # the provider credential; only speech-mcp gets it
MUNSIT_BASE_URL = _e("MUNSIT_BASE_URL", "https://api.munsit.com/api/v1")
# The bake-off providers. Each is INERT without its key: an unconfigured adapter reports
# SpeechNotConfigured from capabilities() and the comparison skips it by name, so a lab with one
# credential runs exactly as before.
ELEVENLABS_API_KEY = _e("ELEVENLABS_API_KEY")
ELEVENLABS_BASE_URL = _e("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io")
ASSEMBLYAI_API_KEY = _e("ASSEMBLYAI_API_KEY")
ASSEMBLYAI_BASE_URL = _e("ASSEMBLYAI_BASE_URL", "https://api.assemblyai.com")
SONIOX_API_KEY = _e("SONIOX_API_KEY")
SONIOX_BASE_URL = _e("SONIOX_BASE_URL", "https://api.soniox.com")
SONIOX_TRANSLATE_TO = _e("SONIOX_TRANSLATE_TO", "en")   # the target for its one_way translation
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
# THE declaration: the agent card (`contracts.AGENTS`) and the key's model allowlist
# (`scripts/provision_meeting_agents.py`) both read it here, so a switch is one value. kimi-k3 until
# 12 Sep 2026, when Ollama Cloud's account-wide weekly cap 429'd every call for days — measured
# against the DEPLOYED gateway with the minutes agent's own key, which is also how the key's
# allowlist turned out to be the second half of the problem: it said `['kimi-k3']`, so pointing the
# host at another model would have traded a 429 for a 403. Minutes are a JSON-mode frame against a
# schema, which is what gpt-5.4-mini was measured fast at, and it is the model the use-case agents
# moved to on the same day and the vendor that serves the corpus's embeddings.
MINUTES_AGENT_MODEL = _e("MINUTES_AGENT_MODEL", "gpt-5.4-mini")
# The use-case agents' model — THE declaration: the agent cards (`contracts.AGENTS`), the key and
# team allowlists (`scripts/provision_usecase_agents.py`) and the eval harness all read it here, so
# a switch is one value. kimi-k3 until 12 Sep 2026, when Ollama Cloud's account-wide weekly cap
# 429'd every call for days. MEASURED on the capability-matching step (12 Sep, `var/eval/
# model-comparison.md`): plain gpt-5.4-mini answered the 1,042-leaf prompt in 3 s and matched
# nothing, gpt-4.1 matched few; the same model with reasoning on (`gpt-5.4-mini-think`, a gateway
# group with reasoning_effort=medium) recalled 0.50/0.40 in ~90 s — the kimi baseline — at a
# fraction of claude-sonnet-5's cost. Speed alone is the wrong answer for this step.
USECASE_AGENT_MODEL = _e("USECASE_AGENT_MODEL", "gpt-5.4-mini-think")
# The gateway's upstream implements only the NON-stateful Responses flavour, so a stateful turn comes
# back empty and full context is resent each turn. Set true only against a Responses-stateful backend.
AGENT_RESPONSES_STORE = _e("AGENT_RESPONSES_STORE", "false").lower() == "true"

# --- the Documentation Fabric (docs/fabric/POC.md) ---
#: Port 1 of every source adapter: the durable stream ArtifactChanged events are published to.
FABRIC_EVENTS = _e("FABRIC_EVENTS", "fabric:events")
#: Below this confidence a suggested delivery association is never committed — it asks (rung 4).
FABRIC_ASSOCIATION_THRESHOLD = float(_e("FABRIC_ASSOCIATION_THRESHOLD", "0.75"))
#: Which sources' events enter the pipeline at all: `<sourceKind>:<site|project|drive id>` entries.
#: EMPTY means nothing is admitted — the ingress must escalate, not admit the world by default.
FABRIC_ALLOWLIST = tuple(a.strip() for a in (_e("FABRIC_ALLOWLIST") or "").split(",") if a.strip())
#: The secret a Graph change notification must echo in `clientState` before it is believed.
FABRIC_NOTIFY_CLIENT_STATE = _e("FABRIC_NOTIFY_CLIENT_STATE", "")
#: Where the projector writes a published artifact's Markdown projection (a collab:// folder handle).
FABRIC_WIKI_FOLDER = _e("FABRIC_WIKI_FOLDER", "")
# The Catalog product's store: the database semantic-mcp already reaches (the same fallback chain as
# the reference layer). Empty = an in-process catalog — tests and a laptop, never the cloud tier.
FABRIC_DB_URL = _e("FABRIC_DB_URL") or _e("DATABASE_URL", "")
# The intake's two agents share one model setting (both are kimi-k3 class work: classify metadata, draft
# records from minutes); the sensitivity label written at C when nothing better is known (NFR-3: a
# label is looked up, never guessed — the site default IS the lookup for a library with one label).
FABRIC_AGENT_MODEL = _e("FABRIC_AGENT_MODEL", "kimi-k3")
# The CURATOR: the virtual key the substrate's fabric consumers act with — the runner applies a person's
# fabric decision (PROMOTE, which no workload has), the projector writes pages, the reconciler sweeps.
# Empty = every fabric consumer refuses: an approved fabric question is recorded on its approval as a
# failure and releases NOTHING, so a record is never published with facets the fabric did not take.
FABRIC_CURATOR_KEY = _e("FABRIC_CURATOR_KEY", "")
# The reconciler's sweep: how often the allow-listed drives are listed against the catalog, how deep it
# follows folders (listing is one level deep by design), how many items one sweep may touch.
FABRIC_SWEEP_S = int(_e("FABRIC_SWEEP_S", "900"))
FABRIC_SWEEP_DEPTH = int(_e("FABRIC_SWEEP_DEPTH", "3"))
FABRIC_SWEEP_LIMIT = int(_e("FABRIC_SWEEP_LIMIT", "500"))
# The FIRST sweep after a start waits: a deploy restarts every service together and the gateway is the
# slowest up, so a sweep at boot queued runs that died at preflight on a 502 (measured, first cloud deploy).
FABRIC_SWEEP_FIRST_S = int(_e("FABRIC_SWEEP_FIRST_S", "180"))
# A change-notification subscription expires (drive subscriptions: ~3 days). The reconciler renews the lab's
# own — those pointing at a receiver on GRAPH_NOTIFICATION_ALLOWLIST — when this much life is left.
FABRIC_RENEW_WITHIN_S = int(_e("FABRIC_RENEW_WITHIN_S", str(2 * 86400)))
FABRIC_DEFAULT_LABEL = _e("FABRIC_DEFAULT_LABEL", "")
