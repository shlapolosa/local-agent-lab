"""The modelling agent's output contract (ADR D4): built on the visio BA's element shape, with CITED
provenance in place of `{source, representation}`. It asks only for what the mapping reads: an
element's layer and aspect follow from its type, so asking for them would only add a way to fail.

Generated rather than written as a file, so the type enums are the engine's own (`_TYPES`,
`_REL_TYPES`, `ACCESS_TYPES`) and cannot drift from what the renderer accepts. The agent cites
sources by their short key (`S1`), never by ref; `mapping` turns the key back into the ref.
"""
from __future__ import annotations

from pathlib import Path

from lab.core.archimate.engine import _REL_TYPES, _TYPES, ACCESS_TYPES
from lab.core.modelling.provenance import LOCATION_KEYS

__all__ = ["prompt", "schema"]

_PROMPT = Path(__file__).with_name("prompts") / "model.md"


def prompt() -> str:
    """The modelling agent's instructions. The schema is appended by the caller, as for every step."""
    return _PROMPT.read_text(encoding="utf-8")


def schema() -> dict:
    cite = {
        "type": "object", "additionalProperties": False,
        "required": ["source", "location", "quote"],
        "properties": {
            "source": {"type": "string", "pattern": "^S[0-9]+$",
                       "description": "The key of the input this came from, as shown (S1, S2, ...)."},
            "location": {"type": "object", "additionalProperties": False, "minProperties": 1,
                         "properties": {k: {"type": ["integer", "string"]} for k in LOCATION_KEYS},
                         "description": "Where in that input: the [¶n] paragraph number, a page, "
                                        "a figure number or a diagram shape id."},
            "quote": {"type": "string", "minLength": 1,
                      "description": "The input's OWN words that justify this item, copied exactly. "
                                     "For a figure or diagram, the label or caption as read."},
        },
    }
    cites = {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/citation"}}
    element = {
        "type": "object", "additionalProperties": False,
        "required": ["name", "role", "type", "provenance"],
        "properties": {
            "name": {"type": "string", "minLength": 1,
                     "description": "The element's name, as the input names it. Unique across the "
                                    "model."},
            "role": {"type": "string", "minLength": 1,
                     "description": "What it is and does in this system, in plain language."},
            "type": {"enum": sorted(_TYPES), "description": "The exact ArchiMate 3.1 type. Its layer "
                                                            "and aspect follow from it."},
            "provenance": cites,
        },
    }
    relationship = {
        "type": "object", "additionalProperties": False,
        "required": ["source", "target", "type", "provenance"],
        "properties": {
            "source": {"type": "string", "minLength": 1, "description": "An element's `name`."},
            "target": {"type": "string", "minLength": 1, "description": "An element's `name`."},
            "type": {"enum": sorted(_REL_TYPES)},
            "accessType": {"enum": list(ACCESS_TYPES), "description": "Only for an Access relation."},
            "provenance": cites,
        },
    }
    question = {
        "type": "object", "additionalProperties": False, "required": ["text"],
        "properties": {"text": {"type": "string", "minLength": 1},
                       "elements": {"type": "array", "items": {"type": "string"},
                                    "description": "Names of the elements the question is about."}},
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Architecture model drawn from the inputs",
        "type": "object", "additionalProperties": False,
        "required": ["systemName", "summary", "elements", "relationships", "openQuestions"],
        "properties": {
            "systemName": {"type": "string", "minLength": 1},
            "summary": {"type": "string", "minLength": 1},
            "elements": {"type": "array", "items": {"$ref": "#/$defs/element"}},
            "relationships": {"type": "array", "items": {"$ref": "#/$defs/relationship"}},
            "openQuestions": {"type": "array", "items": {"$ref": "#/$defs/question"}},
        },
        "$defs": {"citation": cite, "element": element, "relationship": relationship,
                  "question": question},
    }
