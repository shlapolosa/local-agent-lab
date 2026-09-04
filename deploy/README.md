# Deploying the lab off the laptop — Substrate + Workloads

Two tiers, deployed and torn down **independently** (mirrors the Azure org split: a platform team
runs the shared plane once; each product team ships its workload onto it):

- **Substrate** = the shared platform plane: `redis` (limiter state + streams, internal),
  `gateway` (governance, public), `semantic-mcp` + `adoit-mcp` + `storage-mcp` + `workflow-mcp` +
  `graph-mcp` (shared tools, internal), `review` (approval gate + Submit, public), `jaeger` (tracing), plus each
  approval **channel** that is configured (`telegram`, `teams` — internal, no ingress). Deployed once.
  The approval gate has TWO faces: the review app for a person with a browser, and `workflow-mcp`'s
  `approvals_list/_get/_decide` tools for a channel that brings its own signed-in human (a Copilot
  Studio agent in Teams) — one implementation (`lab.substrate.approvals.human_decision`), governed
  through the gateway like any other tool.
- **Workloads** = business processes (`src/lab/workloads/<name>/`), each its own container set, referencing
  the substrate ONLY through the gateway's public domain + the shared managed backends. Spin up/down
  on their own. Cross-workflow deps go via **events (Redis Streams)** or **A2A through the gateway** —
  never direct container coupling — and degrade gracefully.

Everything stateful is a managed service: **Neon** (keys/spend/skills/artifacts), **Redis — inside the substrate on the cloud tier** (a `redis:7-alpine`
service with a `/data` volume; Redis Cloud's 30-client free tier was blown by LiteLLM's two
50-connection pools + pub/sub per gateway, and co-locating removes the cross-region RTT; it must
bind `0.0.0.0 ::` because Railway private DNS is IPv6-only), still **Redis Cloud** as the flip-back
(limiter + approval streams), **Ollama Cloud** (inference), **ADOIT** (EA repo), **Jaeger on
Railway** (tracing). The tiers are stateless containers over that.

## Compose (local, needs a Docker engine)

```bash
# substrate first (shared network `substrate`)
docker compose --env-file .env -f deploy/substrate/compose.yml up --build
# then any workload, independently, joining the substrate network
docker compose --env-file .env -f deploy/workloads/visio_to_archimate/compose.yml up --build
```
One image, role-by-command: `deploy/Dockerfile`.

## Railway (no local Docker needed — builds the public repo)

`deploy/railway.py` (wrapped by `./lab.sh cloud …`) deploys each tier via the Railway GraphQL API.
Config comes from `.env`: active `KEY=value` lines, with `# CLOUD: KEY=value` comments overriding the
machine-local ones (Redis Cloud, Railway Jaeger) — secrets never leave `.env`.

```bash
./lab.sh cloud substrate up        # create/deploy redis + gateway + 4 MCP (semantic, adoit, storage, workflow) + review + configured channels + jaeger; prints public URLs
./lab.sh cloud substrate status    # build/deploy state per service (+ the env-key audit below)
./lab.sh cloud substrate down      # stop (metered) — config/variables/domain kept
./lab.sh cloud substrate env       # OFFLINE: the exact env KEY NAMES each service receives (no Railway call)
```

- **Approval channels are OPTIONAL services:** `telegram` and `teams` are deployed only when their
  settings are in the deploy profile (`TELEGRAM_BOT_TOKEN`+`TELEGRAM_CHAT_ID` / `TEAMS_WEBHOOK_URL`),
  because an unconfigured channel exits immediately by design — `substrate up` prints `skipped (not
  configured: …)` for the others, and `lab.sh up` does the same locally. A channel is a loop with no
  ingress (`restartPolicyType=ALWAYS`, no domain) and gets ONLY its own webhook/token, `REDIS_URL`
  (the approvals streams), the link(s) it puts in front of the human and the tracing sink — no
  Postgres, no bucket, no gateway or model credential. `status`/`down` still cover a channel that is
  deployed but no longer configured, so removing its settings cannot orphan it.
- **Least privilege (per-role env allowlist):** a service receives ONLY the `.env` keys its role
  reads — `ROLE_ENV` in `deploy/railway.py` (gateway / adoit-mcp / semantic-mcp / storage-mcp /
  workflow-mcp / graph-mcp / review / telegram / teams / workload; glob patterns, each line cites the
  code that reads the key). The bucket credentials (`S3_*` + `UPLOADS_URL`) are granted only by a
  service's `"s3": True` flag — review (Submit uploads), storage-mcp (reads) and graph-mcp
  (`collab_fetch` streams fetched content in); a workload gets no `ADOIT_*`, no `LITELLM_MASTER_KEY`, no upstream model keys, no
  `MCP_SHARED_SECRET`, no `DATABASE_URL`, no bucket. `substrate env` / `workload <n> env` print the
  key names for review; `up` prints the same line as it upserts. On Azure this table is the
  Key-Vault-reference scope per Container App. `tests/deploy/test_railway_env.py` pins it (offline).
