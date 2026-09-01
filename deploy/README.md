# Deploying the lab off the laptop — Substrate + Workloads

Two tiers, deployed and torn down **independently** (mirrors the Azure org split: a platform team
runs the shared plane once; each product team ships its workload onto it):

- **Substrate** = the shared platform plane: `gateway` (governance, public), `semantic-mcp` +
  `adoit-mcp` (shared tools, internal), `review` (approval gate, public). Deployed once.
- **Workloads** = business processes (`processes/<name>/`), each its own container set, referencing
  the substrate ONLY through the gateway's public domain + the shared managed backends. Spin up/down
  on their own. Cross-workflow deps go via **events (Redis Streams)** or **A2A through the gateway** —
  never direct container coupling — and degrade gracefully.

Everything stateful is a managed service: **Neon** (keys/spend/skills/artifacts), **Redis Cloud**
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

Point any client/host at the substrate gateway's public domain — the workload references the plane,
it doesn't embed it:
```bash
GATEWAY_URL=https://<gateway-domain> .venv/bin/python -m processes.visio_to_archimate.host
```
Agents authenticate (Entra JWT / per-agent key), tools run via the substrate MCP servers through the
gateway, the approval stages into the substrate review app, and the run traces to Railway Jaeger —
exactly the local behaviour, now off-laptop.

## Azure target (unchanged)

One Container App per service from `deploy/Dockerfile`: internal ingress for the two MCP servers,
external + Entra auth for the gateway UI and review app, secrets from Key Vault, OTLP to Application
Insights, Azure Cache for Redis or the existing Redis Cloud. Put the gateway in the same region as
Redis (the limiter's ~20 round trips per request are the latency-sensitive path).

## Known limitation

Licensed BA Guild reference workbooks (git-ignored `semantic/reference/sources/`) aren't in the repo
and there's no Railway volume, so `semantic-mcp`'s **capability-export** is degraded in the cloud.
Classification / validation / render and the Visio→ArchiMate workflow are unaffected.
