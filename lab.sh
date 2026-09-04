#!/usr/bin/env bash
# lab.sh — bring the local agent lab up/down in one command.
#   ./lab.sh up      start redis (brew, or check the cloud one), jaeger (native, or DEPLOY the Railway one when
#                    tracing is remote), adoit-mcp (:9100), semantic-mcp (:9200), storage-mcp (:9300),
#                    workflow-mcp (:9400), graph-mcp (:9500), gateway (:4000), review app (:8501), and every CONFIGURED
#                    approval channel (telegram, teams — skipped with a line when their .env settings are absent)
#   ./lab.sh down    stop everything — the MCP servers, gateway, review app, every approval channel,
#                    the consumer and the metered Railway Jaeger deployment (redis is left to brew)
#   ./lab.sh status  what is running, what the gateway sees, pending approvals
#   ./lab.sh review  (re)start only the architecture review app (streamlit :8501) — the browser approval channel
#   ./lab.sh channels (re)start only the configured approval channels (telegram, teams)
# Every service is launched with `env -u ANTHROPIC_API_KEY`: only .env holds lab credentials —
# ambient shell keys must never reach the governance plane (see CLAUDE.md, Gateway Registry).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"; cd "$ROOT"
LOGS="$ROOT/var/logs"; RUN="$ROOT/var/run"; mkdir -p "$LOGS" "$RUN"
PY="$ROOT/.venv/bin/python"; LITELLM="$ROOT/.venv/bin/litellm"
export PATH="/opt/homebrew/opt/libpq/bin:$PATH"

need() { [ -e "$1" ] || { echo "missing $1 — $2"; exit 1; }; }
load_env() { need .env "create it from the keys listed in CLAUDE.md"; set -a; source .env; set +a
  # resolve $DATABASE_URL references (ARTIFACTS_URL=$DATABASE_URL) and pin local defaults
  [ "${ARTIFACTS_URL:-}" = '$DATABASE_URL' ] && export ARTIFACTS_URL="$DATABASE_URL"
  export BIND_HOST="${BIND_HOST:-127.0.0.1}"
  export ADOIT_MCP_URL="${ADOIT_MCP_URL:-http://127.0.0.1:9100/mcp}" SEMANTIC_MCP_URL="${SEMANTIC_MCP_URL:-http://127.0.0.1:9200/mcp}" \
         STORAGE_MCP_URL="${STORAGE_MCP_URL:-http://127.0.0.1:9300/mcp}" \
         WORKFLOW_MCP_URL="${WORKFLOW_MCP_URL:-http://127.0.0.1:9400/mcp}" \
         GRAPH_MCP_URL="${GRAPH_MCP_URL:-http://127.0.0.1:9500/mcp}"; }
wait_http() { # url, grep-pattern, seconds
  for i in $(seq 1 "$3"); do curl -s --max-time 3 "$1" | /usr/bin/grep -q "$2" && return 0; sleep 1; done; return 1; }
