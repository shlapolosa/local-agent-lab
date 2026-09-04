"""TDD: a workload holds NO store credentials (CLAUDE.md invariant) — every artifact it persists goes
through the gateway (semantic_store_spec / storage-mcp), never `artifacts.store()` in-process. In the
cloud a workload has no ARTIFACTS_URL, so an in-process put would silently land in a container-local
file:// fallback (review W1b finding). Offline: source-level guard + the pure result-parsing helper."""
import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lab.workloads.visio_to_archimate.workflow import _ref_from  # noqa: E402

WORKLOAD_DIR = os.path.join(ROOT, "src", "lab", "workloads")
ALLOWED: set[str] = set()   # (the upload CLI now lives in lab.substrate.review.uploads)


def test_workload_modules_never_open_the_artifact_store():
    offenders = []
    for dirpath, _, files in os.walk(WORKLOAD_DIR):
        for f in files:
            if f.endswith(".py") and f not in ALLOWED:
                src = open(os.path.join(dirpath, f), encoding="utf-8").read()
                if re.search(r"artifacts\.store\(", src):
                    offenders.append(os.path.relpath(os.path.join(dirpath, f), ROOT))
    assert not offenders, f"in-process artifact store in a workload: {offenders}"


def _module_level_dotenv(path) -> bool:
    """A `load_dotenv(...)` call that runs on plain import (module scope, outside an `if __name__` guard
    or a function body)."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in tree.body:                                  # module scope only — nested bodies are entry points
        for c in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
            name = getattr(c.func, "id", None) or getattr(c.func, "attr", None)
            if name == "load_dotenv" and not isinstance(node, (ast.If, ast.FunctionDef, ast.AsyncFunctionDef,
                                                               ast.ClassDef)):
                return True
    return False


def test_importing_a_workload_module_never_loads_the_environment():
    """`.env` carries the SUBSTRATE's credentials (DATABASE_URL, S3_*, ADOIT_PASSWORD, the master key):
    importing a workload must not pull them into the process — that is what deploy strips from every
    workload service. A dev entry point may load it when it IS the script (`if __name__ == "__main__"`)."""
    offenders = [os.path.relpath(os.path.join(d, f), ROOT)
                 for d, _, files in os.walk(WORKLOAD_DIR) for f in files
                 if f.endswith(".py") and _module_level_dotenv(os.path.join(d, f))]
    assert not offenders, f"module-level load_dotenv in a workload — move it under `if __name__`: {offenders}"


def test_ref_from_accepts_dict_or_json_string_result():
    assert _ref_from({"spec_ref": "art://1/x"}) == "art://1/x"
    assert _ref_from('{"spec_ref": "art://2/y"}') == "art://2/y"   # MCP results may arrive as strings (AF #3313)
    assert _ref_from({"xml_ref": "art://3/z"}, "xml_ref") == "art://3/z"


def test_platform_container_keys_hold_no_store_url():
    """The workload container is built from lab.platform.container — its key list must not carry a store URL
    (ARTIFACTS_URL falls back to the DATABASE_URL DSN)."""
    from lab.platform.container import CONFIG_KEYS
    assert not [k for k in CONFIG_KEYS if k in ("ARTIFACTS_URL", "UPLOADS_URL", "DATABASE_URL") or k.startswith("S3_")]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
