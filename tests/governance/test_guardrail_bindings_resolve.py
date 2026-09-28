"""Every published reference between the CAFÉ artifacts resolves — no ratchet, no exceptions.

The design rests on one chain: a step's facets fire a guardrail (M3), the guardrail names the
capability that enforces it (`cap`), the capability names the components that realise it, and a
component carries a price. Every hop is a join on a string, and nothing in this repository checked
that either side of any of them existed.

Measured 18 Sep 2026, before this file existed: **20 of the 24 live guardrails named an enforcement
point that resolved to no row in the technology capability map, and only 6 of 63 capabilities
enforced anything.** Nine were label drift against a row that did exist (`Semantic · Ontology` for
the map's `Semantic · Ontology (entities, rules)`), eleven named a control capability the map
genuinely lacked, and two were prose rather than a reference at all.

None of it failed anything. `families.unclaimed()` is designed to report a family whose guardrails
reach no capability as CORPUS SILENCE — a legitimate state, because the framework does not claim to
have catalogued every enforcement point — and a typo is indistinguishable from silence. So the
partiality that was meant to be a small, honest gap was most of the chain, and the only symptom was
a component-to-family mapping that quietly resolved almost nothing.

That is the general lesson this file exists to hold: **a join whose failure mode is an empty result
needs a check that the operands exist, because an empty result is what success looks like when the
data is genuinely silent.**

These assertions read the committed MASTERS — what is actually published, signed and pinned. They
used to read the seed JSON, which was the publish-time source until the CAFÉ workbook of 28 Sep
2026 replaced it; after that the seed JSON was an HTML-era fixture, and a check reading it would
have passed on a corpus that no longer existed. Since that workbook the join key is the technology
L3 id ("COG.11"), and the chain is: guardrail `cap` -> L3 -> realisation view row (`l3_id`) ->
`components`.
"""
import re

import pytest

from lab.core.usecase import capabilities, seed


_rows = seed.master_rows


def _capability_keys() -> set[str]:
    return {capabilities.key(row) for row in _rows("technology_capability_l3")}


def _realisations() -> list[dict]:
    return _rows("ai_capability_map")


def _live_guardrails() -> list[dict]:
    return seed.live_only(_rows("guardrails"))


def test_every_guardrail_names_an_enforcement_point_that_exists():
    """A guardrail's `cap` must resolve to a capability row.

    No ratchet. A reference the map cannot answer is either a typo or a capability the framework
    has not catalogued, and both are defects that must be fixed in the source artifact rather than
    tolerated here — the whole point is that the failure is otherwise invisible.
    """
    known = _capability_keys()
    dangling = sorted(
        f"{g['id']}: {ref!r}"
        for g in _live_guardrails()
        for ref in capabilities.refs(g.get("cap"))
        if ref not in known)
    assert not dangling, (
        f"{len(dangling)} guardrail enforcement points resolve to no capability in the technology "
        f"map. Each is either label drift against an existing row or a control capability the map "
        f"lacks; fix it in the CAFÉ source and re-extract, never by widening this test: {dangling}")


def test_every_live_guardrail_names_some_enforcement_point():
    """An invariant with nowhere to be checked is a wish. M4 states it: selection is not complete
    until every obligation resolves to a named enforcement point or is explicitly advisory."""
    naked = sorted(g["id"] for g in _live_guardrails() if not capabilities.refs(g.get("cap")))
    assert not naked, f"guardrails with no enforcement point at all: {naked}"


def test_every_live_guardrail_can_be_bound_to_SOME_component():
    """The hop after the one above, stated the way M4 states it: an obligation is bound when ANY of
    its enforcement points is a selected component. So the invariant is per GUARDRAIL — at least
    one of its capabilities reaches a component. A guardrail none of whose capabilities does can
    never be bound, and would read as an architect who selected nothing.

    It was per REFERENCE until 28 Sep 2026. The workbook then named people and assurance
    capabilities as secondary enforcement points — "PPL.03 Human oversight competence" beside G09's
    approval components, "RCV.05 Vendor agent assurance" beside G31's — which legitimately realise
    no product, and a per-reference rule would have demanded a component for a competence.
    """
    components = {capabilities.key(r): capabilities.refs(r.get("components"))
                  for r in _realisations()}
    never = sorted(g["id"] for g in _live_guardrails()
                   if not any(components.get(ref) for ref in capabilities.refs(g.get("cap"))))
    assert not never, (
        f"guardrails none of whose enforcement points reaches a component, so they can never be "
        f"bound to anything a design selects: {never}")


