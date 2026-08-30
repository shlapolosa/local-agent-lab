#!/usr/bin/env bash
# lab.sh — bring the local agent lab up/down in one command.
#   ./lab.sh up      start redis (brew), adoit-mcp (:9100), litellm gateway (:4000); wait for health
#   ./lab.sh down    stop adoit-mcp + gateway (redis is left to brew services)
#   ./lab.sh status  what is running, what the gateway sees
# Every service is launched with `env -u ANTHROPIC_API_KEY`: only .env holds lab credentials —
# ambient shell keys must never reach the governance plane (see CLAUDE.md, Gateway Registry).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"; cd "$ROOT"
LOGS="$ROOT/logs"; RUN="$ROOT/.lab"; mkdir -p "$LOGS" "$RUN"
PY="$ROOT/.venv/bin/python"; LITELLM="$ROOT/.venv/bin/litellm"
export PATH="/opt/homebrew/opt/libpq/bin:$PATH"

need() { [ -e "$1" ] || { echo "missing $1 — $2"; exit 1; }; }
load_env() { need .env "create it from the keys listed in CLAUDE.md"; set -a; source .env; set +a; }
wait_http() { # url, grep-pattern, seconds
  for i in $(seq 1 "$3"); do curl -s --max-time 3 "$1" | /usr/bin/grep -q "$2" && return 0; sleep 1; done; return 1; }
alive() { [ -f "$RUN/$1.pid" ] && kill -0 "$(cat "$RUN/$1.pid")" 2>/dev/null; }

up() {
  load_env; need "$PY" "python3.12 -m venv .venv && .venv/bin/pip install 'litellm[proxy]' fastmcp prisma"
  # redis: governance state (rate limits, budgets, router) — Homebrew service
  if redis-cli -h "${REDIS_HOST:-127.0.0.1}" -p "${REDIS_PORT:-6379}" ping 2>/dev/null | /usr/bin/grep -q PONG; then
    echo "redis        ok  ${REDIS_HOST:-127.0.0.1}:${REDIS_PORT:-6379}"
  else brew services start redis >/dev/null && sleep 2 && echo "redis        started (brew services)"; fi
  # adoit-mcp: ArchiMate engine + ADOIT facade, registered with the gateway's MCP registry
  if alive adoit-mcp; then echo "adoit-mcp    ok  already running (pid $(cat $RUN/adoit-mcp.pid))"; else
    env -u ANTHROPIC_API_KEY nohup "$PY" mcp/adoit_mcp/server.py >"$LOGS/adoit-mcp.log" 2>&1 & echo $! >"$RUN/adoit-mcp.pid"
    wait_http "http://127.0.0.1:9100/mcp" "" 20 || true; echo "adoit-mcp    started  http://127.0.0.1:9100/mcp"; fi
  # gateway: the governance plane (LLM /v1, MCP /mcp, registry, skills)
  if alive litellm; then echo "gateway      ok  already running (pid $(cat $RUN/litellm.pid))"; else
    env -u ANTHROPIC_API_KEY nohup "$LITELLM" --config gateway/litellm-config.yaml --port 4000 >"$LOGS/litellm.log" 2>&1 & echo $! >"$RUN/litellm.pid"
    printf "gateway      starting"; wait_http "http://127.0.0.1:4000/health/readiness" '"connected"' 90 \
      && echo "  http://127.0.0.1:4000  (db connected)" || { echo "  FAILED — see logs/litellm.log"; exit 1; }; fi
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
  echo "registry ui  http://127.0.0.1:4000/ui  (admin / master key)"
}

down() {
  for s in litellm adoit-mcp; do
    if alive "$s"; then kill "$(cat "$RUN/$s.pid")" && echo "$s stopped"; fi; rm -f "$RUN/$s.pid"; done
  pkill -f "litellm --config gateway/litellm-config.yaml" 2>/dev/null || true
  pkill -f "mcp/adoit_mcp/server.py" 2>/dev/null || true
}

status() {
  for s in adoit-mcp litellm; do alive "$s" && echo "$s    running (pid $(cat $RUN/$s.pid))" || echo "$s    stopped"; done
  redis-cli ping 2>/dev/null | /usr/bin/grep -q PONG && echo "redis        running" || echo "redis        stopped"
  curl -s --max-time 3 http://127.0.0.1:4000/health/readiness | /usr/bin/grep -q '"connected"' && status_gateway || echo "gateway      not reachable"
}

case "${1:-}" in up) up;; down) down;; status) status;; *) echo "usage: $0 up|down|status"; exit 2;; esac
