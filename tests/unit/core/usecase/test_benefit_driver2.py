"""Driver 2 was structurally impossible: the schema says `volume`, the formula reads
`current_volume`.

Audited 23 Sep 2026. `benefit_inputs.schema.json` declares `quality_baseline.volume` with
`additionalProperties: false`, so the step-24 agent is FORBIDDEN by its own schema from emitting
the field `quality_improvement` requires. A fully supplied baseline therefore always returned
`requires_input: ['current_volume']`.

The effect is systemic rather than local: an unresolved marker outranks the repayment test, so
every case was pinned at "proceed with conditions" and a plain `proceed` was unreachable for any
use case ever run. The live run shows exactly that state.

The schema is what moves. `current_volume` is the published name — it pairs with
`expected_reduction` and says WHICH volume — and the domain, the corpus and the formula all
already use it; only the schema disagreed.
"""
import json
from pathlib import Path

from lab.core.usecase import benefit

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads(
    (ROOT / "src/lab/workloads/usecase/schemas/benefit_inputs.schema.json").read_text())
BASELINE = SCHEMA["properties"]["quality_baseline"]


def test_the_schema_asks_for_the_field_the_formula_reads():
    for field in benefit._QUALITY_FIELDS:
        assert field in BASELINE["properties"], f"{field} is required by the formula and unaskable"


def test_a_fully_supplied_baseline_is_quantified_rather_than_requiring_input():
    driver = benefit.quality_improvement(
        {"current_volume": 5000, "error_rate": 0.18, "expected_reduction": 0.6,
         "error_class": "operational", "source": "the incident log"},
        error_costs={"operational": 400.0})
    assert not driver.requires_input, driver.note
    assert driver.amount == 5000 * 0.18 * 0.6 * 400.0


def test_a_baseline_missing_a_number_still_requires_input_by_name():
    driver = benefit.quality_improvement(
        {"error_rate": 0.18, "expected_reduction": 0.6, "error_class": "operational"},
        error_costs={"operational": 400.0})
    assert driver.requires_input and "current_volume" in driver.note


def test_no_error_cost_registry_refuses_by_name_rather_than_assuming():
    driver = benefit.quality_improvement(
        {"current_volume": 10, "error_rate": 0.1, "expected_reduction": 0.5,
         "error_class": "operational"}, error_costs={})
    assert driver.requires_input and driver.amount == 0.0
