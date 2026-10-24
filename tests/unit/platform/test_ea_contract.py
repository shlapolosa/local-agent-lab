"""The VISUALISATION capability's result schemas (FR-19) — declared once, from typed definitions.

What is pinned: each schema is a self-contained JSON Schema object (no `$ref`, no titles); the approval
payload's import artifacts mirror `ImportArtifact` field for field (so the typed dataclass and the
published schema cannot drift); known payloads validate and broken ones are refused; additive fields are
allowed (an adapter MAY add facts to a summary — a caller must never require them).
"""
import dataclasses

import jsonschema
import pytest

from lab.platform import ea_contract
from lab.platform.contracts import EATools, ImportArtifact

ART = {"ref": "art://a1/m.archimate.xml", "label": "Download .archimate.xml", "note": "", "media_type": ""}
PAYLOAD = {"xml_ref": "art://a1/m.archimate.xml", "svg_refs": {"full": "art://a2/m-full.svg"},
           "summary": {"elements": 5, "import_objects": 5}, "import_artifacts": [ART],
           "instructions": "import both"}


def _no_refs(node):
    if isinstance(node, dict):
        assert "$ref" not in node and "title" not in node
        for k, v in node.items():
            if k != "properties":
                _no_refs(v)
            else:
                for sub in v.values():
                    _no_refs(sub)
    elif isinstance(node, list):
        for v in node:
            _no_refs(v)


def test_every_result_schema_is_a_self_contained_object_schema():
    schemas = ea_contract.result_schemas()
    assert {EATools.render, EATools.stage_import, EATools.import_status} <= set(schemas)
    for name, schema in {**schemas, "approval": ea_contract.approval_schema()}.items():
        assert schema["type"] == "object", name
        _no_refs(schema)
        jsonschema.Draft202012Validator.check_schema(schema)


def test_the_published_import_artifact_mirrors_the_typed_dataclass():
    props = ea_contract.approval_schema()["properties"]["import_artifacts"]["items"]["properties"]
    assert set(props) == {f.name for f in dataclasses.fields(ImportArtifact)}


def test_a_known_payload_validates_and_extra_summary_facts_are_allowed():
    jsonschema.validate({**PAYLOAD, "summary": {**PAYLOAD["summary"], "render_violations": 0,
                                                "anything_an_adapter_adds": "x"}},
                        ea_contract.approval_schema())


@pytest.mark.parametrize("broken", [
    {k: v for k, v in PAYLOAD.items() if k != "xml_ref"},                     # the views XML is required
    {**PAYLOAD, "import_artifacts": [{"ref": "art://x/y"}]},                   # an artifact needs a label
    {**PAYLOAD, "svg_refs": {"full": 3}},                                       # refs are strings
])
def test_a_broken_payload_is_refused(broken):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(broken, ea_contract.approval_schema())


def test_the_render_result_states_its_canvas_as_width_and_height():
    view = ea_contract.result_schemas()[EATools.render]["properties"]["views"]["additionalProperties"]
    assert view["minItems"] == 2 and view["maxItems"] == 2


def test_the_schemas_are_deterministic():
    assert ea_contract.result_schemas() == ea_contract.result_schemas()
    assert ea_contract.approval_schema() == ea_contract.approval_schema()
