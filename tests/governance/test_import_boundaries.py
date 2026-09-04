"""Tier import boundaries (restructure, Sep 2026) — checked by reading the source, offline.

  lab.core       imports only lab.core                  (domain: no adapters, no platform kernel)
  lab.platform   imports lab.platform + lab.core        (the kernel every tier shares)
  lab.substrate  imports substrate + platform + core    (never a workload)
  lab.workloads  imports workloads + platform + core    (NEVER the substrate: a workload holds no store
                                                         credentials and reaches the substrate only by URL)
KNOWN is a ratchet of today's accepted exceptions — shrink it, never grow it.
Run: .venv/bin/python tests/governance/test_import_boundaries.py   (also pytest-compatible)"""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "src")
TIERS = ("core", "platform", "substrate", "workloads")
ALLOWED = {"core": {"core"}, "platform": {"platform", "core"},
           "substrate": {"substrate", "platform", "core"}, "workloads": {"workloads", "platform", "core"}}
KNOWN = set()   # empty today — keep it that way


def _modules():
    mods = {}
    for dirpath, dirs, files in os.walk(os.path.join(SRC, "lab")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith(".py"):
                rel = os.path.relpath(os.path.join(dirpath, f), SRC)[:-3].replace(os.sep, ".")
                mods[rel[:-9] if rel.endswith(".__init__") else rel] = os.path.join(dirpath, f)
    return mods


def _tier(mod):
    parts = mod.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == "lab" and parts[1] in TIERS else None


def _imports(mod, path, mods):
    tree = ast.parse(open(path, encoding="utf-8").read())
    pkg = mod if path.endswith("__init__.py") else mod.rsplit(".", 1)[0]
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name.startswith("lab."):
                    yield a.name
        elif isinstance(n, ast.ImportFrom):
            if n.level:
                base = ".".join(pkg.split(".")[: len(pkg.split(".")) - (n.level - 1)])
                base = f"{base}.{n.module}" if n.module else base
            elif n.module and (n.module == "lab" or n.module.startswith("lab.")):
                base = n.module
            else:
                continue
            for a in n.names:
                cand = f"{base}.{a.name}"
                yield cand if cand in mods else base


def _violations():
    mods = _modules()
    out = set()
    for mod, path in mods.items():
        t = _tier(mod)
        if not t:
            continue
        for imp in _imports(mod, path, mods):
            ti = _tier(imp)
            if ti and ti not in ALLOWED[t]:
                out.add((mod, imp))
    return out


def test_tiers_import_only_downward_ratchet():
    viol = _violations()
    new, stale = viol - KNOWN, KNOWN - viol
    assert not new, f"new cross-tier imports (fix, or ratchet them in KNOWN with a reason): {sorted(new)}"
    assert not stale, f"ratchet: no longer violations — remove from KNOWN: {sorted(stale)}"


def test_workloads_never_import_the_substrate():
    hits = sorted((m, i) for m, i in _violations() if m.startswith("lab.workloads.") and i.startswith("lab.substrate."))
    assert not hits, f"a workload imports the substrate (store credentials would follow): {hits}"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
