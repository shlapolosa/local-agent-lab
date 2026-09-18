"""A consumable artifact is DATA the framework author owns — never a table in a Python file.

The strong half of this is already held elsewhere: `test_no_seed_reads_at_runtime.py` keeps every
runtime read on the governed corpus, so a published artifact can be changed and a run picks it up
with no image rebuild. This file holds the half that guards the way IN. The seeding scripts are a
translation layer between the framework's own HTML and the corpus, and a translation layer is where
content quietly accumulates: each entry looks like plumbing at the moment it is added, and the sum
is a second, private copy of the artifact that only a code change can correct.

It caught its own motivating case on 18 Sep 2026. Four new control capabilities failed to auto-link
to a component, and the first fix added four rows to `LINKED_BY_HAND` — four facts about the
framework, living in a script, invisible to the person who owns the framework. The right fix was to
name the enforcing component in the capability row itself, where the existing linker reads it; the
count below went back to what it was, and `seed_components.py` was left unchanged.

So: these tables may SHRINK and never grow. Growing one is not forbidden because it is wrong in
every case — it is forbidden because it is never the FIRST thing to try, and a number is the only
way to make "try the artifact first" a decision someone has to take deliberately.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: script -> {table: entries it may carry}. Each is a translation the SOURCE ARTIFACT cannot express
#: today, not a fact about the framework that belongs to its author. A number may only go DOWN.
BUDGET = {
    "scripts/seed_components.py": {
        # A product named in a capability row under a name the component catalogue spells
        # differently ("Azure Monitor" for "App Insights"). The artifact says one, the reference
        # architecture says the other, and neither is wrong.
        "ALIASES": 5,
        # Components no capability row names at all, because the row describes a choice rather than
        # a product — a model comes from the catalog, a secret from the vault.
        "LINKED_BY_HAND": 23,
        # Component names too generic for a substring match to be safe.
        "GENERIC": 3,
        # The price sheet's service names joined to catalogue components. The sheet is a separate
        # licensed artifact with no component column; Finance replaces the figures in the corpus.
        "PRICED": 12,
    },
}


def _size(path: Path, name: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            continue
        value = node.value
        if isinstance(value, ast.Dict):
            return len(value.keys)
        if isinstance(value, (ast.Set, ast.List, ast.Tuple)):
            return len(value.elts)
        if isinstance(value, ast.Call) and value.args:          # frozenset({...})
            inner = value.args[0]
            if isinstance(inner, (ast.Set, ast.List, ast.Tuple)):
                return len(inner.elts)
    raise AssertionError(f"{path.name}: no literal table named {name!r} — renamed or removed? "
                         f"Update the budget deliberately rather than deleting the check.")


@pytest.mark.parametrize("script,table,budget", [(s, t, b) for s, tables in BUDGET.items()
                                                 for t, b in tables.items()])
def test_a_translation_table_may_shrink_and_never_grow(script, table, budget):
    size = _size(ROOT / script, table)
    assert size <= budget, (
        f"{script}:{table} grew to {size} (budget {budget}). Before raising it, ask whether the "
        f"source artifact can carry this fact — a capability row naming its component in `primary` "
        f"is read by the existing linker and stays editable by the framework's author. Raise the "
        f"budget only for a translation the artifact genuinely cannot express.")


def test_the_budget_never_drifts_above_what_the_scripts_hold():
    """A budget above the real size is slack nobody decided to grant. Keep it exact, so the next
    addition is visible in the diff as a number going up."""
    loose = {f"{s}:{t} budget {b} but holds {_size(ROOT / s, t)}"
             for s, tables in BUDGET.items() for t, b in tables.items()
             if _size(ROOT / s, t) < b}
    assert not loose, f"tighten these to what the script actually carries: {sorted(loose)}"
