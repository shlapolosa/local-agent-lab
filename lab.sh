#!/usr/bin/env bash
# lab.sh — bring the local agent lab up/down in one command.
#   ./lab.sh up      start redis (brew, or check the cloud one), jaeger (native, or DEPLOY the Railway one when
#                    tracing is remote), adoit-mcp (:9100), semantic-mcp (:9200), gateway (:4000), review app (:8501)
#   ./lab.sh down    stop everything — including the metered Railway Jaeger deployment
#   ./lab.sh down    stop adoit-mcp + gateway (redis is left to brew services)
#   ./lab.sh status  what is running, what the gateway sees, pending approvals
#   ./lab.sh review  (re)start only the architecture review app (streamlit :8501) — the approval channel
# Every service is launched with `env -u ANTHROPIC_API_KEY`: only .env holds lab credentials —
# ambient shell keys must never reach the governance plane (see CLAUDE.md, Gateway Registry).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"; cd "$ROOT"
LOGS="$ROOT/logs"; RUN="$ROOT/.lab"; mkdir -p "$LOGS" "$RUN"
PY="$ROOT/.venv/bin/python"; LITELLM="$ROOT/.venv/bin/litellm"
export PATH="/opt/homebrew/opt/libpq/bin:$PATH"

need() { [ -e "$1" ] || { echo "missing $1 — $2"; exit 1; }; }
load_env() { need .env "create it from the keys listed in CLAUDE.md"; set -a; source .env; set +a
  # resolve $DATABASE_URL references (ARTIFACTS_URL=$DATABASE_URL) and pin local defaults
  [ "${ARTIFACTS_URL:-}" = '$DATABASE_URL' ] && export ARTIFACTS_URL="$DATABASE_URL"
  export BIND_HOST="${BIND_HOST:-127.0.0.1}"
  export ADOIT_MCP_URL="${ADOIT_MCP_URL:-http://127.0.0.1:9100/mcp}" SEMANTIC_MCP_URL="${SEMANTIC_MCP_URL:-http://127.0.0.1:9200/mcp}" \
         STORAGE_MCP_URL="${STORAGE_MCP_URL:-http://127.0.0.1:9300/mcp}"; }
wait_http() { # url, grep-pattern, seconds
  for i in $(seq 1 "$3"); do curl -s --max-time 3 "$1" | /usr/bin/grep -q "$2" && return 0; sleep 1; done; return 1; }
alive() { [ -f "$RUN/$1.pid" ] && kill -0 "$(cat "$RUN/$1.pid")" 2>/dev/null; }
free_port() { local pids; pids=$(lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null || true); [ -n "$pids" ] && { kill -9 $pids 2>/dev/null; sleep 1; }; return 0; }  # || true + return 0: lsof exits 1 when the port is already free; under set -e that must not abort up()
remote_tracing() { [ -n "${OTEL_EXPORTER_OTLP_ENDPOINT:-}" ] && ! echo "$OTEL_EXPORTER_OTLP_ENDPOINT" | /usr/bin/grep -qE "127\.0\.0\.1|localhost"; }

# Jaeger on Railway is metered (trial credit): `up` deploys it, `down` removes the deployment
# (config, variables, domains are kept), `status` reports it. Railway's API needs a browser
# User-Agent and the Project-Access-Token header.
railway_jaeger() {  # up | down | status
  [ -n "${RAILWAY_TOKEN:-}" ] || { echo "jaeger       remote  (no RAILWAY_TOKEN — not managed here)"; return 0; }
  "$PY" - "$1" <<'PY'
import json, os, sys, time, urllib.request
TOKEN, ENV, PROJECT = os.environ["RAILWAY_TOKEN"], os.environ["RAILWAY_ENVIRONMENT_ID"], os.environ["RAILWAY_PROJECT_ID"]
H = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/128 Safari/537.36",
     "Content-Type": "application/json", "Accept": "application/json", "Project-Access-Token": TOKEN}
def gql(q, v=None):
    r = json.load(urllib.request.urlopen(urllib.request.Request("https://backboard.railway.com/graphql/v2",
        data=json.dumps({"query": q, "variables": v or {}}).encode(), headers=H), timeout=60))
    if r.get("errors"): sys.exit(f"jaeger       railway error {[e.get('message') for e in r['errors']]}")
    return r["data"]