def test_every_realisation_row_realises_an_L3_the_map_has():
    """The second hop's own operand check: a realisation row for an L3 the map lacks is a row no
    match can ever reach."""
    orphan = sorted(r.get("l3_id", "?") for r in _realisations()
                    if capabilities.key(r) not in _capability_keys())
    assert not orphan, f"realisation rows for L3s the technology map does not have: {orphan}"


def test_every_family_trigger_names_a_guardrail_that_exists():
    """`family-triggers` is hand-translated from the framework's component-family table and the
    extractor cannot regenerate it, so it is the artifact most able to drift unnoticed."""
    known = {str(g["id"]) for g in _rows("guardrails")}      # retired ids stay resolvable
    unknown = sorted(
        f"{f['id']} -> {gid}"
        for f in _rows("family_triggers")
        for gid in capabilities.refs(f.get("guardrails"))
        if gid not in known)
    assert not unknown, f"family triggers naming a guardrail that does not exist: {unknown}"


def test_every_facet_is_read_by_a_guardrail_that_still_fires():
    """CAFÉ's own completeness test: a facet nothing fires on is decorative.

    Teams assign it, governance reviews it, and it changes nothing — which is how reversibility and
    blast radius came to set the risk class while playing no part in selecting the controls that
    class mandates. The framework ran this by hand in v0.25 and the guardrail set GREW as a result.
    Here it runs on every commit, and it also catches the other direction: a facet whose readers
    have all been retired reads as covered in the published table and is not.
    """
    live = {str(g["id"]) for g in _live_guardrails()}
    unread = sorted(
        row["Facet"] for row in _rows("facet_schema_readers")
        if not (set(re.findall(r"G\d+", str(row["Read by"]))) & live))
    assert not unread, (
        f"facets no live guardrail reads — collected, reviewed, and governing nothing: {unread}")


def test_every_capability_row_yields_a_whole_key():
    """A row with no L3 id is no key, and `capabilities.concepts` drops such a row — correctly, and
    silently. A 155-row map that publishes 152 candidates looks exactly like a 152-row map: the
    three missing capabilities are unmatched, unbound and unpriced for the life of that version."""
    half = sorted(str(r.get("name", "?")) for r in _rows("technology_capability_l3")
                  if not capabilities.key(r))
    assert not half, f"capability rows that cannot be addressed, and so cannot be matched: {half}"


def test_no_two_capability_rows_share_a_key():
    """The key is the join. Two rows sharing one means a guardrail binds to whichever the reader
    saw last, and the matcher offers one candidate where the map holds two."""
    for stem in ("technology_capability_l3", "ai_capability_map"):
        keys = [capabilities.key(r) for r in _rows(stem)]
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        assert not dupes, f"{stem}: duplicate capability keys: {dupes}"


def test_the_map_projects_to_exactly_as_many_candidates_as_it_has_rows():
    """Whatever the map publishes is what step 5 is shown. A projection that quietly loses rows is
    the same defect one layer along."""
    rows = _rows("technology_capability_l3")
    made = capabilities.concepts(rows, _rows("technology_capability_l1")
                                 + _rows("technology_capability_l2"))
    assert len([c for c in made if c["level"] == capabilities.LEVEL]) == len(rows)


@pytest.mark.parametrize("stem", ["technology_capability_l3", "ai_capability_map", "guardrails",
                                  "family_triggers"])
def test_the_artifact_is_not_silently_empty(stem):
    """Every assertion above passes vacuously over an empty list."""
    assert len(_rows(stem)) > 10
