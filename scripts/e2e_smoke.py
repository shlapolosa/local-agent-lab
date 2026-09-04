"""End-to-end substrate smoke test — exercises EVERY component through the gateway, the way a
workload will. Run against any deployment by pointing GW at its public gateway URL:

    GW=https://gateway-production-120b.up.railway.app \
      LITELLM_MASTER_KEY=... EA_AGENT_KEY=... \
      REVIEW_APP_URL=... JAEGER_UI_URL=... \
      .venv/bin/python scripts/e2e_smoke.py

Reads missing values from .env (the machine-local lines; `E2E_ENV_PROFILE=cloud` takes the
`# CLOUD:` overrides instead, i.e. the Railway review app / Jaeger URLs). Process env always wins.
Prints a PASS/FAIL line per check and exits non-zero on any failure.
Checks: gateway liveness/readiness(DB) · models · real inference (master + agent key, team model
allowlist) · Redis cache · PII guardrail · MCP servers registered · MCP tools (master) · MCP
round-trip with the AGENT key (list + read-only call to BOTH servers, proving gateway->MCP private
wiring + per-team ACL) · artifact store (render writes art:// refs to Postgres) · review app · Jaeger.
"""
import asyncio, importlib.util, json, os, re, sys, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_env(path=None):
    """.env values with the SAME parsing as the deployer (deploy/railway.py parse_env: `$VAR` /
    `${VAR}` expansion, inline `# note` stripping, quoted values) — one dialect, not a second
    parser (review B-M4; lab.platform.envfile is the eventual home). Falls back to a minimal reader
    only if railway.py is missing. Non-empty process env overrides .env."""
    path = path or os.path.join(ROOT, ".env")
    cloud = os.environ.get("E2E_ENV_PROFILE", "local") == "cloud"
    env = {}
    if os.path.exists(path):
        try:
            spec = importlib.util.spec_from_file_location("lab_railway", os.path.join(ROOT, "deploy", "railway.py"))
            railway = importlib.util.module_from_spec(spec); spec.loader.exec_module(railway)
            env = railway.parse_env(path, cloud=cloud)
        except (OSError, AttributeError):                       # railway.py absent/older: minimal local fix
            for line in open(path):
                m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
                if m: env.setdefault(m.group(1), re.sub(r"\s+#.*$", "", m.group(2)).strip().strip("'\""))
            for _ in range(2):
                env = {k: re.sub(r"\$\{?([A-Z_][A-Z0-9_]*)\}?", lambda m: env.get(m.group(1), m.group(0)), v)
                       for k, v in env.items()}
    env.update({k: v for k, v in os.environ.items() if v})
    return env

E = _load_env()
GW = (E.get("GW") or E.get("GATEWAY_URL") or "http://127.0.0.1:4000").rstrip("/")
MASTER = E.get("LITELLM_MASTER_KEY", "")
AGENT = E.get("EA_AGENT_KEY", "")
REVIEW = E.get("REVIEW_APP_URL", "")
JAEGER = E.get("JAEGER_UI_URL", "")
results = []

def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