_svcs = gql('query($p:String!){ project(id:$p){ services{ edges{ node{ id name } } } } }', {"p": PROJECT})["project"]["services"]["edges"]
SID = next(e["node"]["id"] for e in _svcs if e["node"]["name"] == "local-agent-lab")  # Jaeger by NAME (the project now holds substrate services too)
def latest():
    e = gql('query($s:String!,$e:String!){ deployments(first:1, input:{serviceId:$s, environmentId:$e}){ edges{ node{ id status } } } }', {"s": SID, "e": ENV})["deployments"]["edges"]
    return e[0]["node"] if e else {"id": None, "status": "NONE"}
cmd, d, ui = sys.argv[1], latest(), os.environ.get("JAEGER_UI_URL", "?")
if cmd == "status":
    print(f"jaeger       railway {d['status'].lower():8} {ui}")
elif cmd == "up":
    if d["status"] == "SUCCESS": print(f"jaeger       railway ok  {ui}"); sys.exit()
    gql('mutation($s:String!,$e:String!){ serviceInstanceDeploy(serviceId:$s, environmentId:$e) }', {"s": SID, "e": ENV})
    for _ in range(24):
        time.sleep(10); d = latest()
        if d["status"] in ("SUCCESS", "FAILED", "CRASHED"): break
    print(f"jaeger       railway {d['status'].lower()}  {ui}")
    if d["status"] != "SUCCESS": sys.exit(1)
elif cmd == "down":
    if d["status"] != "SUCCESS": print(f"jaeger       railway already {d['status'].lower()}"); sys.exit()
    gql('mutation($id:String!){ deploymentRemove(id:$id) }', {"id": d["id"]}); print("jaeger       railway stopped (config, variables, domains kept)")
PY
}

up() {
  load_env; need "$PY" "python3.12 -m venv .venv && .venv/bin/pip install 'litellm[proxy]' fastmcp prisma"
  # redis: governance state (rate limits, budgets, router) + approval streams.
  # REDIS_URL set -> managed/cloud instance (just check it); unset -> local Homebrew service
  if [ -n "${REDIS_URL:-}" ]; then
    redis-cli -u "$REDIS_URL" --no-auth-warning ping 2>/dev/null | /usr/bin/grep -q PONG \
      && echo "redis        ok  ${REDIS_HOST:-cloud}:${REDIS_PORT:-}" || { echo "redis        UNREACHABLE at REDIS_URL"; exit 1; }
  elif redis-cli -h "${REDIS_HOST:-127.0.0.1}" -p "${REDIS_PORT:-6379}" ping 2>/dev/null | /usr/bin/grep -q PONG; then
    echo "redis        ok  ${REDIS_HOST:-127.0.0.1}:${REDIS_PORT:-6379}"
  else brew services start redis >/dev/null && sleep 2 && echo "redis        started (brew services)"; fi
  # jaeger: native v2 all-in-one binary (tools/jaeger, ~50 MB RAM — no Colima VM); traces = audit trail.
  # A remote OTEL_EXPORTER_OTLP_ENDPOINT (e.g. Jaeger on Railway, App Insights) means no local jaeger.
  if remote_tracing; then
    railway_jaeger up || { echo "jaeger       remote tracing endpoint down — stopping"; exit 1; }
  elif alive jaeger; then echo "jaeger       ok  already running (pid $(cat $RUN/jaeger.pid))"; else
    need tools/jaeger/jaeger "download jaeger-2.x-darwin-arm64 from github.com/jaegertracing/jaeger/releases into tools/jaeger/"
    nohup ./tools/jaeger/jaeger >"$LOGS/jaeger.log" 2>&1 & echo $! >"$RUN/jaeger.pid"
    wait_http "http://127.0.0.1:16686/api/services" "data" 20 && echo "jaeger       started  http://127.0.0.1:16686 (OTLP :4318)" \
      || { echo "jaeger       FAILED — see logs/jaeger.log"; exit 1; }; fi
  # adoit-mcp: ArchiMate engine + ADOIT facade, registered with the gateway's MCP registry
  if alive adoit-mcp; then echo "adoit-mcp    ok  already running (pid $(cat $RUN/adoit-mcp.pid))"; else
    env -u ANTHROPIC_API_KEY nohup "$PY" mcp/adoit_mcp/server.py >"$LOGS/adoit-mcp.log" 2>&1 & echo $! >"$RUN/adoit-mcp.pid"
    wait_http "http://127.0.0.1:9100/mcp" "" 20 || true; echo "adoit-mcp    started  http://127.0.0.1:9100/mcp"; fi
  # semantic-mcp: vocabularies / classification / legality / SPARQL (read-only, granted to all teams)
  if alive semantic-mcp; then echo "semantic-mcp ok  already running (pid $(cat $RUN/semantic-mcp.pid))"; else
    env -u ANTHROPIC_API_KEY nohup "$PY" mcp/semantic_mcp/server.py >"$LOGS/semantic-mcp.log" 2>&1 & echo $! >"$RUN/semantic-mcp.pid"
    wait_http "http://127.0.0.1:9200/mcp" "" 20 || true; echo "semantic-mcp started  http://127.0.0.1:9200/mcp"; fi
  # storage-mcp: READ-ONLY governed access to the upload store — the only way a workload reads an input object
  if alive storage-mcp; then echo "storage-mcp ok  already running (pid $(cat $RUN/storage-mcp.pid))"; else
    env -u ANTHROPIC_API_KEY nohup "$PY" mcp/storage_mcp/server.py >"$LOGS/storage-mcp.log" 2>&1 & echo $! >"$RUN/storage-mcp.pid"
    wait_http "http://127.0.0.1:9300/mcp" "" 20 || true; echo "storage-mcp started  http://127.0.0.1:9300/mcp"; fi
  # gateway: the governance plane (LLM /v1, MCP /mcp, registry, skills)
  if alive litellm; then echo "gateway      ok  already running (pid $(cat $RUN/litellm.pid))"; else
    free_port 4000                        # ensure :4000 is free so the gateway never binds a random port
    env -u ANTHROPIC_API_KEY nohup "$LITELLM" --config gateway/litellm-config.yaml --port 4000 >"$LOGS/litellm.log" 2>&1 & echo $! >"$RUN/litellm.pid"
    printf "gateway      starting"; wait_http "http://127.0.0.1:4000/health/readiness" '"connected"' 90 \
      && echo "  http://127.0.0.1:4000  (db connected)" || { echo "  FAILED — see logs/litellm.log"; exit 1; }; fi
  review
  render_clients
  status_gateway
}

