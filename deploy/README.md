# Deploying the lab off the laptop

Everything stateful is already a managed service: **Neon Postgres** (keys, spend, skills, and the
artifact store), **Redis Cloud** (limiter state, approval streams), **Ollama Cloud** (inference),
**ADOIT** (EA repository), **GitHub** (skill source). What remains are five stateless Python
processes plus tracing.

## Same-machine assumptions removed (Aug 2026)

| Assumption | Replacement |
|---|---|
| Services on `127.0.0.1` | `shared/config.py` — `GATEWAY_URL`, `ADOIT_MCP_URL`, `SEMANTIC_MCP_URL`, `REVIEW_APP_URL`, `JAEGER_UI_URL`, `BIND_HOST` |
| Gateway trusts MCP servers because they're loopback | `MCP_SHARED_SECRET` bearer token: servers enforce it (`shared/mcpauth.py`), gateway sends it (`auth_type: bearer_token`) |
| Files handed between services by path | `shared/artifacts.py` — `art://` references in a Postgres `lab_artifacts` table (`ARTIFACTS_URL`, defaults to `DATABASE_URL`); tool results and approval events carry refs, the review app reads them |
| Review app open to anyone who can reach it | `REVIEW_APP_PASSWORD` gate locally; on Azure, Container Apps built-in Entra authentication in front |
| Redis on `localhost` | `REDIS_URL` |

## Topology

`deploy/docker-compose.yml` runs the exact cloud shape locally (each service its own host name).
On **Azure Container Apps** (the target): one Container App per service from `deploy/Dockerfile`,
internal ingress for the two MCP servers (only the gateway talks to them), external ingress with
Entra auth for the gateway UI and the review app, secrets from Key Vault, OTLP to Application
Insights (`OTEL_*`), Azure Cache for Redis or the existing Redis Cloud, Azure Files or Blob
only if you outgrow the Postgres artifact store. Put the gateway in the same region as Redis —
the limiter's ~20 round trips per request are the latency-sensitive path.

## Not yet done here

Image builds are unverified on this machine (no Docker daemon); the compose file mirrors `lab.sh`
one-to-one and is the first thing to run on a machine with Docker.
