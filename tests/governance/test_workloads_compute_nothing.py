"""The application ring orchestrates and computes nothing (TO-BE, 24 Oct 2026).

A workload may sequence, branch on a value a tool RETURNED, retry, wait and pass refs. A threshold, a
formula, a ranking or a fuzzy match is computation, and it belongs below the seam behind a typed
contract — in `lab.core` (pure) or in a provider's tool (which returns the decision, not the inputs).

This is a COARSE instrument, deliberately: it counts the shapes computation leaves in an AST —
a comparison against a non-trivial number or a threshold-named value, a score-ranked sort, a fuzzy
match. It misses joins. It is a ratchet, not a proof: the count per package may only fall, and
`lab.workloads.usecase` may hold only the orchestration modules named in ORCHESTRATION.
"""
import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKLOADS = os.path.join(ROOT, "src", "lab", "workloads")

TRIVIAL = {0, 1, -1}
NAMED = re.compile(r"threshold|floor|cutoff|margin|score|confidence|_min$|_max$|^min_|^max_", re.I)

# package -> markers accepted today. Shrink it; never grow it. "(top)" = modules directly in workloads/.
KNOWN = {
    "(top)": 2,
    "artifact_intake": 6,
    "artifact_publish": 1,
    "meeting_to_transcript": 2,
    "transcript_to_minutes": 2,
    "use_case_screening": 1,
    "usecase": 2,
    "visio_to_archimate": 6,
}

# What may remain in the shared use-case package: the modules that drive an agent, call the gateway or
# write the run board. Their pure halves (steps, mappers, coverage matching, outline, view inputs, provenance)
# live in lab.core.usecase since delta 2 (24 Oct 2026). A new module here is computation until shown otherwise.
ORCHESTRATION = {"agents", "coverage", "derivation", "identity", "modelling", "reference", "views"}


def _ident(node):
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else ""


def _threshold_like(node):
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value not in TRIVIAL
    return bool(NAMED.search(_ident(node)))


def markers(tree):
    """Yield (line, kind) for each computation shape in one module."""
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare) and any(_threshold_like(x) for x in (n.left, *n.comparators)):
            yield n.lineno, "threshold"
        elif isinstance(n, ast.Call):
            name, owner = _ident(n.func), _ident(getattr(n.func, "value", None))
            if owner == "difflib" or name in ("get_close_matches", "SequenceMatcher"):
                yield n.lineno, "fuzzy"
            elif name in ("sorted", "max", "min") and any(k.arg == "key" for k in n.keywords):
                yield n.lineno, "ranked"


def counts():
    out = {}
    for dirpath, dirs, files in os.walk(WORKLOADS):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith(".py"):
                continue
            path = os.path.join(dirpath, f)
            rel = os.path.relpath(path, WORKLOADS)
            pkg = rel.split(os.sep)[0] if os.sep in rel else "(top)"
            n = sum(1 for _ in markers(ast.parse(open(path, encoding="utf-8").read())))
            if n:
                out[pkg] = out.get(pkg, 0) + n
    return out


def test_no_workload_gains_computation():
    grew = {p: (n, KNOWN.get(p, 0)) for p, n in counts().items() if n > KNOWN.get(p, 0)}
    assert not grew, ("computation landed in the application ring (found, allowed) — move it to "
                      f"lab.core or into a provider tool that returns the decision: {grew}")


def test_the_ratchet_only_shrinks():
    now = counts()
    fell = {p: (now.get(p, 0), n) for p, n in KNOWN.items() if now.get(p, 0) < n}
    assert not fell, f"markers fell (now, KNOWN) — lower KNOWN to lock the gain in: {fell}"


def test_the_shared_use_case_package_holds_orchestration_only():
    pkg = os.path.join(WORKLOADS, "usecase")
    present = {f[:-3] for f in os.listdir(pkg) if f.endswith(".py") and f != "__init__.py"}
    assert present <= ORCHESTRATION, f"computation modules still in workloads.usecase: {present - ORCHESTRATION}"