status_gateway() {
  load_env 2>/dev/null || true
  local auth="Authorization: Bearer ${LITELLM_MASTER_KEY:-}"
  echo "models       $(curl -s http://127.0.0.1:4000/v1/models -H "$auth" | $PY -c 'import json,sys; print(", ".join(m["id"] for m in json.load(sys.stdin)["data"]))' 2>/dev/null || echo '?')"
  echo "mcp servers  $($PY - <<PYEOF 2>/dev/null || echo '?'
import yaml; print(", ".join(yaml.safe_load(open("gateway/litellm-config.yaml")).get("mcp_servers",{}).keys()))
PYEOF
)"
  echo "skills       $(curl -s "http://127.0.0.1:4000/v1/skills?beta=true&custom_llm_provider=litellm_proxy" -H "$auth" | $PY -c 'import json,sys; print(", ".join(s["display_title"] for s in json.load(sys.stdin).get("data",[])) or "none")' 2>/dev/null || echo '?')"
  echo "approvals    pending: $(env -u ANTHROPIC_API_KEY $PY shared/approvals.py count 2>/dev/null || echo '?')  (./lab.sh review | python shared/approvals.py list)"
  echo "registry ui  http://127.0.0.1:4000/ui  (admin / master key)"
  echo "traces ui    ${JAEGER_UI_URL:-http://127.0.0.1:16686}  services: $(curl -s --max-time 5 "${JAEGER_UI_URL:-http://127.0.0.1:16686}/api/services" | $PY -c 'import json,sys; print(", ".join(json.load(sys.stdin).get("data") or []) or "none yet")' 2>/dev/null || echo '?')"
}

