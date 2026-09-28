"""The guardrail mapping's ROWS — which row is the baseline, and what the new kinds of row mean.

Measured 28 Sep 2026 on the CAFÉ bundle. `_mapping_rows` filed every row that is not an E/I class
under "BASELINE", so the last such row WON. The bundle added two — a clinical domain floor and an
estate-level row that says outright it is "not from facet vectors" — and every step's baseline
became the estate row: G01 prompt integrity, G03 agent identity, G04 component admission, G10
registration and G15 ontology conformance vanished from every control set, and nothing failed.

The same bundle names G09 TWICE in E2 — "human confirmation, or a policy-bounded gate" and "approver
holds a current, role-specific authorisation" — two requirements under one guardrail. Keyed by
guardrail alone the second erased the first, and at E3 the authorisation clause was dropped when
E3 restated G09's confirmation mode.
"""
from pathlib import Path

import pytest

from lab.core.reference import master
from lab.core.usecase import obligations as O

ROOT = Path(__file__).resolve().parents[4]
_M = master.parse((ROOT / "src/lab/core/usecase/seed/masters/guardrail_mapping.md").read_text())
MAPPING = [dict(zip(_M.headers, row)) for row in _M.rows]


def _ids(exposure=0, influence=0, domain="general"):
    return {o.guardrail for o in O.mandatory_for(exposure, influence, mapping_rows=MAPPING,
                                                 domain=domain) if o.guardrail}


def _g09(exposure):
    rows = [o for o in O.mandatory_for(exposure, 0, mapping_rows=MAPPING) if o.guardrail == "G09"]
    assert len(rows) == 1, f"one G09 obligation per class, got {rows}"
    return rows[0]


def test_the_baseline_is_the_row_LABELLED_baseline_whatever_follows_it():
    assert {"G01", "G03", "G04", "G10", "G14", "G15", "G06"} <= _ids()


def test_an_ESTATE_LEVEL_guardrail_never_enters_a_step_control_set():
    """The row says it: evaluated at registration and as standing estate checks, "not from facet
    vectors". G14 and G28 are also in the baseline, so they are the only overlap."""
    estate_only = {"G27", "G30", "G31", "G32"}
    for exposure in range(4):
        for influence in range(4):
            assert not estate_only & _ids(exposure, influence, "clinical"), (exposure, influence)


def test_the_DOMAIN_FLOOR_applies_to_a_clinical_step_and_only_to_one():
    assert {"G26", "G29"} <= _ids(domain="clinical")
    assert "G26" not in _ids(domain="financial")


def test_the_estate_rows_are_still_READABLE_for_the_registration_check():
    """Not applied to a step is not discarded: a registration check reads them."""
    assert {"G27", "G30", "G31", "G32"} <= {o.guardrail for o in O.estate_level(MAPPING)}


def test_a_row_the_parser_does_not_know_is_REFUSED_rather_than_guessed():
    rows = MAPPING + [{"Class": "Weekend floor — Saturdays", "Mandatory": "G05 something"}]
    with pytest.raises(O.ObligationError, match="Weekend floor"):
        O.mandatory_for(0, 0, mapping_rows=rows)


def test_both_G09_clauses_stand_at_E2():
    text = _g09(2).text
    assert "policy-bounded gate" in text and "role-specific authorisation" in text


def test_E3_overrides_the_confirmation_mode_and_KEEPS_the_authorisation_clause():
    g09 = _g09(3)
    assert "not sufficient" in g09.text, "E3's stronger confirmation mode stands"
    assert "or a policy-bounded gate whose policy" not in g09.text, "the weaker mode is overridden"
    assert "role-specific authorisation" in g09.text, "an orthogonal E2 clause is still inherited"
    assert g09.source.startswith("E3"), g09.source