alive() { [ -f "$RUN/$1.pid" ] && kill -0 "$(cat "$RUN/$1.pid")" 2>/dev/null; }
free_port() { local pids; pids=$(lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null || true); [ -n "$pids" ] && { kill -9 $pids 2>/dev/null; sleep 1; }; return 0; }  # || true + return 0: lsof exits 1 when the port is already free; under set -e that must not abort up()
# One MCP server: already up -> report, else launch it detached (ambient creds stripped) and wait for
# /mcp. All four differ ONLY in name, module and port, so they share this.
start_mcp() {   # name, module, port
  if alive "$1"; then printf "%-12s ok  already running (pid %s)\n" "$1" "$(cat "$RUN/$1.pid")"; return 0; fi
  env -u ANTHROPIC_API_KEY nohup "$PY" -m "$2" >"$LOGS/$1.log" 2>&1 & echo $! >"$RUN/$1.pid"
  wait_http "http://127.0.0.1:$3/mcp" "" 20 || true
  printf "%-12s started  http://127.0.0.1:%s/mcp\n" "$1" "$3"
}
# The approval channels — each an `approvals:requests` consumer group, like the review app — in ONE
# place: name, module, required .env settings. start/status/stop all walk this table, so adding a
# channel is exactly ONE line here. Kept in step with deploy/railway.py's CHANNELS table by
# tests/deploy/test_railway_env.py (a channel that runs locally but is never deployed — or stops
# only in one of the two runners — is a silently unattended approval gate).
for_each_channel() {   # calls "$1 <name> <module> <required .env vars>" for every channel
  "$1" telegram lab.substrate.channels.telegram "TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID"
  "$1" teams    lab.substrate.channels.teams    "TEAMS_WEBHOOK_URL"
}
missing_settings() { local v out=""; for v in $1; do [ -n "${!v:-}" ] || out="$out $v"; done; echo "$out"; }
# Start ONE channel, only when it is configured: an unconfigured channel exits immediately by design,
# so launching it would leave a dead pid file and hide the fact that nobody is being notified.
start_channel() {   # name, module, "VAR1 VAR2" (all must be non-empty)
  local missing i; missing=$(missing_settings "$3")
  if [ -n "$missing" ]; then printf "%-12s skipped  (not configured: set%s in .env)\n" "$1" "$missing"; return 0; fi
  if alive "$1"; then printf "%-12s ok  already running (pid %s)\n" "$1" "$(cat "$RUN/$1.pid")"; return 0; fi
  env -u ANTHROPIC_API_KEY nohup "$PY" -m "$2" >"$LOGS/$1.log" 2>&1 & echo $! >"$RUN/$1.pid"
  # A channel has no port to probe, so its own first log line ("<name> channel: enabled") is the
  # readiness signal — without this, a channel that dies on a bad token or an import error would be
  # reported as started, which is the very silence the skip check above exists to prevent. A broken
  # OPTIONAL channel warns and does not fail `up`.
  for i in 1 2 3; do /usr/bin/grep -q "channel: enabled" "$LOGS/$1.log" 2>/dev/null && break; sleep 1; done
  alive "$1" && printf "%-12s started  (approval channel; log: var/logs/%s.log)\n" "$1" "$1" \
    || printf "%-12s FAILED — see var/logs/%s.log (channel not running)\n" "$1" "$1"
  return 0
}
stop_channel() {    # name, module, required vars (unused) — the table already knows the module path
  if alive "$1"; then kill "$(cat "$RUN/$1.pid")" && echo "$1 stopped"; fi; rm -f "$RUN/$1.pid"
  pkill -f "$2" 2>/dev/null || true
}
channel_status() {  # name, module, required vars — "stopped" alone would read as a fault
  local missing; missing=$(missing_settings "$3")
  alive "$1" && echo "$1    running (pid $(cat "$RUN/$1.pid"))" \
    || echo "$1    stopped${missing:+ (not configured)}"
}
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
  load_env; need "$PY" "python3.12 -m venv .venv && .venv/bin/pip install -r deploy/requirements.txt -e ."
  # redis: governance state (rate limits, budgets, router) + approval streams.
  # REDIS_URL set -> managed/cloud instance (just check it); unset -> local Homebrew service
  if [ -n "${REDIS_URL:-}" ]; then
    redis-cli -u "$REDIS_URL" --no-auth-warning ping 2>/dev/null | /usr/bin/grep -q PONG \
      && echo "redis        ok  ${REDIS_HOST:-cloud}:${REDIS_PORT:-}" || { echo "redis        UNREACHABLE at REDIS_URL"; exit 1; }
  elif redis-cli -h "${REDIS_HOST:-127.0.0.1}" -p "${REDIS_PORT:-6379}" ping 2>/dev/null | /usr/bin/grep -q PONG; then
    echo "redis        ok  ${REDIS_HOST:-127.0.0.1}:${REDIS_PORT:-6379}"
  else brew services start redis >/dev/null && sleep 2 && echo "redis        started (brew services)"; fi
  # jaeger: native v2 all-in-one binary (var/tools/jaeger, ~50 MB RAM — no Colima VM); traces = audit trail.
  # A remote OTEL_EXPORTER_OTLP_ENDPOINT (e.g. Jaeger on Railway, App Insights) means no local jaeger.
  if remote_tracing; then
    railway_jaeger up || { echo "jaeger       remote tracing endpoint down — stopping"; exit 1; }
  elif alive jaeger; then echo "jaeger       ok  already running (pid $(cat $RUN/jaeger.pid))"; else
    need var/tools/jaeger/jaeger "download jaeger-2.x-darwin-arm64 from github.com/jaegertracing/jaeger/releases into var/tools/jaeger/"
    nohup ./var/tools/jaeger/jaeger >"$LOGS/jaeger.log" 2>&1 & echo $! >"$RUN/jaeger.pid"
    wait_http "http://127.0.0.1:16686/api/services" "data" 20 && echo "jaeger       started  http://127.0.0.1:16686 (OTLP :4318)" \
      || { echo "jaeger       FAILED — see var/logs/jaeger.log"; exit 1; }; fi
  # the MCP servers, all started the same way (start_mcp: name, module, port) — a fifth is one line
  start_mcp adoit-mcp    lab.substrate.mcp.adoit.server    9100   # ArchiMate engine + ADOIT facade
  start_mcp semantic-mcp lab.substrate.mcp.semantic.server 9200   # vocabularies/legality/SPARQL (read-only, all teams)
  start_mcp storage-mcp  lab.substrate.mcp.storage.server  9300   # READ-ONLY upload store: the only way a workload reads an input
  start_mcp workflow-mcp lab.substrate.mcp.workflow.server 9400   # business processes: <process>_submit/_status/_result (async)
                                                                  # + the approval gate: approvals_list/_get/_decide (human)
  # graph-mcp is started ALWAYS, unlike the approval channels, and that is deliberate: with no
  # GRAPH_CLIENT_ID it still answers collab_capabilities with the exact settings and grants that are
  # missing, which is the provisioning experience. A skipped server would instead make the gateway
  # report zero collab_* tools, which looks like a grant problem and is the confusion this whole
  # server is built to prevent.
  start_mcp graph-mcp    lab.substrate.mcp.graph.server    9500   # collaboration (alias collab_mcp): files + meetings by handle,
                                                                  # collab_fetch streams content into the upload store
  # gateway: the governance plane (LLM /v1, MCP /mcp, registry, skills)
  if alive litellm; then echo "gateway      ok  already running (pid $(cat $RUN/litellm.pid))"; else
    free_port 4000                        # ensure :4000 is free so the gateway never binds a random port
    env -u ANTHROPIC_API_KEY nohup "$LITELLM" --config config/litellm-config.yaml --port 4000 >"$LOGS/litellm.log" 2>&1 & echo $! >"$RUN/litellm.pid"
    printf "gateway      starting"; wait_http "http://127.0.0.1:4000/health/readiness" '"connected"' 90 \
      && echo "  http://127.0.0.1:4000  (db connected)" || { echo "  FAILED — see var/logs/litellm.log"; exit 1; }; fi
  review
  channels
  render_clients
  status_gateway
}