# Render env-specific client settings from templates (values from .env: GATEWAY_URL,
# ENTRA_GATEWAY_AUDIENCE). Regenerate whenever the gateway moves (localhost -> cloud/APIM)
# or the audience changes. Rendered files are git-ignored; templates are committed.
render_clients() {
  load_env
  local n=0
  for tpl in clients/*/settings.template.json; do
    [ -e "$tpl" ] || continue
    out="${tpl%.template.json}.json"
    sed -e "s#\${GATEWAY_URL}#${GATEWAY_URL:-http://127.0.0.1:4000}#g" \
        -e "s#\${ENTRA_GATEWAY_AUDIENCE}#${ENTRA_GATEWAY_AUDIENCE:-}#g" "$tpl" > "$out"
    n=$((n+1))
  done
  echo "clients      rendered $n settings from templates (GATEWAY_URL=${GATEWAY_URL:-http://127.0.0.1:4000})"
  echo "             copy clients/claude-code/settings.json -> your project's .claude/settings.json"
}

review() {
  load_env
  if alive review; then echo "review app   ok  http://127.0.0.1:8501 (pid $(cat $RUN/review.pid))"; else
    env -u ANTHROPIC_API_KEY nohup "$ROOT/.venv/bin/streamlit" run review/app.py --server.port 8501 --server.headless true \
      >"$LOGS/review.log" 2>&1 & echo $! >"$RUN/review.pid"
    wait_http "http://127.0.0.1:8501/healthz" "ok" 30 && echo "review app   started  http://127.0.0.1:8501" \
      || { echo "review app   FAILED — see logs/review.log"; exit 1; }; fi
}

down() {
  for s in wf-visio review litellm storage-mcp semantic-mcp adoit-mcp jaeger; do
    if alive "$s"; then kill "$(cat "$RUN/$s.pid")" && echo "$s stopped"; fi; rm -f "$RUN/$s.pid"; done
  load_env 2>/dev/null || true; remote_tracing && railway_jaeger down
  pkill -f "litellm --config gateway/litellm-config.yaml" 2>/dev/null || true
  pkill -f "mcp/adoit_mcp/server.py" 2>/dev/null || true
  pkill -f "mcp/semantic_mcp/server.py" 2>/dev/null || true
  pkill -f "mcp/storage_mcp/server.py" 2>/dev/null || true
  pkill -f "processes.visio_to_archimate.consumer" 2>/dev/null || true
}

status() {
  load_env 2>/dev/null || true
  if remote_tracing; then railway_jaeger status; else alive jaeger && echo "jaeger    running (pid $(cat $RUN/jaeger.pid))" || echo "jaeger    stopped"; fi
  for s in adoit-mcp semantic-mcp storage-mcp litellm wf-visio; do alive "$s" && echo "$s    running (pid $(cat $RUN/$s.pid))" || echo "$s    stopped"; done
  load_env 2>/dev/null || true
  if [ -n "${REDIS_URL:-}" ]; then redis-cli -u "$REDIS_URL" --no-auth-warning ping 2>/dev/null | /usr/bin/grep -q PONG && echo "redis        cloud ok (${REDIS_HOST:-})" || echo "redis        cloud UNREACHABLE";
  else redis-cli ping 2>/dev/null | /usr/bin/grep -q PONG && echo "redis        running (local)" || echo "redis        stopped"; fi
  curl -s --max-time 3 http://127.0.0.1:4000/health/readiness | /usr/bin/grep -q '"connected"' && status_gateway || echo "gateway      not reachable"
}

# Cloud tiers on Railway — the substrate (shared plane) and workloads deploy/tear down
# INDEPENDENTLY (deploy/railway.py). Metered: bring a tier up for a demo, down when idle.
cloud() { load_env; env -u ANTHROPIC_API_KEY "$PY" deploy/railway.py "$@"; }

consumer() {   # the long-lived visio workload host: consumes workflow:requests (Submit page -> run)
  load_env
  if alive wf-visio; then echo "wf-visio ok  already running (pid $(cat $RUN/wf-visio.pid))"; return; fi
  env -u ANTHROPIC_API_KEY nohup "$PY" -m processes.visio_to_archimate.consumer >"$LOGS/wf-visio.log" 2>&1 & echo $! >"$RUN/wf-visio.pid"
  echo "wf-visio started  (consumer of workflow:requests; log: $LOGS/wf-visio.log)"
}

case "${1:-}" in
  up) up;; down) down;; status) status;; review) review;; clients) render_clients;; consumer) consumer;;
  cloud) shift; cloud "$@";;
  *) echo "usage: $0 up|down|status|review|consumer|clients | cloud substrate up|down|status"; exit 2;;
esac
