"""The component catalogue, the capability map's links to it, and the price catalogue — the DATA
invariants deterministic cost rests on. Written against the committed seed, so a re-run of the
extractor without `scripts/seed_components.py`, or a hand edit that breaks a reference, fails here
rather than as a gap flag on the single largest cost line.
"""
import json
from pathlib import Path

from lab.core.semantic.ids import content_id

SEED = Path(__file__).resolve().parents[4] / "src" / "lab" / "core" / "usecase" / "seed"


def _load(name):
    return json.loads((SEED / f"{name}.json").read_text())


def _components():
    return _load("reference_architecture")["components"]


def test_every_component_has_the_content_addressed_id_first():
    for row in _components():
        cid, zone, name = row[0], row[1], row[2]
        assert cid == content_id("cmp-", zone, name), row


def test_every_component_a_capability_names_exists():
    ids = {row[0] for row in _components()}
    for cap in _load("ai_capability_map")["capabilities"]:
        assert set(cap.get("components", [])) <= ids, cap["capability"]


def test_a_generic_word_never_admits_a_component():
    """`System` occurs in "system of record" and "Agentic AI Systems"; each such match admitted an
    experience-zone client channel to a row about compute — a wrong component under G04."""
    system = content_id("cmp-", "exp", "System")
    for cap in _load("ai_capability_map")["capabilities"]:
        assert system not in cap.get("components", []), cap["capability"]


def test_every_priced_component_is_admitted_by_some_capability_row():
    """G04: a design may select only what the capability map admits, so a priced component no row
    links is a price line no legitimate design can ever use — the provisioned frontier model was
    one of four such before this test existed."""
    admitted = {c for cap in _load("ai_capability_map")["capabilities"]
                for c in cap.get("components", [])}
    priced = {line["component"] for line in _load("component_prices")["prices"]}
    assert priced <= admitted, sorted(priced - admitted)


def test_every_price_line_names_a_catalogue_component_and_is_driven_or_flat():
    ids = {row[0] for row in _components()}
    lines = _load("component_prices")["prices"]
    assert lines
    keys = set()
    for line in lines:
        assert line["component"] in ids, line
        assert "banded" not in line, "a boolean through a markdown master comes back as text"
        if line["volume_driver"] == "none":
            assert line["expected_at"] == line["high_at"] == 0
        else:
            assert line["volume_driver"] in ("runs_per_month", "users", "records")
            assert 0 < line["expected_at"] < line["high_at"]
        assert line["opex_low"] <= line["opex_expected"] <= line["opex_high"]
        assert set(line["envelope_in"]) <= {"low", "expected", "high"} and line["envelope_in"]
        keys.add((line["component"], line["variant"]))
    assert len(keys) == len(lines), "the natural key (component, variant) is unique"


def test_the_price_catalogue_says_which_columns_are_the_sheet_s_and_which_are_placeholders():
    caveat = _load("component_prices")["_caveat"]
    for column in ("variant", "envelope_in", "volume_driver", "expected_at", "capex_once"):
        assert column in caveat


def test_intake_captures_the_volume_assumptions_cost_is_banded_on():
    intake = _load("intake_fields")
    rows = {r[0]: r for r in intake["field_groups"]["rows"]}
    assert "Volume assumptions" in rows
    for driver in ("Runs per month", "users", "records"):
        assert driver.lower() in rows["Volume assumptions"][1].lower()
    assert "seed_components" in intake["_source"], "the docx is not the source of that row"
