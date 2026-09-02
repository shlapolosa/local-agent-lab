# Deploying the lab off the laptop — Substrate + Workloads

Two tiers, deployed and torn down **independently** (mirrors the Azure org split: a platform team
runs the shared plane once; each product team ships its workload onto it):

- **Substrate** = the shared platform plane: `gateway` (governance, public), `semantic-mcp` +
  `adoit-mcp` (shared tools, internal), `review` (approval gate, public). Deployed once.
- **Workloads** = business processes (`processes/<name>/`), each its own container set, referencing
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
docker compose --env-file .env -f processes/visio_to_archimate/deploy/compose.yml up --build
```
One image, role-by-command: `deploy/Dockerfile`.

## Railway (no local Docker needed — builds the public repo)

`deploy/railway.py` (wrapped by `./lab.sh cloud …`) deploys each tier via the Railway GraphQL API.
Config comes from `.env`: active `KEY=value` lines, with `# CLOUD: KEY=value` comments overriding the
machine-local ones (Redis Cloud, Railway Jaeger) — secrets never leave `.env`.

```bash
./lab.sh cloud substrate up        # create/deploy gateway + 2 MCP + review; prints public URLs
./lab.sh cloud substrate status    # build/deploy state per service
./lab.sh cloud substrate down      # stop (metered) — config/variables/domain kept
```

- **Networking:** the substrate lives in one Railway project/environment, so the gateway reaches the
  MCP servers over private DNS (`adoit-mcp.railway.internal:9100`, `semantic-mcp…:9200`). The MCP
  servers get **no public domain**; only `gateway` (targetPort 4000) and `review` (8501) do.
  Services bind `::` (`BIND_HOST=::`) — Railway private networking is IPv6.
- **Trust:** `MCP_SHARED_SECRET` is mandatory (servers enforce it, gateway sends it) since
  `BIND_HOST` is not loopback. Review app behind `REVIEW_APP_PASSWORD` (Azure equivalent: Container
  Apps Entra auth in front).
- **Cost:** metered (~$5 credit) → `down` each tier when idle, same discipline as the Railway Jaeger.

## Running a workload against the cloud substrate

A workload is its **own Railway service** that references the plane, it doesn't embed it — it
gets ONLY the gateway's public domain + the shared backends (never the MCP servers):
```bash
set -a && source .env && set +a
python deploy/railway.py workload visio up|down|status     # service wf-visio, a run-to-completion job
# or, from anywhere, the same thing by hand:
GATEWAY_URL=https://<gateway-domain> .venv/bin/python -m processes.visio_to_archimate.host
```
Agents authenticate (Entra JWT / per-agent key), tools run via the substrate MCP servers through the
gateway, the approval stages into the substrate review app, and the run traces to Railway Jaeger —
exactly the local behaviour, now off-laptop (verified: one trace, 552 spans across the workload,
gateway and both MCP servers). Railway job gotchas, all verified the hard way:
- a Dockerfile **start command is exec'd without a shell** — `a && b` runs only `a`; chains must be
  `sh -c '…'` (`railway.py` does this);
- a `restartPolicyType=NEVER` job shows **SUCCESS whether it finished or crashed** — `workload status`
  reads the run's own log markers (`approval requested:` / `Traceback`) instead of trusting it;
- **no volume mounts**, so git-ignored generated inputs (`architecture/lab_model.json`, then the
  `.vsdx` fixture) are generated at container start; re-run = redeploy (or set `cronSchedule`).
- **Inputs go in by reference, and a person starts the run.** The review app's **Submit** mode
  uploads a diagram (`.vsdx` or image) + requirements docs straight into the **upload store**
  (`UPLOADS_URL` — a Railway **Bucket** via `python deploy/railway.py bucket up`, which writes the
  `# CLOUD: S3_*` lines; locally the Postgres artifact store, no S3 needed) and an explicit **Run**
  publishes a `workflow:requests` event (`shared/workflows.py`, Redis Streams). The long-lived
  `wf-visio` service (`processes/visio_to_archimate/consumer.py`, `restart=ALWAYS`) consumes it and
  writes status → trace → approval back, which the Submit page shows. **The workload never holds
  store credentials**: refs are read through the gateway's read-only **storage-mcp** (`:9300`;
  `storage_read_vsdx` / `storage_read_document` for the BA, `storage_get` /
  `storage_extract_figures` for the images the workflow attaches, normalised server-side to
  ≤1600 px), and its spec is stored via `semantic_store_spec`. CLI alternatives stay:
  `python -m processes.visio_to_archimate.inputs upload <files>` → refs, `python
  shared/workflows.py request visio_to_archimate <refs…>`, or the one-shot `workload visio-job` with
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

Licensed BA Guild reference workbooks (git-ignored `semantic/reference/sources/`) aren't in the repo
and there's no Railway volume, so `semantic-mcp`'s **capability-export** is degraded in the cloud.
Classification / validation / render and the Visio→ArchiMate workflow are unaffected.
