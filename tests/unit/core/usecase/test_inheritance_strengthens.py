"""Inheritance must STRENGTHEN an obligation, not be shadowed by the class it inherits from.

Audited 23 Sep 2026. `_obligations_from` keyed `seen` on the guardrail NUMBER alone, and
`_resolve("E3")` recurses into E2 first — so E2's G09 ("human confirmation, **or a policy-bounded
gate** whose policy is D0-evaluable") was added, and E3's own G09 ("per-action human
authorisation — **a policy-bounded gate is not sufficient at this class**") was dropped as a
duplicate.

The failure is not that a control went missing: it is that the reviewer was handed, as the
mandatory control for an irreversible financial commitment, the sentence saying the weaker thing
is acceptable — which is exactly what the published table says it is not.

A higher class re-stating a guardrail is overriding it. Keyed on `(class, id)`, the later (higher)
row supersedes the inherited one.
"""
import json
from pathlib import Path

from lab.core.reference import master
from lab.core.usecase import obligations

ROOT = Path(__file__).resolve().parents[4]
#: The PUBLISHED mapping, so this measures the rules the runs actually read.
_M = master.parse((ROOT / "src/lab/core/usecase/seed/masters/guardrail_mapping.md").read_text())
MAPPING = [dict(zip(_M.headers, row)) for row in _M.rows]


def _texts(exposure, influence=0):
    return [(o.source, o.guardrail, o.text)
            for o in obligations.mandatory_for(exposure, influence, mapping_rows=MAPPING)]


def test_the_higher_class_text_supersedes_the_one_it_inherits():
    rows = [(s, g, t) for s, g, t in _texts(3) if g == "G09"]
    assert rows, "G09 is mandated at exposure 3"
    assert len(rows) == 1, f"a guardrail is mandated once, got {rows}"
    source, _, text = rows[0]
    assert source == "E3", "the strengthened row is the one that stands"
    assert "not sufficient" in text, text


def test_the_inherited_text_still_stands_at_its_own_class():
    rows = [(s, g, t) for s, g, t in _texts(2) if g == "G09"]
    assert len(rows) == 1 and rows[0][0] == "E2"
    assert "policy-bounded gate" in rows[0][2] and "not sufficient" not in rows[0][2]


def test_everything_the_lower_class_mandates_is_still_mandated_at_the_higher_one():
    """Overriding one clause must not drop the rest of what was inherited."""
    lower = {g for _, g, _ in _texts(2) if g}
    higher = {g for _, g, _ in _texts(3) if g}
    assert lower <= higher, f"inheriting E2 lost {sorted(lower - higher)}"


def test_a_guardrail_is_never_mandated_twice():
    for exposure in (0, 1, 2, 3):
        ids = [g for _, g, _ in _texts(exposure) if g]
        assert len(ids) == len(set(ids)), f"exposure {exposure}: duplicates in {ids}"
