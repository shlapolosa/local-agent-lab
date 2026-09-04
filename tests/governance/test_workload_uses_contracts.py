"""Governance: a workload names substrate tools ONLY through `lab.platform.contracts` — no bare tool-name
string literal (`storage_*`, `semantic_*`, `archimate_*`, `ea_*`, a `<server>_mcp` alias, or the
gateway-qualified `<server>_mcp-<tool>` form) anywhere under src/lab/workloads. That is what makes the
EA-repository port swappable: the workload spells `EATools.search`, so renaming a tool or its adapter is
a one-place change here, never an edit in the workload. AST-based like
tests/governance/test_di_boundaries.py: docstrings and comments may MENTION a tool; code may not spell one.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/governance/test_workload_uses_contracts.py"""
import ast
import os
import re

from lab.platform import contracts

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKLOADS = os.path.join(ROOT, "src", "lab", "workloads")
# a word that IS a tool name, a server alias, or a gateway-qualified tool name
FORBIDDEN = contracts.ALL_TOOLS | set(contracts.SERVERS) | \
    {cls.gateway(t) for cls in contracts.SERVERS.values() for t in cls.names()}
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


def _py_files():
    for dirpath, dirs, files in os.walk(WORKLOADS):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in sorted(files):
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


def _docstrings(tree) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def code_literals(path):
    """(lineno, text) of every string literal in CODE — plain strings and the constant parts of f-strings —
    excluding docstrings."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    docs = _docstrings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            yield node.lineno, node.value


def test_workloads_spell_no_tool_name_outside_the_contracts():
    hits = []
    for path in _py_files():
        for lineno, text in code_literals(path):
            words = set(WORD.findall(text))
            if words & FORBIDDEN:
                hits.append(f"{os.path.relpath(path, ROOT)}:{lineno}: {sorted(words & FORBIDDEN)} in {text[:60]!r}")
    assert not hits, "bare tool-name literals in a workload — use lab.platform.contracts:\n" + "\n".join(hits)


def test_the_guard_sees_f_string_parts_and_skips_docstrings(tmp_path):
    p = tmp_path / "m.py"
    p.write_text('"""storage_get in a docstring is fine."""\n'
                 'def f(x):\n    """ea_search mentioned."""\n    return f"call storage_get with {x}", "semantic_mcp"\n')
    found = {text for _, text in code_literals(str(p))}
    assert found == {"call storage_get with ", "semantic_mcp"}


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
