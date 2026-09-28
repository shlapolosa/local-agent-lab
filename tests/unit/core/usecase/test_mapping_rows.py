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
import pytest

from lab.core.usecase import obligations as O, seed

MAPPING = seed.master_rows("guardrail_mapping")


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
    assert "G26" in _ids(domain="clinical")
    assert "G26" not in _ids(domain="financial")


def _one(gid, domain="general", exposure=0, influence=0):
    rows = [o for o in O.mandatory_for(exposure, influence, mapping_rows=MAPPING, domain=domain)
            if o.guardrail == gid]
    assert len(rows) == 1, rows
    return rows[0]


def test_a_floor_ADDS_to_the_baseline_and_never_replaces_it():
    """Review finding, 28 Sep 2026: the baseline's "G29 residency-gated routing on every model
    call" and the clinical floor's "G29 personal or health content to in-region … lanes only"
    shared a key, so the floor REPLACED the baseline for exactly the steps that carry health data.
    Every row is "Mandatory, IN ADDITION to the baseline"; override is only along an "All of"
    chain. (The previous version of this test asserted G29 was present — which the baseline
    guaranteed, so it could not fail.)"""
    g29 = _one("G29", "clinical")
    assert "every model call" in g29.text and "in-region" in g29.text, g29.text
    assert "baseline" in g29.source and "domain floor" in g29.source, g29.source


def test_an_I_row_never_overrides_an_E_row_it_does_not_inherit_from():
    """The E and I chains are independent rows; I merely comes later in the list."""
    rows = [{"Class": "Baseline", "M": "G01 base"},
            {"Class": "E1 — contained", "M": "G05 exposure wording"},
            {"Class": "I1 — contained", "M": "G05 influence wording"}]
    g05 = [o for o in O.mandatory_for(1, 1, mapping_rows=rows) if o.guardrail == "G05"][0]
    assert "exposure wording" in g05.text and "influence wording" in g05.text


def test_a_floor_row_names_the_domains_it_floors_and_a_negated_one_is_not_one():
    """"non-clinical" contains "clinical" after a hyphen, which a plain word match accepts. It floors
    no domain, so it is refused like any floor that floors nothing — never applied to clinical."""
    rows = [{"Class": "Baseline", "M": "G01 base"},
            {"Class": "Domain floor — non-clinical data", "M": "G26 retention"}]
    with pytest.raises(O.ObligationError, match="non-clinical"):
        O.mandatory_for(0, 0, mapping_rows=rows, domain="clinical")


def test_a_floor_row_that_names_no_known_domain_is_refused():
    rows = [{"Class": "Baseline", "M": "G01 base"},
            {"Class": "Domain floor — weekends", "M": "G26 retention"}]
    with pytest.raises(O.ObligationError, match="weekends"):
        O.mandatory_for(0, 0, mapping_rows=rows)


def test_the_estate_row_is_RECOGNISED_rather_than_refused_or_applied():
    """It says it is not derived from facets, so it applies to no step — but it is a known kind
    of row, so its presence must not refuse the derivation either."""
    assert _ids(3, 3, "clinical")                       # derives, does not raise


#: Where a class RESTATES a guardrail it inherits with FEWER clauses than it inherits, which of
#: the inherited clauses it replaces is decided by position — and the data never says so. Each
#: such restatement is listed here once a person has confirmed the position is the one meant;
#: a new one fails until somebody has. (Review finding F2, 28 Sep 2026: a mutation that restated
#: G09's SECOND clause at E3 silently dropped the first — the confirmation mode.)
#: Keyed by position, and PINNED BY CONTENT: position alone cannot tell which clause was meant —
#: the review's mutation restated the approver clause at position 0 and still matched a position-
#: only allowlist. The value is (the phrase the confirmed restatement contains, why).
PARTIAL_RESTATEMENTS = {
    ("E3", "G09", 0): ("per-action human authorisation",
                       "E3 restates G09's CONFIRMATION MODE and inherits E2's second clause, the "
                       "approver's authorisation, unchanged"),
}


def test_every_partial_restatement_in_the_published_mapping_was_confirmed_by_a_person():
    rows = O._mapping_rows(MAPPING)
    found, texts = set(), {}
    for label, cell in rows.items():
        m = O._INHERITS.search(cell)
        if not m:
            continue
        inherited = {}
        for key, _ in O._resolve(m.group(1).upper(), rows):
            if key[1]:
                inherited[key[1]] = inherited.get(key[1], 0) + 1
        own = {}
        for key, obligation in O._obligations_from(cell, label, label[0]):
            if key[1]:
                own[key[1]] = own.get(key[1], 0) + 1
                texts[(label, key[1], key[2])] = obligation.text
        for gid, n in own.items():
            if 0 < n < inherited.get(gid, 0):
                found |= {(label, gid, i) for i in range(n)}
    assert found <= set(PARTIAL_RESTATEMENTS), sorted(found - set(PARTIAL_RESTATEMENTS))
    for key in found:
        phrase, why = PARTIAL_RESTATEMENTS[key]
        assert phrase in texts[key], (f"{key} restates something other than what was confirmed "
                                      f"({why!r}): {texts[key]!r} — re-confirm which clause it "
                                      f"replaces before changing this entry")


def test_the_published_exposure_floor_is_the_one_exposure_derives():
    """Review finding F6: the floor row says "exposure not below N" and `exposure.DOMAIN_FLOOR`
    computes it. Two homes for one number drift silently — the control set would claim a floor the
    derivation does not apply."""
    import re
    from lab.core.usecase.exposure import DOMAIN_FLOOR
    for row in MAPPING:
        label, cell = str(list(row.values())[0]), str(list(row.values())[1])
        said = re.search(r"exposure not below (\d)", cell)
        if not label.lower().startswith("domain floor") or not said:
            continue
        for domain in O._floor_domains(label):
            assert DOMAIN_FLOOR.get(domain) == int(said.group(1)), (domain, label)


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
