"""The ArchiMate engine SPEC as a JSON Schema — the interchange between whoever proposes a model (the
lab's Architect agent, or a channel's own agent) and the engine that validates, lays out and renders it
(FR-11, user decision 24 Oct 2026). Committed as `contracts/archimate-spec.schema.json`.

GENERATED from the engine, never re-typed: the element types are `_TYPES` (the ArchiMate 3.1 taxonomy),
the relationship types `_REL_TYPES`, the access types `ACCESS_TYPES`. Strict (`additionalProperties:
false`): `from_spec` reads exactly these keys, so a key outside them is a mistake the producer should
hear about rather than a value silently dropped.

VERSION covers this schema AND the golden layout fixtures (`contracts/goldens/`): bump it by hand —
major for a breaking change to the spec shape or to the layout a port must reproduce, minor for an
additive change — so a channel porting the engine pins a version and re-validates when it moves.
Structural only: legality (which relationship may join which two types) is the semantic layer's
matrix, checked by `semantic_validate_model`, not expressible as a schema.
"""
from __future__ import annotations

import json

from lab.core.archimate.engine import _REL_TYPES, _TYPES, ACCESS_TYPES

__all__ = ["VERSION", "schema", "dumps"]

VERSION = "1.0.0"
_ID = {"type": "string", "minLength": 1}
_IDS = {"type": "array", "items": {"$ref": "#/$defs/id"}}


def schema() -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:lab:contracts:archimate-spec:{VERSION}",
        "title": "ArchiMate engine spec",
        "version": VERSION,
        "type": "object", "required": ["name"], "additionalProperties": False,
        "properties": {
            "name": {"type": "string", "description": "The model's name"},
            "id": {**_ID, "description": "The model id (default \"model\")"},
            "elements": {"type": "array", "items": {"$ref": "#/$defs/element"}},
            "relations": {"type": "array", "items": {"$ref": "#/$defs/relation"}},
            "views": {"type": "array", "items": {"$ref": "#/$defs/view"}},
            "standard_views": {"type": "boolean",
                               "description": "Add the engine's cross-layer view catalogue after the explicit views"},
        },
        "$defs": {
            "id": _ID,
            "element": {
                "type": "object", "required": ["id", "type", "name"], "additionalProperties": False,
                "properties": {
                    "id": {**_ID, "description": "Stable id; an EA-repository UUID is emitted as its native identifier"},
                    "type": {"enum": sorted(_TYPES), "description": "ArchiMate 3.1 element type"},
                    "name": {"type": "string"},
                    "doc": {"type": ["string", "null"]},
                    "folder": {"type": ["string", "null"], "description": "Domain folder (organisation: domain -> layer)"},
                },
            },
            "relation": {
                "type": "object", "required": ["type", "src", "tgt"], "additionalProperties": False,
                "properties": {
                    "id": {**_ID, "description": "Stable id, e.g. ids.rid: \"r-\" + md5(\"src|type|tgt\")[:10]"},
                    "type": {"enum": list(_REL_TYPES)},
                    "src": {"$ref": "#/$defs/id"},
                    "tgt": {"$ref": "#/$defs/id"},
                    "accessType": {"enum": list(ACCESS_TYPES), "description": "Access relationships only"},
                },
            },
            "view": {
                "type": "object", "required": ["id", "title"], "additionalProperties": False,
                "anyOf": [{"required": ["elements"]}, {"required": ["rows"]}],
                "properties": {
                    "id": {"$ref": "#/$defs/id"},
                    "title": {"type": "string"},
                    "elements": {**_IDS, "description": "Elements placed by layer band (aspect rows)"},
                    "rows": {"type": "array", "items": _IDS,
                             "description": "Explicit rows, each pinned to its rank (capability-map grids)"},
                    "containers": {"type": "array", "items": {
                        "type": "object", "required": ["id", "children"], "additionalProperties": False,
                        "properties": {"id": {"$ref": "#/$defs/id"}, "children": _IDS}},
                        "description": "Nesting: a container element and the children drawn inside it"},
                },
            },
        },
    }


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
