"""The ArchiMate engine spec as a JSON Schema — the interchange a channel's own agent emits (FR-11).

What is pinned: the enums are the ENGINE's (generated from `_TYPES`, `_REL_TYPES`, `ACCESS_TYPES`, never
re-typed), every real producer's spec validates — the lab architecture model, a SKOS capability-map export
(rows + containers) and the visio Architect's shape — and a spec the engine would refuse is refused here
too, so a channel validating against the schema is told what the renderer would have said.
"""
import json
import os

import jsonschema
import pytest

from fixtures.skos import scheme
from lab.core.archimate import engine, spec_schema

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
SPECS = os.path.join(ROOT, "contracts", "goldens", "specs")


def _validate(spec):
    jsonschema.Draft202012Validator(spec_schema.schema()).validate(spec)


def test_the_type_enums_are_the_engine_s_own():
    s = spec_schema.schema()
    el = s["$defs"]["element"]["properties"]["type"]["enum"]
    rel = s["$defs"]["relation"]["properties"]["type"]["enum"]
    assert set(el) == set(engine._TYPES) and set(rel) == set(engine._REL_TYPES)
    assert s["$defs"]["relation"]["properties"]["accessType"]["enum"] == list(engine.ACCESS_TYPES)
    assert s["version"] == spec_schema.VERSION


def test_the_schema_is_itself_valid_and_deterministic():
    jsonschema.Draft202012Validator.check_schema(spec_schema.schema())
    assert spec_schema.dumps(spec_schema.schema()) == spec_schema.dumps(spec_schema.schema())


def test_a_capability_map_export_validates_and_builds():
    spec = scheme().to_archimate_spec()
    _validate(spec)
    engine.from_spec(spec)


@pytest.mark.parametrize("name", sorted(f for f in os.listdir(SPECS) if f.endswith(".json")) if os.path.isdir(SPECS) else [])
def test_every_golden_spec_validates_and_builds(name):
    spec = json.load(open(os.path.join(SPECS, name), encoding="utf-8"))
    _validate(spec)
    engine.from_spec(spec)


def test_the_visio_architect_shape_validates():
    spec = {"name": "eRx", "elements": [
        {"id": "portal", "type": "ApplicationComponent", "name": "Portal", "doc": "front end", "folder": "Pharmacy"},
        {"id": "rx", "type": "DataObject", "name": "Prescription"}],
        "relations": [{"id": "r-0123456789", "type": "Access", "src": "portal", "tgt": "rx", "accessType": "Write"}],
        "standard_views": True}
    _validate(spec)


@pytest.mark.parametrize("bad, why", [
    ({"elements": []}, "name"),
    ({"name": "x", "elements": [{"id": "a", "type": "NotAType", "name": "A"}]}, "NotAType"),
    ({"name": "x", "relations": [{"type": "Flowing", "src": "a", "tgt": "b"}]}, "Flowing"),
    ({"name": "x", "relations": [{"type": "Access", "src": "a", "tgt": "b", "accessType": "Delete"}]}, "Delete"),
    ({"name": "x", "views": [{"id": "v", "title": "V"}]}, "elements"),
    ({"name": "x", "extra": 1}, "extra"),
])
def test_a_spec_the_engine_would_refuse_is_refused(bad, why):
    with pytest.raises(jsonschema.ValidationError) as e:
        _validate(bad)
    assert why in str(e.value)