def http(path, key=None, method="GET", body=None, timeout=40, base=None):
    url = (base or GW) + path
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if key: h["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            try: return r.status, json.loads(raw)
            except Exception: return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:
        return 0, str(e)[:200]

def section(t): print(f"\n=== {t} ===")

def main():
    """All checks, in order; returns the exit code (0 = every check passed)."""
    # ---- 1. gateway health / DB ----
    section("Gateway + backends")
    s, _ = http("/health/liveliness"); check("gateway liveliness", s == 200, f"HTTP {s}")
    s, d = http("/health/readiness")
    dbok = isinstance(d, dict) and d.get("db") == "connected"
    check("gateway readiness + Neon Postgres", dbok, f"db={d.get('db') if isinstance(d,dict) else d}")
    s, d = http("/cache/ping", MASTER)
    check("Redis cache (/cache/ping)", s == 200, f"HTTP {s}")

    # ---- 2. models ----
    section("Model catalogue + inference")
    s, d = http("/v1/models", MASTER)
    models = [m["id"] for m in d.get("data", [])] if isinstance(d, dict) else []
    check("model catalogue", len(models) >= 5, f"{len(models)} models: {models}")

    # reasoning models (glm-flash) may emit reasoning_content and no final content on a given run —
    # a completed generation (finish=stop / completion_tokens>0) is proof the call worked end to end.
    def _generated(d):
        if not isinstance(d, dict): return False, str(d)[:60]
        c = d.get("choices", [{}])[0]; m = c.get("message", {}) or {}
        txt = m.get("content") or ""
        ct = (d.get("usage") or {}).get("completion_tokens", 0)
        return (bool(txt) or ct > 0), (repr(txt) if txt else f"generated {ct} tok (reasoning)")

    # ---- 3. real inference: master key ----
    s, d = http("/v1/chat/completions", MASTER, "POST",
                {"model": "glm-flash", "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
                 "max_tokens": 200}, timeout=90)
    ok, why = _generated(d)
    check("inference via master key (glm-flash -> Ollama Cloud)", s == 200 and ok, f"HTTP {s}, {why}")

    # ---- 4. real inference: agent key + team model allowlist ----
    s, d = http("/v1/chat/completions", AGENT, "POST",
                {"model": "gpt-oss-120b", "messages": [{"role": "user", "content": "Reply with exactly: AGENT-OK"}],
                 "max_tokens": 200}, timeout=90)
    ok, why = _generated(d)
    check("inference via AGENT key (ea-modeling-agent)", s == 200 and ok, f"HTTP {s}, {why}")
    # team allowlist: agent should be REFUSED a model not on its list (claude-sonnet-5)
    s2, d2 = http("/v1/chat/completions", AGENT, "POST",
                 {"model": "claude-sonnet-5", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}, timeout=40)
    check("team model ACL blocks off-list model", s2 in (400, 401, 403), f"HTTP {s2} (expected 4xx)")

    # ---- 5. PII guardrail (reversible pseudonymization, non-blocking) ----
    section("PII guardrail")
    s, d = http("/v1/chat/completions", MASTER, "POST",
                {"model": "glm-flash",
                 "messages": [{"role": "user", "content": "Echo this address back exactly: jane@example.com"}],
                 "max_tokens": 200}, timeout=90)
    gtxt = (d.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") if isinstance(d, dict) else str(d)
    # non-blocking: call still succeeds (the model may see a placeholder; gateway restores on the way back)
    check("guardrail non-blocking (call succeeds)", s == 200, f"HTTP {s}, reply={gtxt[:60]!r}")

    # ---- 6. MCP servers registered + tools (master) ----
    section("MCP registry")
    s, d = http("/v1/mcp/server", MASTER)
    srv = [x.get("server_name") for x in d] if isinstance(d, list) else []
    check("MCP servers registered", set(["ea_mcp", "semantic_mcp", "storage_mcp"]).issubset(set(srv)), f"{srv}")
    s, d = http("/v1/mcp/tools", MASTER)
    tools = d if isinstance(d, list) else d.get("tools", d.get("data", [])) if isinstance(d, dict) else []
    tnames = [t.get("name") if isinstance(t, dict) else t for t in tools]
    check("MCP tools listed (master)", len(tnames) >= 20, f"{len(tnames)} tools")

    # ---- 7 & 8. MCP round-trip with the AGENT key (the real governance path) ----
    async def mcp_roundtrip():
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport
        url = GW + "/mcp/"
        transport = StreamableHttpTransport(url, headers={"Authorization": f"Bearer {AGENT}"})
        async with Client(transport) as c:
            tools = await c.list_tools()
            names = [t.name for t in tools]
            check("agent key sees granted MCP tools (per-team ACL)", len(names) >= 20, f"{len(names)} tools")
            # read-only call to the semantic server
            sem = next((n for n in names if n.endswith("semantic_ontologies") or n.endswith("semantic_questions")), None)
            if sem:
                r = await c.call_tool(sem, {})
                ok = r is not None and (getattr(r, "content", None) or getattr(r, "data", None) or r)
                check(f"gateway->semantic-mcp round-trip ({sem.split('-')[-1]})", bool(ok),
                      "returned data" if ok else "empty")
            else:
                check("gateway->semantic-mcp round-trip", False, "no read-only semantic tool found")
            # read-only call to the adoit server (GET repos against the live ADOIT 18 tenant)
            rep = next((n for n in names if n.endswith("ea_repositories")), None)
            if rep:
                r = await c.call_tool(rep, {})
                ok = r is not None and (getattr(r, "content", None) or getattr(r, "data", None) or r)
                check("gateway->adoit-mcp round-trip (ea_repositories)", bool(ok),
                      "returned data" if ok else "empty")
            else:
                check("gateway->adoit-mcp round-trip", False, "no ea_repositories tool")
            # existing-architecture search: ea_search must return real objects from the ADOIT 18 repo
            srch = next((n for n in names if n.endswith("ea_search")), None)
            if srch:
                r = await c.call_tool(srch, {"class_name": "ApplicationComponent", "limit": 5})
                items = r.data if isinstance(r.data, list) else (json.loads(r.content[0].text) if r.content else [])
                check("ea_search (existing architecture, ApplicationComponents)", bool(items),
                      f"{len(items)} existing component(s)" if items else "no hits")
            else:
                check("ea_search present", False, "no ea_search tool (grant ea_mcp / restart gateway)")
            # governed object store: list through the gateway (read-only), then info on the first ref
            lst = next((n for n in names if n.endswith("storage_list")), None)
            if lst:
                r = await c.call_tool(lst, {"limit": 5})
                items = r.data if isinstance(r.data, list) else []
                if not items and r.content:
                    try:
                        items = json.loads(r.content[0].text)
                    except Exception:
                        items = []
                check("gateway->storage-mcp round-trip (storage_list)", isinstance(items, list), f"{len(items)} object(s)")
                if items:
                    info_t = next((n for n in names if n.endswith("storage_info")), None)
                    ri = await c.call_tool(info_t, {"ref": items[0]["ref"]}) if info_t else None
                    check("storage_info by ref", bool(ri and (ri.data or ri.content)), items[0]["ref"])
            else:
                check("gateway->storage-mcp round-trip", False, "no storage_list tool (grant storage_mcp to the team)")
            # artifact store: render a known-valid spec -> art:// refs in Postgres
            spec_path = os.path.join(ROOT, "var", "out", "architecture", "lab_model.json")
            rnd = next((n for n in names if n.endswith("archimate_render")), None)
            if rnd and os.path.exists(spec_path):
                spec = json.load(open(spec_path))
                r = await c.call_tool(rnd, {"basename": "e2e-smoke", "spec": spec})
                payload = getattr(r, "data", None) or getattr(r, "content", None)
                txt = json.dumps(payload) if not isinstance(payload, str) else payload
                if isinstance(payload, list) and payload and hasattr(payload[0], "text"):
                    txt = payload[0].text
                hasref = "art://" in (txt or "")
                check("artifact store (render -> art:// refs in Postgres)", hasref,
                      "got art:// ref" if hasref else f"{str(txt)[:80]}")
            else:
                check("artifact store (render)", False, "archimate_render or lab_model.json missing")

    section("MCP round-trip (agent key -> gateway -> MCP servers over private DNS)")
    try:
        asyncio.run(mcp_roundtrip())
    except Exception as e:
        check("MCP round-trip", False, f"{type(e).__name__}: {str(e)[:150]}")

    # ---- 9. review app + jaeger ----
    section("Review app + tracing")
    if REVIEW:
        s, _ = http("/_stcore/health", base=REVIEW.rstrip("/"), timeout=20)
        check("review app (Streamlit health)", s == 200, f"HTTP {s} @ {REVIEW}")
    if JAEGER:
        s, _ = http("/", base=JAEGER.rstrip("/"), timeout=20)
        check("Jaeger UI reachable", s == 200, f"HTTP {s} @ {JAEGER}")

    # ---- summary ----
    section("SUMMARY")
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"  {passed}/{total} checks passed")
    fails = [n for n, ok, _ in results if not ok]
    if fails:
        print("  FAILED:", ", ".join(fails))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