status_gateway() {
  load_env 2>/dev/null || true
  local auth="Authorization: Bearer ${LITELLM_MASTER_KEY:-}"
  echo "models       $(curl -s http://127.0.0.1:4000/v1/models -H "$auth" | $PY -c 'import json,sys; print(", ".join(m["id"] for m in json.load(sys.stdin)["data"]))' 2>/dev/null || echo '?')"
  echo "mcp servers  $($PY - <<PYEOF 2>/dev/null || echo '?'
import yaml; print(", ".join(yaml.safe_load(open("config/litellm-config.yaml")).get("mcp_servers",{}).keys()))
PYEOF
)"
  echo "skills       $(curl -s "http://127.0.0.1:4000/v1/skills?beta=true&custom_llm_provider=litellm_proxy" -H "$auth" | $PY -c 'import json,sys; print(", ".join(s["display_title"] for s in json.load(sys.stdin).get("data",[])) or "none")' 2>/dev/null || echo '?')"
  echo "approvals    pending: $(env -u ANTHROPIC_API_KEY $PY -m lab.substrate.approvals count 2>/dev/null || echo '?')  (./lab.sh review | python -m lab.substrate.approvals list)"
  echo "registry ui  http://127.0.0.1:4000/ui  (admin / master key)"
  echo "traces ui    ${JAEGER_UI_URL:-http://127.0.0.1:16686}  services: $(curl -s --max-time 5 "${JAEGER_UI_URL:-http://127.0.0.1:16686}/api/services" | $PY -c 'import json,sys; print(", ".join(json.load(sys.stdin).get("data") or []) or "none yet")' 2>/dev/null || echo '?')"
}

