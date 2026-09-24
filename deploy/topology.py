"""The lab's deployment TOPOLOGY — what runs, and with which environment — independent of WHERE.

One definition, two deploy targets: `deploy/railway.py` (development) and `deploy/aca.py`
(production) both render THIS. A role, a workload, a channel or an env allowlist line is added here
once; neither target re-declares it. Pure: no network, no credentials, importable offline.
"""
import fnmatch
import os
import re
import sys
from dataclasses import dataclass
from typing import Callable

REPO = "shlapolosa/local-agent-lab"
BRANCH = "main"
# Defined HERE and not further down: `_head_tag()` runs at IMPORT to pin the image tag, and it reads
# ROOT. It used to be defined 20 lines BELOW that call, so every tag resolution raised NameError into
# a bare `except` and silently fell back to the mutable branch tag — see the note in `_head_tag`.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _head_tag():
    """`sha-<short>` for HEAD — the tag CI publishes alongside the branch tag.

    Default to it, because a MUTABLE `:main` makes "what is deployed" unknowable: the substrate and a
    workload can each pull `:main` at different times and silently run different commits (that is
    exactly how a workload came to call a tool the gateway had renamed). An immutable tag also makes
    rollback a one-word change. Falls back to the branch when git cannot answer (a container, a
    tarball) — and `LAB_IMAGE_TAG` always wins.

    NOT SILENT when it falls back. This function was broken from the day it was written — it reads
    `ROOT`, which was defined twenty lines BELOW the call that runs it at import, so every resolution
    raised NameError into the bare `except` and returned the mutable branch tag. Every service this
    project has ever deployed ran `:main`, and the instrument built to make version skew visible was
    itself invisible. So the fallback now SAYS SO on stderr: a deploy that cannot pin its tag is a
    deploy whose "what is running" is a guess, and that is worth one line of noise.
    """
    try:
        import subprocess
        out = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short=7", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        sha = out.stdout.strip()
        if out.returncode == 0 and sha:
            return f"sha-{sha}"
        why = (out.stderr or "").strip() or f"git exited {out.returncode}"
    except Exception as e:                                  # noqa: BLE001 — deploy must not die on git
        why = f"{type(e).__name__}: {e}"
    print(f"[deploy] cannot pin an immutable image tag ({why}) — falling back to the MUTABLE "
          f"'{BRANCH}'. What each service runs is then whatever it last pulled.",
          file=sys.stderr, flush=True)
    return BRANCH


IMAGE_TAG = os.environ.get("LAB_IMAGE_TAG") or _head_tag()
IMAGE = os.environ.get("LAB_IMAGE") or f"ghcr.io/{REPO}:{IMAGE_TAG}"


REDIS_NAME = "redis"
EMBED_NAME = "embedder"
EMBED_MODEL = "nomic-embed-text"
JAEGER_NAME = "local-agent-lab"   # pre-existing Jaeger service (Docker image; NOT built from our repo)