- **Networking:** the substrate lives in one Railway project/environment, so the gateway reaches the
  MCP servers over private DNS (`adoit-mcp.railway.internal:9100`, `semantic-mcp…:9200`,
  `storage-mcp…:9300`, `workflow-mcp…:9400`, `graph-mcp…:9500`). The MCP servers get **no public domain**; only `gateway` (targetPort 4000)
  and `review` (8501) do. Services bind `::` (`BIND_HOST=::`) — Railway private networking is IPv6.
- **Trust:** `MCP_SHARED_SECRET` is mandatory (servers enforce it, gateway sends it) since
  `BIND_HOST` is not loopback. Review app behind `REVIEW_APP_PASSWORD` (Azure equivalent: Container
  Apps Entra auth in front).
- **Cost:** metered (~$5 credit) → `down` each tier when idle, same discipline as the Railway Jaeger.

## Running a workload against the cloud substrate

A workload is its **own Railway service** that references the plane, it doesn't embed it — it
gets ONLY the gateway's public domain + the shared backends (never the MCP servers):
```bash
set -a && source .env && set +a
python deploy/railway.py workload visio up|down|status|env # service wf-visio, the long-lived consumer (visio-job = one-shot)
# or, from anywhere, the same thing by hand:
GATEWAY_URL=https://<gateway-domain> .venv/bin/python -m lab.workloads.visio_to_archimate.host
```
Agents authenticate (Entra JWT / per-agent key), tools run via the substrate MCP servers through the
gateway, the approval stages into the substrate review app, and the run traces to Railway Jaeger —
exactly the local behaviour, now off-laptop (verified: one trace, 552 spans across the workload,
gateway and both MCP servers). Railway job gotchas, all verified the hard way:
- a Dockerfile **start command is exec'd without a shell** — `a && b` runs only `a`; chains must be
  `sh -c '…'` (`railway.py` does this);
- a `restartPolicyType=NEVER` job shows **SUCCESS whether it finished or crashed** — `workload status`
  reads the run's own log markers (`approval requested:` / `Traceback`) instead of trusting it;
- **no volume mounts**, so git-ignored generated inputs (`var/out/architecture/lab_model.json`, then the
  `.vsdx` fixture) are generated at container start; re-run = redeploy (or set `cronSchedule`).
- **Inputs go in by reference, and a person starts the run.** The review app's **Submit** mode
  uploads a diagram (`.vsdx` or image) + requirements docs straight into the **upload store**
  (`UPLOADS_URL` — a Railway **Bucket** via `python deploy/railway.py bucket up`, which writes the
  `# CLOUD: S3_*` lines; locally the Postgres artifact store, no S3 needed) and an explicit **Run**
  publishes a `workflow:requests` event (`src/lab/platform/workflows.py`, Redis Streams). The long-lived
  `wf-visio` service (`src/lab/workloads/visio_to_archimate/consumer.py`, `restart=ALWAYS`) consumes it and
  writes status → trace → approval back, which the Submit page shows. **The workload never holds
  store credentials**: refs are read through the gateway's read-only **storage-mcp** (`:9300`;
  `storage_read_vsdx` / `storage_read_document` for the BA, `storage_get` /
  `storage_extract_figures` for the images the workflow attaches, normalised server-side to
  ≤1600 px), and its spec is stored via `semantic_store_spec`. CLI alternatives stay:
  `python -m lab.substrate.review.uploads upload <files>` → refs, `python
  src/lab/platform/workflows.py request visio_to_archimate <refs…>`, or the one-shot `workload visio-job` with
  `# CLOUD: VISIO_DIAGRAM=` / `VISIO_REQUIREMENTS=`.
- **Large workloads span containers by decomposition, not by splitting one graph**: one AF host per
  sub-process/agent (own container, OTel service name, key), coupled via A2A through the gateway or
  Redis Streams; throughput is replicas of a stateless host.

## Azure target (unchanged)

One Container App per service from `deploy/Dockerfile`: internal ingress for the two MCP servers,
external + Entra auth for the gateway UI and review app, secrets from Key Vault, OTLP to Application
Insights, Azure Cache for Redis or the existing Redis Cloud. Put the gateway in the same region as
Redis (the limiter's ~20 round trips per request are the latency-sensitive path).

## Known limitation

Licensed BA Guild reference workbooks (git-ignored `var/reference-sources/`) aren't in the repo
and there's no Railway volume, so `semantic-mcp`'s **capability-export** is degraded in the cloud.
Classification / validation / render and the Visio→ArchiMate workflow are unaffected.