# Render env-specific client settings from templates (values from .env: GATEWAY_URL,
# ENTRA_GATEWAY_AUDIENCE). Regenerate whenever the gateway moves (localhost -> cloud/APIM)
# or the audience changes. Rendered files are git-ignored; templates are committed.
render_clients() {
  load_env
  local n=0
  for tpl in config/clients/*/settings.template.json; do
    [ -e "$tpl" ] || continue
    out="${tpl%.template.json}.json"
    sed -e "s#\${GATEWAY_URL}#${GATEWAY_URL:-http://127.0.0.1:4000}#g" \
        -e "s#\${ENTRA_GATEWAY_AUDIENCE}#${ENTRA_GATEWAY_AUDIENCE:-}#g" "$tpl" > "$out"
    n=$((n+1))
  done
  echo "clients      rendered $n settings from templates (GATEWAY_URL=${GATEWAY_URL:-http://127.0.0.1:4000})"
  echo "             copy config/clients/claude-code/settings.json -> your project's .claude/settings.json"
}

review() {
  load_env
  if alive review; then echo "review app   ok  http://127.0.0.1:8501 (pid $(cat $RUN/review.pid))"; else
    env -u ANTHROPIC_API_KEY nohup "$ROOT/.venv/bin/streamlit" run src/lab/substrate/review/app.py --server.port 8501 --server.headless true \
      >"$LOGS/review.log" 2>&1 & echo $! >"$RUN/review.pid"
    wait_http "http://127.0.0.1:8501/healthz" "ok" 30 && echo "review app   started  http://127.0.0.1:8501" \
      || { echo "review app   FAILED — see var/logs/review.log"; exit 1; }; fi
}

# The approval channels that are configured (see start_channel). `./lab.sh channels` restarts just these.
channels() {
  load_env
  for_each_channel start_channel
}

down() {
  for_each_channel stop_channel
  for s in wf-visio review litellm graph-mcp workflow-mcp storage-mcp semantic-mcp adoit-mcp jaeger; do
    if alive "$s"; then kill "$(cat "$RUN/$s.pid")" && echo "$s stopped"; fi; rm -f "$RUN/$s.pid"; done
  load_env 2>/dev/null || true; remote_tracing && railway_jaeger down
  pkill -f "litellm --config config/litellm-config.yaml" 2>/dev/null || true
  for m in adoit semantic storage workflow graph; do pkill -f "lab.substrate.mcp.$m.server" 2>/dev/null || true; done
  pkill -f "lab.workloads.visio_to_archimate.consumer" 2>/dev/null || true
}

status() {
  load_env 2>/dev/null || true
  if remote_tracing; then railway_jaeger status; else alive jaeger && echo "jaeger    running (pid $(cat $RUN/jaeger.pid))" || echo "jaeger    stopped"; fi
  for s in adoit-mcp semantic-mcp storage-mcp workflow-mcp graph-mcp litellm wf-visio; do alive "$s" && echo "$s    running (pid $(cat $RUN/$s.pid))" || echo "$s    stopped"; done
  # the review app is reported by its HEALTH endpoint, not its pid file: streamlit's recorded pid
  # goes stale across a manual restart while the app keeps serving :8501 (observed), and "stopped"
  # for a running approval UI is exactly the wrong answer
  curl -s --max-time 3 http://127.0.0.1:8501/healthz 2>/dev/null | /usr/bin/grep -q ok \
    && echo "review    running (http://127.0.0.1:8501)" || echo "review    stopped"
  for_each_channel channel_status
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
  env -u ANTHROPIC_API_KEY nohup "$PY" -m lab.workloads.visio_to_archimate.consumer >"$LOGS/wf-visio.log" 2>&1 & echo $! >"$RUN/wf-visio.pid"
  echo "wf-visio started  (consumer of workflow:requests; log: $LOGS/wf-visio.log)"
}

case "${1:-}" in
  up) up;; down) down;; status) status;; review) review;; channels) channels;; clients) render_clients;; consumer) consumer;;
  cloud) shift; cloud "$@";;
  *) echo "usage: $0 up|down|status|review|channels|consumer|clients | cloud substrate up|down|status"; exit 2;;
esac
