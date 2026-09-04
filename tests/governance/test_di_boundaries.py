"""DI / hosting-boundary guard (user ask, Sep 3 2026: "confirm DI — especially Railway vs Azure").

Two mechanical invariants, checked by reading the source:
1. NO production module knows the hosting platform: the words "railway" / "Railway" appear only under
   `deploy/` (the Railway adapter) and in `.env`/docs. Production code addresses services only via
   `src/lab/platform/config.py` env vars (GATEWAY_URL, REDIS_URL, ARTIFACTS_URL, OTEL_*, …), so Azure = a different
   `.env` + a `deploy/azure.py` sibling — never a code change.
2. Configuration enters in ONE place: `os.environ` / `os.getenv` reads in production code are confined to
   `src/lab/platform/config.py` plus the composition roots (the hosts) — NOT inside domain/tool logic. This is a
   RATCHET: `KNOWN_ENV_READERS` lists today's remaining offenders (scheduled: A-F9 / C-H4); the test fails
   if a NEW file starts reading env, and must be tightened (entry removed) when one is fixed.
"""
import ast
import io
import os
import re
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PRODUCTION = ["src/lab"]
EXEMPT = {"tests", "__pycache__"}
# one-off scripts (CLAUDE.md: spikes/scripts exempt) — provisioning and bootstrap tools, run by a person
SCRIPT_PATTERNS = ("provision", "bootstrap_registry")
CONFIG = "src/lab/platform/config.py"
# composition roots: processes wire env -> config here (host/consumer/devui) — allowed by design
PROVIDER_ROOTS = ["src/lab/platform/container.py", "src/lab/substrate/container.py"]   # the ONLY files with `providers.*`
COMPOSITION_ROOTS = {"src/lab/workloads/visio_to_archimate/host.py", "src/lab/workloads/visio_to_archimate/consumer.py",
                     "src/lab/workloads/visio_to_archimate/devui_entry.py"}
# ratchet: files that still read env inside logic (each is a scheduled finding) — shrink, never grow
KNOWN_ENV_READERS = {
    "src/lab/workloads/visio_to_archimate/workflow.py",   # BA_MODE / ARCHITECT_MODE / VISIO_AGENT_MODEL (A-F9, C-H4)
    "src/lab/workloads/visio_to_archimate/agents.py",     # model + responses-store toggles
    "src/lab/substrate/gateway/custom_auth.py",                     # LiteLLM loads it by path; reads ENTRA_* / DEVELOPERS_TEAM_ID
    "src/lab/substrate/gateway/auto_router.py",                     # loaded by LiteLLM by path
    "src/lab/workloads/identity.py",                         # <PREFIX>_CLIENT_ID/SECRET/KEY lookup by prefix
    "src/lab/platform/otel.py",                             # OTEL_EXPORTER_OTLP_ENDPOINT
    "src/lab/substrate/approvals.py",                        # REVIEW_APP_URL in the request payload
    "src/lab/platform/workflows.py",                        # consumer name / review URL
    "src/lab/platform/docparse.py",                         # BA_MAX_* sizing knobs (should come from config)
    "src/lab/substrate/mcp/adoit/adoit_rest.py",                # ADOIT_* credentials (should come from config)
    "src/lab/substrate/review/app.py",                              # REVIEW_APP_PASSWORD / JAEGER_UI_URL
    "src/lab/substrate/mcp/storage/server.py",                  # UPLOADS_URL fallback
    "src/lab/substrate/mcp/adoit/server.py",                    # port
    "src/lab/core/semantic/reference/baguild.py",              # REFERENCE_MODELS_DIR
}
ENV_READ = re.compile(r"os\.environ(\.get)?\s*[\[(]|os\.getenv\s*\(")
PLATFORM = re.compile(r"railway", re.IGNORECASE)


def _py_files():
    for base in PRODUCTION:
        for dirpath, dirs, files in os.walk(os.path.join(ROOT, base)):
            dirs[:] = [d for d in dirs if d not in EXEMPT]
            for f in files:
                if f.endswith(".py") and not f.startswith("test_") and not any(k in f for k in SCRIPT_PATTERNS):
                    yield os.path.relpath(os.path.join(dirpath, f), ROOT)


def _src(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def _code(rel):
    """Source minus comments and string literals — docstrings may MENTION a platform; code may not."""
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(_src(rel)).readline):
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            out.append(tok.string)
    return " ".join(out)


def test_no_production_module_knows_the_hosting_platform():
    hits = [rel for rel in _py_files() if PLATFORM.search(_code(rel))]
    assert not hits, f"hosting platform named in production code (must live under deploy/): {hits}"


def test_env_reads_are_confined_to_config_roots_and_the_ratchet():
    readers = {rel for rel in _py_files() if ENV_READ.search(_src(rel))}
    new = readers - {CONFIG} - COMPOSITION_ROOTS - KNOWN_ENV_READERS
    assert not new, f"NEW env readers outside src/lab/platform/config.py — inject via config/params instead: {sorted(new)}"
    stale = {r for r in KNOWN_ENV_READERS if r not in readers and os.path.exists(os.path.join(ROOT, r))}
    assert not stale, f"ratchet: these no longer read env — remove them from KNOWN_ENV_READERS: {sorted(stale)}"


def test_providers_are_declared_only_in_the_composition_roots():
    """`providers.` / `DeclarativeContainer` (dependency-injector) appear in the two composition roots only."""
    hits = [rel for rel in _py_files()                       # _code() joins tokens with spaces
            if re.search(r"\bproviders\s*\.\s*\w+\s*\(|DeclarativeContainer", _code(rel))]
    assert sorted(hits) == PROVIDER_ROOTS, hits


def _builds_a_container(rel) -> bool:
    """True when the module calls `container.build(...)` / `build(...)` from a lab container module."""
    tree = ast.parse(_src(rel))
    module_aliases, build_aliases = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            for a in n.names:
                if n.module.endswith(".container") and a.name == "build":
                    build_aliases.add(a.asname or a.name)
                if n.module.startswith("lab.") and a.name == "container":
                    module_aliases.add(a.asname or a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.endswith(".container"):
                    module_aliases.add(a.asname or a.name)
    for c in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        f = c.func
        if isinstance(f, ast.Name) and f.id in build_aliases:
            return True
        if isinstance(f, ast.Attribute) and f.attr == "build" and isinstance(f.value, ast.Name) and f.value.id in module_aliases:
            return True
    return False


def test_every_composition_root_builds_its_container():
    """Each host is composed from `lab.platform.container.build(SERVICE)` — the ONE place clients come from
    (tracer, Redis); nothing below a composition root constructs a client."""
    missing = [rel for rel in sorted(COMPOSITION_ROOTS) if not _builds_a_container(rel)]
    assert not missing, f"composition roots that never call container.build(...): {missing}"


def test_config_is_the_single_service_address_book():
    """Every service address a workload/host uses is a config.py name (the Azure swap is an .env edit)."""
    from lab.platform import config
    for name in ("GATEWAY_URL", "REDIS_URL", "ARTIFACTS_URL", "ADOIT_MCP_URL", "SEMANTIC_MCP_URL",
                 "REVIEW_APP_URL", "JAEGER_UI_URL", "BIND_HOST"):
        assert hasattr(config, name), name


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