# --- substrate services: name -> role command, ingress, health ---
SUBSTRATE = {
    "semantic-mcp": {"cmd": "python -m lab.substrate.mcp.semantic.server", "port": None},
    "adoit-mcp":    {"cmd": "python -m lab.substrate.mcp.adoit.server", "port": None},
    # READ-ONLY governed object store. "s3": True = this service (and only such services) receives the
    # bucket credentials (S3_* + UPLOADS_URL); every other service — and every workload — gets none.
    "storage-mcp":  {"cmd": "python -m lab.substrate.mcp.storage.server", "port": None, "s3": True},
    # the front door to every business process (submit/status/result) AND the human-in-the-loop
    # approval gate a run pauses at (approvals_list/get/decide). Redis ONLY: it publishes
    # workflow:requests events, reads their status and appends approval decisions — no store, no
    # bucket, no ADOIT credential.
    "workflow-frontdoor": {"cmd": "python -m lab.substrate.mcp.workflow.server", "port": None},
    # the COLLABORATION port (gateway alias collab_mcp): files and meetings from wherever the
    # organisation collaborates. "s3": True because collab_fetch WRITES what it fetches into the
    # upload store — a meeting recording is streamed there and comes back as an art:// ref, so this
    # is the third holder of bucket credentials alongside storage-mcp (reads) and review (writes).
    # "port": the receiver of change notifications (`/notifications`, exempt from the bearer check) must be
    # reachable from the provider's cloud, so graph-mcp gets a PUBLIC domain; /mcp on it still needs the secret.
    "graph-mcp":    {"cmd": "python -m lab.substrate.mcp.graph.server", "port": 9500, "s3": True},
    # the SPEECH port (gateway alias speech_mcp): a recording becomes timed, speaker-labelled words.
    # "s3": True because it READS the audio out of the upload store and WRITES the segment timeline
    # back as an art:// ref — an hour of speech is never a tool result. It holds the speech
    # credential and nothing else; it publishes no event, so it gets no Redis.
    "speech-mcp":   {"cmd": "python -m lab.substrate.mcp.speech.server", "port": None, "s3": True},
    # No "s3": the reference server never opens an artifact — publication explodes the agent-
    # readable form into rows — so it holds no bucket credential and no ARTIFACTS_URL.
    "reference-mcp": {"cmd": "python -m lab.substrate.mcp.reference.server", "port": None},
    # Pure derivation over facet vectors: no store, no bucket, no database of its own. It reads
    # the governed rules THROUGH reference-mcp (substrate to substrate, on the private network,
    # bearer-authenticated — the stated exception in CLAUDE.md), never from a DSN of its own.
    "decision-mcp": {"cmd": "python -m lab.substrate.mcp.decision.server", "port": None,
                     "env": {"REFERENCE_PROVIDER": "mcp"}},   # the corpus THROUGH reference-mcp: no DSN here
    # The FINANCIAL derivations, split from decision-mcp by artifact OWNER: finance releases the
    # price sheet and the rate cards, and must not need architecture governance's redeploy.
    "valuation-mcp": {"cmd": "python -m lab.substrate.mcp.valuation.server", "port": None,
                      "env": {"REFERENCE_PROVIDER": "mcp"}},
    # What makes FR-12 structural: the architect's decision is the EVENT that releases the
    # submitter's message, so there is no code path where the submitter hears first.
    "usecase-notifier": {"cmd": "python -m lab.substrate.usecase_notifier", "port": None},
    # what turns "a human approved" into "the next run started". Redis ONLY: it reads the decisions
    # stream and publishes a workflow request, holds no credential of any kind, and has no ingress.
    "continuations": {"cmd": "python -m lab.substrate.continuations", "port": None},
    # what tells a meeting its minutes exist — Redis and one webhook, nothing else
    "meeting-notifier": {"cmd": "python -m lab.substrate.meeting_notifier", "port": None},
    # The Documentation Fabric's three substrate consumers (docs/fabric/POC.md). Ingress: finished runs and
    # change events -> artifact_intake requests (Redis only). Projector: a published record -> one wiki page,
    # through the gateway with the fabric's substrate identity. Reconciler: a timer sweep of the allow-listed
    # drives against the catalog -> change events, so a missed notification is said later.
    "fabric-ingress":    {"cmd": "python -m lab.substrate.fabric_ingress", "port": None},
    "fabric-projector":  {"cmd": "python -m lab.substrate.fabric_projector", "port": None},
    "fabric-reconciler": {"cmd": "python -m lab.substrate.fabric_reconciler", "port": None},
    "gateway":      {"cmd": "litellm --config config/litellm-config.yaml --host 0.0.0.0 --port 4000 --num_workers 1",
                     "port": 4000,   # NOTE: deliberately NO "health" key — see below.
                     # --host 0.0.0.0 + NO healthcheck: the verified working combo (health 200, 7 models).
                     # Railway uses TWO different network paths to a container: the PUBLIC edge reaches it
                     # over IPv4, but the HEALTHCHECK probes over IPv6. uvicorn binds a single stack, so
                     # neither single choice satisfies both: `--host ::` is IPv6-only (healthcheck could
                     # pass, but the IPv4 public edge 502s — every request did), and `--host 0.0.0.0` is
                     # IPv4-only (public edge works, but the IPv6 healthcheck can't connect and Railway
                     # kills the deploy). Fix = bind 0.0.0.0 for the public edge AND set no healthcheckPath
                     # so the IPv6 probe never runs. Nothing internal calls the gateway (workloads use its
                     # public URL), so IPv4-only inbound is fine; its OUTBOUND calls to the MCP servers over
                     # private IPv6 DNS are unaffected by its own bind. (streamlit's :: happens to dual-stack,
                     # which is why review works on :: — uvicorn does not.) Do NOT set a manual PORT var
                     # either: forcing PORT=4000 also broke edge routing (verified). DISABLE_SCHEMA_UPDATE:
                     # Neon is already migrated by the native bootstrap; skip the ~152-migration cold-start
                     # replay a fresh container otherwise runs against remote Neon.
                     "env": {"OTEL_SERVICE_NAME": "litellm-gateway", "DISABLE_SCHEMA_UPDATE": "true"}},
    "review":       {"cmd": "streamlit run src/lab/substrate/review/app.py --server.port 8501 "
                            "--server.address :: --server.headless true", "port": 8501,
                     "s3": True,    # the Submit page writes uploads DIRECT to the bucket (trusted substrate component)
                     "env": {"REFERENCE_PROVIDER": "mcp"}},   # the corpus THROUGH reference-mcp: no reader DSN
}
S3_KEYS = ("S3_ENDPOINT", "S3_REGION", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_URL_STYLE", "UPLOADS_URL")

# --- approval CHANNELS: substrate services deployed ONLY when they are configured ----------------
# A channel is another consumer group on `approvals:requests` (same contract as the review app): it
# notifies a human where they already are and records the decision. It is deployed only when its
# settings are in the deploy profile, because an unconfigured channel exits immediately by design —
# `lab.sh` skips it for exactly the same reason. Long-lived loop -> restartPolicyType ALWAYS; no
# port -> no public domain, nothing calls it. A channel holds NO store, bucket or gateway credential
# (ROLE_ENV below): its own webhook/token, Redis, and the link(s) it puts in front of the human.
CHANNELS = {
    "telegram": {"cmd": "python -m lab.substrate.channels.telegram", "port": None, "restart": "ALWAYS",
                 "requires": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")},
    "teams":    {"cmd": "python -m lab.substrate.channels.teams", "port": None, "restart": "ALWAYS",
                 "requires": ("TEAMS_WEBHOOK_URL",)},
}


def substrate_services(base_env: dict) -> dict:
    """The substrate table for THIS deploy: the fixed roles plus every channel whose settings are in
    `base_env`. Pure — `up`, `status` and `env` all read it, so a configured channel is deployed,
    audited and torn down like any other service, and an unconfigured one is never created."""
    return {**SUBSTRATE, **{n: s for n, s in CHANNELS.items()
                            if all(base_env.get(k) for k in s["requires"])}}


def deploy_profile() -> dict:
    """The deploy profile when there is a `.env` to read, else {}. `down`/`status` never needed `.env`
    before channels made the service list depend on it — with {} a channel is still covered whenever
    it is deployed, so a box that only exports the Railway credentials can still inspect and tear
    down the substrate."""
    return load_env_for_cloud() if os.path.exists(os.path.join(ROOT, ".env")) else {}


def embedder_enabled(base_env: dict) -> bool:
    """The substrate runs its OWN embedding model only while the corpus embeds with it. Since 12 Sep
    2026 the corpus embeds with a vendor model through the gateway (REFERENCE_EMBED_MODEL names it),
    and an idle ollama box is metered for nothing — so the profile decides, the same way a channel's
    settings decide whether the channel is deployed. Unset means the substrate's own, as before."""
    return base_env.get("REFERENCE_EMBED_MODEL", EMBED_MODEL) in ("", EMBED_MODEL)


def substrate_names(base_env: dict, ids: dict | None = None) -> list[str]:
    """Service names the substrate owns, in deploy order (redis first, jaeger last). A channel — and
    the embedder — is included when it is configured OR already deployed, so `down`/`status` still
    see one whose settings have since changed in `.env`, instead of orphaning it."""
    table = substrate_services(base_env)
    chans = [n for n in CHANNELS if n in table or n in (ids or {})]
    embed = [EMBED_NAME] if embedder_enabled(base_env) or EMBED_NAME in (ids or {}) else []
    return [REDIS_NAME] + embed + list(SUBSTRATE) + chans + [JAEGER_NAME]

# --- how a service is ADDRESSED: the one thing that differs between deploy targets -------------------
# Every server's listen port. A target turns (service, port) into a URL its own network routes: Railway
# private DNS names the port; a Container Apps ingress listens on 80 and forwards to the port.
SERVICE_PORTS = {
    "adoit-mcp": 9100, "semantic-mcp": 9200, "storage-mcp": 9300, "workflow-frontdoor": 9400,
    "graph-mcp": 9500, "speech-mcp": 9600, "reference-mcp": 9700, "decision-mcp": 9800,
    "valuation-mcp": 9900, "gateway": 4000, "review": 8501,
}
EMBED_PORT = 11434


@dataclass(frozen=True)
class Network:
    """A deploy target's private network: where a server binds, and the base URL of (service, port)."""
    bind_host: str
    address: Callable[[str, int], str]


# IPv6 for Railway private networking; *.railway.internal resolves only there.
RAILWAY_NET = Network(bind_host="::", address=lambda svc, port: f"http://{svc}.railway.internal:{port}")


def substrate_env(name, spec, base_env, net: Network) -> dict:
    """The exact variables substrate service `name` receives: the substrate coordinates (addressed on
    `net`) layered on the profile pool, then the role allowlist (S3_KEYS only for services flagged
    "s3"), then the service's own fixed overrides. Pure — used by `up` (to upsert) and `env` (to audit)."""
    at = lambda svc, path="": net.address(svc, SERVICE_PORTS.get(svc, EMBED_PORT)) + path   # noqa: E731
    env = dict(base_env)
    env["BIND_HOST"] = net.bind_host
    env["ADOIT_MCP_URL"] = at("adoit-mcp", "/mcp")
    env["SEMANTIC_MCP_URL"] = at("semantic-mcp", "/mcp")
    env["STORAGE_MCP_URL"] = at("storage-mcp", "/mcp")
    env["WORKFLOW_MCP_URL"] = at("workflow-frontdoor", "/mcp")
    env["GRAPH_MCP_URL"] = at("graph-mcp", "/mcp")
    env["SPEECH_MCP_URL"] = at("speech-mcp", "/mcp")
    env["REFERENCE_MCP_URL"] = at("reference-mcp", "/mcp")
    env["DECISION_MCP_URL"] = at("decision-mcp", "/mcp")
    env["VALUATION_MCP_URL"] = at("valuation-mcp", "/mcp")
    env["WORKFLOW_API_URL"] = at("workflow-frontdoor", "/api")
    env["GATEWAY_URL"] = at("gateway")
    # The relevance stores' provider (litellm-config.yaml vector_store_registry): an ORIGIN — the
    # client appends /v1/vector_stores/<id>/search — and the bearer reference-mcp expects.
    env["PG_VECTOR_API_BASE"] = at("reference-mcp")
    env["PG_VECTOR_API_KEY"] = env.get("MCP_SHARED_SECRET", "")
    env["EMBED_URL"] = at(EMBED_NAME)                       # the gateway's embedding model
    env = env_for_role(name, env, s3=bool(spec.get("s3")))  # bucket credentials: only services flagged "s3"
    env.update(spec.get("env", {}))
    return env


# --- per-role environment ALLOWLIST (least privilege; review B-H2) ---
# A service receives ONLY the `.env` keys (after `# CLOUD:` override + $VAR expansion, plus the
# coordinates configure() layers on) that match its role's glob patterns — nothing is popped from
# a full copy any more. Derived from the code that READS env in each role (cited per line); when a
# role starts reading a new variable, add it here in the same change, or the container won't see
# it. This table is also the Azure Container Apps secret-scope map (which Key Vault refs each app
# gets). The bucket credentials (S3_KEYS) are NOT listed anywhere here on purpose: they are granted
# solely by a service's `"s3": True` flag (review + storage-mcp + graph-mcp), which env_for_role() adds.
_OTLP = "OTEL_EXPORTER_OTLP_*"                     # every Python role: lab.platform.otel.tracer reads OTEL_EXPORTER_OTLP_ENDPOINT
ROLE_ENV = {
    "gateway": [                                   # litellm + gateway/{custom_auth,auto_router,pii_guardrail}.py
        "LITELLM_*",                               # master key, LITELLM_MCP_CLIENT_TIMEOUT / TOOL_LISTING_TIMEOUT (litellm env)
        "DATABASE_URL",                            # key/team/spend store (litellm)
        "OLLAMA_API_KEY", "ANTHROPIC_UPSTREAM_API_KEY",   # litellm-config.yaml os.environ/ refs; auto_router.py
        "OPENAI_UPSTREAM_API_KEY",                 # ... the vendor embedding model (text-embedding-3-large)
        "AZURE_FOUNDRY_*",                         # ... production's models (config/litellm-models.azure.yaml)
        "EMBED_URL",                               # ... the corpus's embedding model, the substrate's own (set by substrate_env)
        "PG_VECTOR_API_BASE", "PG_VECTOR_API_KEY",  # the vector_store_registry's provider reads THESE from the
                                                   # process env (LiteLLM resolves no os.environ/ on that path):
                                                   # reference-mcp's origin + MCP_SHARED_SECRET, set by substrate_env()
        "MCP_SHARED_SECRET",                       # litellm-config.yaml mcp_servers authentication_token
        "ADOIT_MCP_URL", "SEMANTIC_MCP_URL", "STORAGE_MCP_URL", "WORKFLOW_MCP_URL",   # mcp_servers url (set by configure(), private DNS)
        "GRAPH_MCP_URL", "SPEECH_MCP_URL",         # ... incl. the collab_mcp and speech_mcp aliases' services
        "REFERENCE_MCP_URL", "DECISION_MCP_URL", "VALUATION_MCP_URL",   # ... the governed corpus and the derivations
        "WORKFLOW_API_URL",                        # the front door's REST ingress, which the gateway
                                                   # pass-through forwards to. Authorised HERE, not there:
                                                   # the pass-through replaces the caller's Authorization,
                                                   # so identity does not survive the hop (lab.substrate.
                                                   # apipolicy + custom_auth). Hence the ENTRA_* below are
                                                   # load-bearing for /api, not only for agent auth.
        "REDIS_URL",                               # custom_auth.py; litellm falls back to it when REDIS_HOST/PORT/
                                                   # PASSWORD are absent (verified) — those three stay OUT (unchanged
                                                   # from the old drop-set; the cloud Redis has no password)
        "OTEL_*",                                  # OTEL_EXPORTER / OTEL_ENDPOINT / OTEL_SERVICE_NAME (litellm otel callback)
        "ENTRA_TENANT_ID", "ENTRA_GATEWAY_AUDIENCE", "ENTRA_CLIENT_TO_KEY", "DEVELOPERS_TEAM_ID",   # custom_auth.py
        "MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET", "MICROSOFT_TENANT", "PROXY_BASE_URL",     # litellm UI SSO
        "DISABLE_SCHEMA_UPDATE",                   # spec env (see SUBSTRATE["gateway"])
    ],
    "adoit-mcp": [                                 # src/lab/substrate/mcp/adoit/{server,adoit_rest}.py + lab.substrate.{approvals,artifacts,mcpauth} + lab.platform.config
        "ADOIT_BASE_URL", "ADOIT_USERNAME", "ADOIT_PASSWORD", "ADOIT_REPO_ID",   # ADOIT REST credentials (this role ONLY)
        "ADOIT_REST_WRITE",                        # config.ADOIT_REST_WRITE write-path toggle
        "MCP_SHARED_SECRET", "BIND_HOST", "ADOIT_MCP_PORT",   # mcpauth bearer; uvicorn bind
        "REDIS_URL",                               # approvals.request() (adoit_request_import)
        "ARTIFACTS_URL", "DATABASE_URL",           # artifacts.store() (renders -> art:// refs; DATABASE_URL is config's fallback)
        "REVIEW_APP_URL",                          # tool results link the reviewer to the review app
        _OTLP, "REFERENCE_MODELS_DIR",             # tracing; src/lab/core/semantic/reference/baguild.py workbook dir (optional)
    ],
    "semantic-mcp": [
        # The licensed reference workbooks, BY REFERENCE — they cannot be in a public image.
        "REFERENCE_MODELS_REFS",                              # src/lab/substrate/mcp/semantic/server.py — credential-free, read-only
        "MCP_SHARED_SECRET", "BIND_HOST", "SEMANTIC_MCP_PORT",
        "ARTIFACTS_URL", "DATABASE_URL",           # semantic_store_spec / semantic_export_archimate write spec refs
        "FABRIC_DB_URL",                           # the fabric's catalog tables (falls back to DATABASE_URL)
        "REDIS_URL",                               # rung_store: the index of the latest rung-graph refs + the single-writer lock.   # + fabric:metrics, the numbers semantic_metrics answers with
                                                   # Missing here = boot() crashes on 127.0.0.1:6379 (measured, first cloud deploy)
        "GATEWAY_URL", "REFERENCE_EMBED_MODEL", "REFERENCE_EMBED_DIM", "REFERENCE_EMBED_KEY",   # the fabric's index posts to the gateway
        _OTLP, "REFERENCE_MODELS_DIR",
    ],
    "storage-mcp": [                               # src/lab/substrate/mcp/storage/server.py + lab.substrate.artifacts + lab.platform.docparse — READ-ONLY upload store
        "MCP_SHARED_SECRET", "BIND_HOST", "STORAGE_MCP_PORT",
        "ARTIFACTS_URL", "DATABASE_URL",           # config.UPLOADS_URL falls back to ARTIFACTS_URL when no bucket is configured
        "BA_MAX_*",                                # docparse.py size limits (BA_MAX_DOC_CHARS, BA_MAX_EMBEDDED_IMAGES)
        _OTLP,
    ],                                             # + S3_KEYS via the "s3" flag (the only writer/reader pair of the bucket)
    "workflow-frontdoor": [                              # src/lab/substrate/mcp/workflow/{server,approval_tools}.py + lab.substrate.approvals + lab.platform.{workflows,contracts} — Redis ONLY
        "MCP_SHARED_SECRET", "BIND_HOST", "WORKFLOW_MCP_PORT",
        "REDIS_URL",                               # workflows.request/status + approvals streams — the ONLY backend it holds
        "REVIEW_APP_URL", "JAEGER_UI_URL",         # approval_tools.py: the two LINKS a reviewer follows
        "SPEECH_LANES",                            # which lanes a submission fans out into. The fan-out
                                                   # happens HERE (rest.py + server.py, via
                                                   # workflows.lanes_for); unset means one run, which
                                                   # looks exactly like a working single-provider lab
        _OTLP,                                     # (addresses, not credentials). Deliberately NO
    ],                                             # ARTIFACTS_URL/DATABASE_URL/UPLOADS_URL/S3_*: refs are never dereferenced here
    "graph-mcp": [                                 # src/lab/substrate/mcp/graph/*.py + lab.substrate.{artifacts,container,mcpauth} + lab.core.collab — the COLLABORATION adapter
        "MCP_SHARED_SECRET", "BIND_HOST",          # mcpauth bearer; uvicorn bind
        "REDIS_URL", "FABRIC_EVENTS", "FABRIC_NOTIFY_CLIENT_STATE",   # notifications.py: a change notification -> fabric:events
        "GRAPH_*",                                 # GRAPH_MCP_PORT + the adapter's own settings: client id/secret,
                                                   # base url, auth mode, meeting user(s), fetch ceiling,
                                                   # notification allow-list, metered switch (graph_auth/graph_repository)
        "COLLAB_PROVIDER", "ENTRA_TENANT_ID",      # which adapter the container wires; the app-only token's authority
        "ARTIFACTS_URL",                           # config.UPLOADS_URL falls back to it when no bucket is configured.
                                                   # Deliberately NOT DATABASE_URL (the LiteLLM key/spend store's DSN):
                                                   # ARTIFACTS_URL is already the expanded value, so the fallback needs
                                                   # only the one key — this role never reaches the registry database.
        _OTLP,                                     # NO Redis either: it publishes no event and holds no approval
    ],                                             # + S3_KEYS via the "s3" flag (collab_fetch streams INTO the upload store)
    "usecase-notifier": [                          # src/lab/substrate/usecase_notifier.py — Redis + one webhook
        "REDIS_*",                                 # the decisions stream it consumes
        "USECASE_WEBHOOK_URL",                     # where a submitter is told; unset = it logs instead
        "JAEGER_UI_URL",                           # the link it puts in the message
        _OTLP,
    ],
    "valuation-mcp": [                             # src/lab/substrate/mcp/valuation/*.py + lab.core.usecase — the cost JOIN
        "MCP_SHARED_SECRET", "BIND_HOST",          # mcpauth bearer; uvicorn bind
        "VALUATION_MCP_PORT",                      # which port it serves
        "REFERENCE_MCP_URL", "REFERENCE_RING", "REFERENCE_PROVIDER",   # the price catalogue, read THROUGH
                                                   # reference-mcp under the caller's pin — no DSN, no
                                                   # packaged sheet: the spec env sets the provider to mcp
        _OTLP,                                     # NO store, NO database, NO model credential
    ],
    "decision-mcp": [                              # src/lab/substrate/mcp/decision/*.py + lab.core.usecase — pure derivation
        "MCP_SHARED_SECRET", "BIND_HOST",          # mcpauth bearer; uvicorn bind
        "DECISION_MCP_PORT",                       # which port it serves
        # NAMED, not `REFERENCE_*`: the glob would also match REFERENCE_SIGNING_KEY and
        # REFERENCE_PUBLISH_DB_URL. Neither is in `.env` today, so the private seed staying out of
        # every container rested on nobody adding a line — which is the shape of guarantee this
        # whole file exists to replace.
        "REFERENCE_MCP_URL", "REFERENCE_RING", "REFERENCE_PROVIDER",   # the corpus THROUGH reference-mcp
                                                   # (spec env: provider mcp), never a DSN of its own
        _OTLP,
    ],
    "reference-mcp": [                             # src/lab/substrate/{reference,mcp/reference}/*.py + lab.core.reference — the governed CORPUS
        "MCP_SHARED_SECRET", "BIND_HOST",          # mcpauth bearer; uvicorn bind
        "REFERENCE_MCP_PORT", "REFERENCE_PROVIDER",  # which port it serves; which adapter the container wires
        "REFERENCE_DB_URL",                        # the READER dsn — never DATABASE_URL, which can write
        "REFERENCE_RING", "REFERENCE_PIN_TTL_S",   # which audience it resolves for; how long a pin lives
        "REFERENCE_TRUST_KEYS",                    # PUBLIC key material only; the signing seed stays with the operator
        "REFERENCE_EMBED_MODEL", "REFERENCE_EMBED_DIM", "REFERENCE_EMBED_KEY",  # embed via the GATEWAY, virtual key
        "GATEWAY_URL",                             # ... which is where the embedder posts
        _OTLP,
    ],
    "speech-mcp": [                                # src/lab/substrate/mcp/speech/*.py + lab.substrate.{artifacts,container,mcpauth} + lab.core.speech — the SPEECH adapter
        "MCP_SHARED_SECRET", "BIND_HOST",          # mcpauth bearer; uvicorn bind
        "SPEECH_MCP_PORT", "SPEECH_PROVIDER",      # which port it serves; which adapter the container wires
        # EVERY provider's credential, because this service can be asked for ANY registered one —
        # that is what a lane is. A key stripped here does not error: the adapter reports
        # SpeechNotConfigured, the lane is skipped by name, and a four-provider comparison quietly
        # returns one provider's answer while every service reports healthy.
        "MUNSIT_*", "ELEVENLABS_*", "ASSEMBLYAI_*", "SONIOX_*",
        "AUDIO_EXTRACT_BIN",                       # the host tool that pulls audio out of a video recording;
                                                   # unset = video refused with a sentence, audio still works
        "ARTIFACTS_URL",                           # config.UPLOADS_URL falls back to it when no bucket is set.
                                                   # NOT DATABASE_URL: this role never reaches the registry database.
        _OTLP,                                     # NO Redis: it publishes no event and holds no approval.
    ],                                             # + S3_KEYS via the "s3" flag (reads the audio, writes the timeline)
    "continuations": [                             # src/lab/substrate/continuations.py + lab.substrate.approvals + lab.platform.workflows
        "REDIS_URL",                               # the approvals:decisions group + workflow:requests
        "REVIEW_APP_URL",                          # printed on start so an operator can find the gate
        "GATEWAY_URL", "FABRIC_CURATOR_KEY",       # fabric_curator: a person's fabric decision applied at rung H
        _OTLP,                                     # NOTHING else: no store, no bucket, no model and no
    ],                                             # provider credential. It cannot read what it releases.
    "fabric-ingress": [                            # src/lab/substrate/fabric_ingress.py + lab.platform.{fabric_events,workflows,delivery} — Redis ONLY
        "REDIS_URL", "FABRIC_EVENTS", "FABRIC_ALLOWLIST",
        _OTLP,                                     # no store, no gateway, no credential: it reads run state and events, and submits requests
    ],
    "fabric-projector": [                          # src/lab/substrate/fabric_projector.py — a published record becomes a wiki page
        "REDIS_URL", "GATEWAY_URL", "FABRIC_CURATOR_KEY", "FABRIC_WIKI_FOLDER",
        _OTLP,                                     # reads the record and writes the page THROUGH the gateway; no store credential
    ],
    "fabric-reconciler": [                         # src/lab/substrate/fabric_reconciler.py — the timer sweep of the allow-listed drives
        "REDIS_URL", "GATEWAY_URL", "FABRIC_CURATOR_KEY", "FABRIC_EVENTS", "FABRIC_ALLOWLIST", "FABRIC_SWEEP_*",
        "FABRIC_WIKI_FOLDER",   # the measurements page (fabric_metrics.tick) lands beside the record pages
        _OTLP,
    ],
    "meeting-notifier": [       # src/lab/substrate/meeting_notifier.py + lab.platform.workflows — Redis ONLY
        "REDIS_URL",            # the finished-runs stream it consumes
        "MEETING_WEBHOOK_URL",  # where it POSTs. Unset = it logs what it would say
        _OTLP,                  # NO store, NO Graph credential, NO gateway: it reads run state and
    ],                          # posts ids and links. It never opens an artifact it announces.
    "review": [                                    # src/lab/substrate/review/app.py + lab.substrate.{approvals,artifacts} + lab.platform.{workflows,runlog,config}
        "REVIEW_APP_PASSWORD",                     # config.REVIEW_APP_PASSWORD gate
        "REDIS_URL",                               # approvals / workflows / runlog streams
        "ARTIFACTS_URL", "DATABASE_URL",           # reads xml/svg refs of a request
        "JAEGER_UI_URL",                           # trace links
        "REFERENCE_PROVIDER", "REFERENCE_MCP_URL", "REFERENCE_RING", "MCP_SHARED_SECRET",   # the Submit form's
                                                   # intake groups, read from the corpus THROUGH reference-mcp under
                                                   # a pin — never the LiteLLM DSN it holds for artifacts
    ],                                             # + S3_KEYS via the "s3" flag (Submit page uploads straight to the bucket)
    "telegram": [                                  # src/lab/substrate/channels/telegram.py + lab.substrate.approvals + lab.platform.config
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",  # the Bot API credential + target chat (unset = not deployed)
        "REDIS_URL",                               # approvals:requests consumer group "telegram" + decisions
        "REVIEW_APP_URL",                          # the link the message sends the human to for the diagrams
        _OTLP,                                     # tracing sink: an ADDRESS, not a credential. A channel builds no
                                                   # tracer today (nothing in its import graph does) — it is granted so
                                                   # that emitting spans from a channel is a code change, not a deploy one
    ],                                             # NOTHING else: no store, no bucket, no gateway/ADOIT secret
    "teams": [                                     # src/lab/substrate/channels/teams.py + lab.substrate.approvals + lab.platform.config
        "TEAMS_WEBHOOK_URL",                       # outbound Adaptive Card webhook (unset = not deployed)
        "REDIS_URL",                               # approvals:requests consumer group "teams" + decisions
        "REVIEW_APP_URL", "JAEGER_UI_URL",         # the card's two Action.OpenUrl buttons
        _OTLP,
    ],
    # What EVERY workload needs, and nothing more. A workload reaches the substrate only through the
    # gateway, Redis and tracing — the same seam as Container Apps -> APIM. Anything process-specific
    # (its agents' credentials, its own settings) belongs in WORKLOAD_ENV below, not here: one shared
    # list meant the meeting workload was handed the visio agents' client secrets, which is exactly
    # the blast radius this table exists to prevent.
    "workload": [                                  # src/lab/workloads/* + lab.workloads.identity + lab.platform.{workflows,runlog,docparse}
        "GATEWAY_URL",                             # the ONLY substrate coordinate (LLM + MCP via the gateway)
        "REVIEW_APP_URL", "JAEGER_UI_URL",         # reported to the human (host.py prints; consumer writes back)
        "REDIS_URL",                               # workflows.py (consume requests) + runlog.py (live node status)
        _OTLP,                                     # lab.platform.otel.tracer; service name is set in code, not from env
        "ENTRA_TENANT_ID", "ENTRA_GATEWAY_AUDIENCE",   # identity.py MSAL authority + scope
        "AGENT_*",                                 # agents.py: AGENT_RESPONSES_STORE / REQUEST_TIMEOUT / MAX_RETRIES / MAX_OUTPUT_TOKENS
        "WF_CONSUMER",                             # consumer.py replica name (spec env)
    ],
    # image services built from nothing in this repo: they get NO .env keys at all
    "redis": [],
    "embedder": [],                                # the embedding model: an image, no env, no secret
    "jaeger": [],
}


# What ONE workload needs on top of the shared list — its agents' credentials and its own settings.
# Adding a process means adding a row here; an unlisted prefix is SILENTLY dropped in the cloud, which
# is the failure this table is named after.
WORKLOAD_ENV: dict[str, list[str]] = {
    "visio": [
        "BA_*", "ARCHITECT_*",                     # identity.agent_headers(): <PREFIX>_CLIENT_ID/SECRET/KEY;
                                                   # BA_MODE, BA_RUN_TIMEOUT, BA_MAX_* (docparse), ARCHITECT_MODE
        "VISIO_AGENT_MODEL", "VISIO_DIAGRAM", "VISIO_REQUIREMENTS",   # model; cloud-job inputs
    ],
    "usecase-screening": [
        "USECASE_AGENT_*",                         # identity.agent_headers(): CLIENT_ID/SECRET/KEY
        "AGENT_*",                                 # responses-store toggle, timeouts, caps
    ],
    "usecase-design": [
        "USECASE_AGENT_*",
        "AGENT_*",
    ],
    "usecase-investment": [                        # a DIFFERENT identity: its grants carry the write
        "USECASE_DELIVERY_*",                      # path, and one workload never holds another's
    ],
    "usecase-provisioning": [
        "USECASE_DELIVERY_*",
    ],
    "minutes": [
        "MINUTES_*",                               # identity.agent_headers(): MINUTES_AGENT_CLIENT_ID/
                                                   # SECRET/KEY, and MINUTES_AGENT_MODEL. This process
                                                   # writes the minutes with OUR model, so it needs an
                                                   # LLM identity where the transcription one does not.
        "AGENT_*",                                 # agents.py: responses-store toggle, timeouts, caps
    ],
    "fabric-intake": [
        "CLASSIFIER_AGENT_*", "SYNTHESIS_AGENT_*", # two identities: the classifier SUGGESTS (and carries the tool
                                                   # calls), the synthesiser WRITES tagged drafts
        "FABRIC_AGENT_MODEL", "FABRIC_ASSOCIATION_THRESHOLD", "FABRIC_DEFAULT_LABEL",
        "AGENT_*",
    ],
    "artifact-publish": [
        "PUBLISH_AGENT_*",                         # its OWN tool-only identity (team fabric-publish)
    ],
    "meeting": [
        "MEETING_*",                               # MEETING_AGENT_CLIENT_ID/SECRET/KEY, and MEETING_LANGUAGES —
                                                   # the language HINT that selects a model able to transcribe
                                                   # speech switching language mid-sentence.
    ],
}
# The one-shot job runs the SAME process as its long-lived twin, so it gets the same allowlist —
# declared rather than defaulted, because "unknown workload" must stay an error.
WORKLOAD_ENV["visio-job"] = WORKLOAD_ENV["visio"]


def env_for_role(role: str, base: dict, s3: bool = False, workload: str | None = None) -> dict:
    """Select from `base` (parsed .env + layered coordinates) exactly the keys ROLE_ENV[role]
    allows, plus S3_KEYS iff the service is flagged `s3`, plus WORKLOAD_ENV[workload] for a workload
    role. Unknown role -> KeyError (never ship a full env by accident). Empty values are dropped
    (Railway would store them as empty strings)."""
    pats = list(ROLE_ENV[role]) + (list(S3_KEYS) if s3 else [])
    if workload is not None:
        pats += list(WORKLOAD_ENV[workload])       # KeyError on an unregistered process, deliberately
    return {k: v for k, v in base.items()
            if v != "" and any(fnmatch.fnmatchcase(k, p) for p in pats)}


def _print_env_keys(label: str, env: dict):
    """Audit line: the exact key names (never values) a service receives."""
    print(f"  {label:13} env ({len(env)}): {', '.join(sorted(env))}")


def _value(v: str) -> str:
    """One .env value the way the shell sees it: a quoted value keeps everything inside the quotes
    (a `#` in JSON is data); an unquoted one loses a trailing inline note ("value   # note") — a
    URL once shipped WITH its note because Railway passes values verbatim."""
    v = v.strip()
    if v[:1] in ("'", '"'):
        return v.strip("'\"")
    return re.sub(r"\s+#.*$", "", v).strip()


def parse_env(path: str | None = None, cloud: bool = True, overlay: str | None = None) -> dict:
    """KEY=value from .env. `cloud=True` (the deploy profile) lets `# CLOUD: KEY=value` comment
    lines WIN over the active machine-local ones; `cloud=False` reads the active lines only (what
    `source .env` gives a local process). Either way `$VAR` / `${VAR}` refs are expanded against
    the parsed values — the shell does this on `source .env`, but Railway passes values verbatim,
    so e.g. ARTIFACTS_URL=$DATABASE_URL would otherwise reach the container as the literal
    "$DATABASE_URL" (psycopg: missing "=" ...). Two passes resolve one level of chaining; unknown
    refs are left untouched. Selection per service is NOT done here — see env_for_role()."""
    active, overrides = {}, {}
    for raw in open(path or os.path.join(ROOT, ".env")):
        line = raw.rstrip("\n")
        m = re.match(r"# CLOUD:\s*([A-Z0-9_]+)=(.*)$", line)
        if m:
            # drop a trailing inline comment first, then quotes (unchanged CLOUD-line semantics)
            overrides[m.group(1)] = re.sub(r"\s+#.*$", "", m.group(2)).strip().strip("'\"")
            continue
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if re.match(r"^[A-Z0-9_]+$", k):
            active[k] = _value(v)
    if cloud:
        active.update(overrides)                           # cloud values override local
    if overlay:
        # A TARGET's own profile (production's `.env.azure`): plain KEY=value lines that win over the
        # cloud profile. Merged BEFORE expansion, so `ARTIFACTS_URL=$DATABASE_URL` follows an overridden
        # DATABASE_URL; an empty value survives here and is dropped by load_env_for_cloud, which is how
        # an overlay takes a dev-only credential (the Railway bucket) OUT of the pool.
        for raw in open(overlay):
            line = raw.rstrip("\n")
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if re.match(r"^[A-Z0-9_]+$", k.strip()):
                active[k.strip()] = _value(v)

    def expand(v):
        return re.sub(r"\$\{?([A-Z_][A-Z0-9_]*)\}?", lambda m: active.get(m.group(1), m.group(0)), v)
    for _ in range(2):
        active = {k: expand(v) for k, v in active.items()}
    return active


def load_env_for_cloud(path: str | None = None, overlay: str | None = None) -> dict:
    """The deploy profile of .env (`# CLOUD:` wins, $VAR expanded, empty values dropped). This is
    the POOL a service is selected from — env_for_role() decides what each one actually gets, so
    management keys (RAILWAY_*, NEON_*, OCI_*, provisioning ids) never ship without a drop-list."""
    return {k: v for k, v in parse_env(path, cloud=True, overlay=overlay).items() if v != ""}


# --- workloads: each business process is its OWN service, deployed independently ON the substrate ---
# The two-tier contract: a workload reaches the substrate ONLY through the gateway's PUBLIC domain
# plus the shared Redis (streams) and the tracing sink from .env — see ROLE_ENV["workload"]; never
# Neon, the bucket, the MCP servers (internal to the substrate) or another workload; cross-workflow coupling goes via events
# (Redis Streams) or A2A through the gateway. The public URL is the door by design (and the gateway
# binds IPv4 — see SUBSTRATE — so its *.railway.internal name would not be reachable anyway).
WORKLOADS = {
    # The normal cloud shape: a LONG-LIVED host that consumes `workflow:requests` (published by the
    # review app's Submit page) and runs the workflow per event. Inputs arrive as art:// refs and are
    # read through the gateway's storage-mcp; this container holds no store credentials.
    "visio": {
        "service": "wf-visio",
        "cmd": "python -m lab.workloads.visio_to_archimate.consumer",
        "restart": "ALWAYS",
        "env": {"AGENT_RESPONSES_STORE": "false", "WF_CONSUMER": "1"},
        "markers": ("consumer ready", "request "),   # what workload_status reads from the logs
    },
    "meeting": {
        "service": "wf-meeting-transcript",
        "cmd": "python -m lab.workloads.meeting_to_transcript.consumer",
        "restart": "ALWAYS",
        "env": {"WF_CONSUMER": "1"},
        "markers": ("consumer ready", "request "),
        # TWO, because this is the workload SPEECH_LANES fans out: lanes submitted together would
        # otherwise queue behind each other in one process, and a provider that HANGS rather than
        # fails blocks the rest for its whole 900 s timeout. Two replicas halve that exposure and
        # cost one more small container. Not one per lane — the point is to overlap the slow part
        # (the provider call), not to hold every recording in memory at once — and deliberately NOT
        # re-raised when a lane was added: four lanes over two replicas is two rounds of the slow
        # part, which is the cost the shape is meant to bound, not a regression in it.
        "replicas": 2,
    },
    # Started by the continuation runner when an organiser answers, not normally by a person.
    "usecase-screening": {
        "service": "wf-usecase-screening",
        "cmd": "python -m lab.workloads.use_case_screening.consumer",
        "restart": "ALWAYS",
        "env": {"AGENT_RESPONSES_STORE": "false", "WF_CONSUMER": "1"},
        "markers": ("consumer ready", "request "),
    },
    "usecase-design": {
        "service": "wf-usecase-design",
        "cmd": "python -m lab.workloads.use_case_design.consumer",
        "restart": "ALWAYS",
        "env": {"AGENT_RESPONSES_STORE": "false", "WF_CONSUMER": "1"},
        "markers": ("consumer ready", "request "),
    },
    "usecase-investment": {
        "service": "wf-usecase-investment",
        "cmd": "python -m lab.workloads.use_case_investment.consumer",
        "restart": "ALWAYS",
        "env": {"WF_CONSUMER": "1"},
        "markers": ("consumer ready", "request "),
    },
    "usecase-provisioning": {
        "service": "wf-usecase-provisioning",
        "cmd": "python -m lab.workloads.use_case_provisioning.consumer",
        "restart": "ALWAYS",
        "env": {"WF_CONSUMER": "1"},
        "markers": ("consumer ready", "request "),
    },
    # The Documentation Fabric's two hosts. Intake is started ONLY by fabric-ingress (external=False);
    # publish ONLY by the continuation runner when an owner approves the record's review.
    "fabric-intake": {
        "service": "wf-fabric",
        "cmd": "python -m lab.workloads.artifact_intake.consumer",
        "restart": "ALWAYS",
        "env": {"AGENT_RESPONSES_STORE": "false", "WF_CONSUMER": "1"},
        "markers": ("consumer ready", "request "),
    },
    "artifact-publish": {
        "service": "wf-artifact-publish",
        "cmd": "python -m lab.workloads.artifact_publish.consumer",
        "restart": "ALWAYS",
        "env": {"WF_CONSUMER": "1"},
        "markers": ("consumer ready", "request "),
    },
    "minutes": {
        "service": "wf-meeting-minutes",
        "cmd": "python -m lab.workloads.transcript_to_minutes.consumer",
        "restart": "ALWAYS",
        "env": {"AGENT_RESPONSES_STORE": "false", "WF_CONSUMER": "1"},
        "markers": ("consumer ready", "request "),
    },
    # The one-shot job (demo / smoke): run to completion on the generated fixture, or on real
    # uploaded refs via `# CLOUD: VISIO_DIAGRAM=` / `VISIO_REQUIREMENTS=` in .env.
    # Railway has no volume mounts and both fixture inputs are git-ignored GENERATED files
    # (var/out/architecture/lab_model.json, then the .vsdx built from it): generate both at start.
    # `sh -c` is REQUIRED: Railway execs a Dockerfile start command without a shell, so a bare
    # `a && b && c` runs only `a` (the rest arrives as ignored argv) and exits 0 — verified twice.
    "visio-job": {
        "service": "wf-visio-job",
        "cmd": "sh -c 'python scripts/lab_model.py && "
               "python -m lab.workloads.visio_to_archimate.make_sample_vsdx && "
               "python -m lab.workloads.visio_to_archimate.host'",
        "restart": "NEVER",   # exit 0 means done, not crashed; re-run = redeploy
        "env": {"AGENT_RESPONSES_STORE": "false"},
    },
}


# The stream every workload consumes, and the consumer group a host reads it under. Literal here, not
# imported: the deploy job does not install the lab package. tests/governance/
# test_deploy_streams_match_workflows.py holds both equal to lab.platform.workflows.
REQUEST_STREAM = "workflow:requests"


def workload_group(spec) -> str:
    """The consumer group a workload host reads REQUEST_STREAM under — its service name, which is what
    ProcessSpec.group declares for the process it runs."""
    return spec["service"]


MAX_REPLICAS = 6      # a lab overlaps a handful of lanes; every replica is a metered container


def replica_services(spec) -> list[tuple[str, str]]:
    """`[(service_name, consumer_name)]` for one workload — one entry unless it declares `replicas`.

    WHY REPLICAS RATHER THAN THREADS. A consumer group hands each stream entry to exactly ONE
    consumer, so N replicas process N lanes in parallel with no locking and no change to the
    workflow — and it is the shape Container Apps scales, which is the point of this lab. Running
    the lanes concurrently INSIDE one process would instead put four audio extractions and four
    recordings in the one container least able to hold them.

    The FIRST replica keeps the plain service name. Turning replicas on must not rename the service
    that is already deployed: that would orphan its variables and its logs, and `substrate images`
    would then compare against a service nobody runs.

    Each replica gets its own consumer name because two consumers SHARING one name share a pending
    list, and XAUTOCLAIM can no longer tell whose in-flight work is whose — the reclaim that exists
    to stop work being lost would start moving work that was never lost.
    """
    # ABSENT is one replica; ZERO is a mistake. `or 1` would quietly turn "replicas: 0" — a
    # half-finished edit — into a normal single-replica deployment.
    declared = spec.get("replicas")
    n = 1 if declared is None else int(declared)
    if not 1 <= n <= MAX_REPLICAS:
        raise ValueError(f"replicas must be 1..{MAX_REPLICAS}, not {n}")
    base = spec["service"]
    return [(base if i == 1 else f"{base}-{i}", str(i)) for i in range(1, n + 1)]


def workload_env(name, spec, base_env, gw, review=None, consumer=None) -> dict:
    """The exact variables ONE workload receives. The two-tier isolation invariant is the ALLOWLIST
    itself — the shared `ROLE_ENV["workload"]` plus this process's own `WORKLOAD_ENV[name]`: no MCP
    server addresses (it reaches tools only via the gateway), no store credentials (inputs are
    art:// refs read through storage-mcp, its spec goes to semantic-mcp), no gateway/ADOIT/bucket
    secrets, and none of ANOTHER process's agent credentials. Pure — used by `up` and `env`."""
    env = dict(base_env)
    env["GATEWAY_URL"] = gw                                     # the ONLY substrate coordinate
    env["REVIEW_APP_URL"] = review or env.get("REVIEW_APP_URL", "")
    env = env_for_role("workload", env, workload=name)
    env.update(spec.get("env", {}))
    if consumer and "WF_CONSUMER" in spec.get("env", {}):
        # AFTER spec env, deliberately: the spec carries WF_CONSUMER="1" as the single-replica
        # default, and it would otherwise win for every replica — the shared-pending-list failure
        # arrived at from the other direction.
        #
        # ...and ONLY for a workload that already declares one, which is what says "this is a stream
        # consumer". The one-shot job is not: it runs once and exits, belongs to no group, and
        # handing it a consumer name would state something untrue about how it takes its work.
        env["WF_CONSUMER"] = str(consumer)
    return env
