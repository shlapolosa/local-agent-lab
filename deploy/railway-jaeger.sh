#!/usr/bin/env bash
# Start/stop the Jaeger service on Railway (metered trial credit) without touching its config.
#   deploy/railway-jaeger.sh up | down | status
# Needs RAILWAY_TOKEN, RAILWAY_ENVIRONMENT_ID in .env (project token; Railway's API also
# requires a browser User-Agent). Service id is discovered from the environment.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; set -a; source "$ROOT/.env"; set +a
"$ROOT/.venv/bin/python" - "$1" <<'PY'
import json, os, sys, time, urllib.request
TOKEN, ENV = os.environ["RAILWAY_TOKEN"], os.environ["RAILWAY_ENVIRONMENT_ID"]
H = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/128 Safari/537.36",
     "Content-Type": "application/json", "Accept": "application/json", "Project-Access-Token": TOKEN}
def gql(q, v=None):
    r = json.load(urllib.request.urlopen(urllib.request.Request("https://backboard.railway.com/graphql/v2",
        data=json.dumps({"query": q, "variables": v or {}}).encode(), headers=H), timeout=60))
    if r.get("errors"): sys.exit(f"railway: {[e.get('message') for e in r['errors']]}")
    return r["data"]
PROJECT = os.environ["RAILWAY_PROJECT_ID"]
svc = gql('query($p:String!){ project(id:$p){ services{ edges{ node{ id name } } } } }', {"p": PROJECT})["project"]["services"]["edges"][0]["node"]
SID = svc["id"]
def latest():
    e = gql('query($s:String!,$e:String!){ deployments(first:1, input:{serviceId:$s, environmentId:$e}){ edges{ node{ id status } } } }', {"s": SID, "e": ENV})["deployments"]["edges"]
    return e[0]["node"] if e else {"id": None, "status": "NONE"}
cmd = sys.argv[1]
d = latest()
if cmd == "status":
    print(f"{svc['name']}: {d['status']}  ui={os.environ.get('JAEGER_UI_URL','?')}")
elif cmd == "up":
    if d["status"] == "SUCCESS": print("already running"); sys.exit()
    gql('mutation($s:String!,$e:String!){ serviceInstanceDeploy(serviceId:$s, environmentId:$e) }', {"s": SID, "e": ENV})
    for _ in range(24):
        time.sleep(10); d = latest()
        if d["status"] in ("SUCCESS", "FAILED", "CRASHED"): break
    print(f"deploy: {d['status']}  ui={os.environ.get('JAEGER_UI_URL','?')}")
elif cmd == "down":
    if d["status"] != "SUCCESS": print(f"nothing to stop ({d['status']})"); sys.exit()
    gql('mutation($id:String!){ deploymentRemove(id:$id) }', {"id": d["id"]}); print("stopped (config, variables, domains kept)")
else:
    sys.exit("usage: railway-jaeger.sh up|down|status")
PY
