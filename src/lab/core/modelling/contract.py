"""`contracts/modelling.json`, GENERATED from the modelling domain (ADR 2026-10-24, D9).

What the envelope builder keeps and what a channel vendors are one declaration: every enum, required
list, field shape and id prefix below is read from `envelope`, `provenance` and `ids`, never retyped.
Render with `PYTHONPATH=src .venv/bin/python scripts/render_modelling_contract.py`; a governance test
holds the committed file to this function byte for byte.
"""
from __future__ import annotations

import json

from lab.core.archimate import ids
from lab.core.modelling import envelope as E
from lab.core.modelling.provenance import LOCATION_KEYS

__all__ = ["SPEC_ID", "dumps", "schema"]

#: The FR-11 engine spec schema this envelope carries unchanged (contracts/archimate-spec.schema.json).
SPEC_ID = "urn:lab:contracts:archimate-spec:1.0.0"
_ID = {"type": "string", "pattern": f"^{E.ID_PATTERN.pattern}$"}


def _ref_def(rk: E.RefKind) -> dict:
    shared = {E.STATUSES: {"$ref": "#/$defs/status"}, E.CHANGES: {"$ref": "#/$defs/change"}}
    props = {}
    for f in rk.fields:
        if f.kind == "status":
            shape = dict(shared.get(rk.statuses) or {"enum": list(rk.statuses)})
        elif f.kind == "level":
            shape = {"type": ["integer", "string"]}
        elif f.kind == "list":
            shape = {"type": "array", "items": {"type": "object"}}
        else:
            shape = {"type": "string"}
        if f.kind == "string" and f.name in rk.required and f.name != "element_id":
            shape["minLength"] = 1
        if f.description:
            shape["description"] = f.description
        props[f.name] = shape
    return {"type": "object", "additionalProperties": False, "description": rk.description,
            "required": list(rk.required), "properties": props}


def _prefixes() -> dict:
    table = {prefix: atype for atype, prefix in ids.PREFIXES.items()}
    table.update(ids.ROLE_PREFIXES)
    table[ids.ROOT_ID] = "Grouping, the use-case model root"
    return dict(sorted(table.items()))


def schema() -> dict:
    v = E.CONTRACT_VERSION
    by_id = {"type": "object", "propertyNames": {"pattern": _ID["pattern"]}}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:lab:contracts:modelling:{v}",
        "version": v,
        "title": "Architecture modelling envelope",
        "description": (
            "What modelling emits: the FR-11 engine spec UNCHANGED under `spec`, with provenance, "
            "sources, references, change status, renames, reviews, open questions and refused "
            "relations beside it (ADR docs/decisions/2026-10-24-architecture-modelling.md). Generated "
            "from lab.core.modelling; never edit by hand."),
        "x-stability": {k: "draft" for k in ("envelope", "provenance", "references", "changes",
                                             "reviews", "open_question")},
        "x-id-rule": (
            f"Every element and relation id matches {E.ID_PATTERN.pattern} (an IRI local name). An "
            "element id is a prefix for its type plus a slug of its name, so a re-run that keeps the "
            "name keeps the id. The prefix is x-id-prefixes' for the type, otherwise the type's own "
            "name in kebab case (SystemSoftware -> 'system-software-'). A name with nothing to slug "
            "(e.g. wholly Arabic) gets 'h' plus a hash of the name. A rename is a new id, declared in "
            "`renamed_from` when modelling can show it is the same thing. A relation id is 'r-' + "
            "md5(src|type|tgt)[:10]."),
        "x-id-prefixes": _prefixes(),
        "type": "object", "additionalProperties": False,
        "required": ["contract_version", "spec", "sources", "provenance", "references", "changes",
                     "renamed_from", "reviews", "open_questions", "dropped", "gaps"],
        "properties": {
            "contract_version": {"const": v},
            "spec": {"$ref": SPEC_ID},
            "sources": {"type": "array", "items": {"$ref": "#/$defs/source"}},
            "provenance": {"type": "object", "additionalProperties": False,
                           "required": ["elements", "relations"],
                           "properties": {g: {"$ref": "#/$defs/provenance_by_id"}
                                          for g in ("elements", "relations")}},
            "references": {"type": "object", "additionalProperties": False,
                           "required": list(E.REFERENCE_KINDS),
                           "description": "What each model element is in other registers.",
                           "properties": {k: {"type": "array", "items": {"$ref": f"#/$defs/ref_{k}"}}
                                          for k in E.REFERENCE_KINDS}},
            "changes": by_id | {
                "description": "Per element, its change relative to the EA repository, for impact "
                               "views (as-is = consumed, updated, removed; to-be = consumed, updated, "
                               "new). The lab's visualisation does not read it yet.",
                "additionalProperties": {"$ref": "#/$defs/change"}},
            "renamed_from": by_id | {
                "description": "Element id -> the ids it had in earlier runs, declared only on "
                               "evidence (same provenance location or the same repository id).",
                "additionalProperties": {"type": "array", "items": {"type": "string"}}},
            "reviews": {"type": "array", "items": {"$ref": "#/$defs/review_decision"},
                        "description": "Architect decisions at the modelling gate, carried across "
                                       "re-runs: kept on an id that still exists, moved across a "
                                       "rename (an element's, or a relation endpoint's), and raised "
                                       "as `review-orphaned` when the id is gone."},
            "open_questions": {"type": "array", "items": {"$ref": "#/$defs/open_question"}},
            "dropped": {"type": "array", "items": {"type": "object"},
                        "description": "Relations proposed but refused (illegal by the matrix, an "
                                       "undeclared or ambiguous endpoint), each with its reason."},
            "gaps": {"type": "array", "items": {"type": "object"},
                     "description": "Joins a mapper could not make."},
        },
        "$defs": {
            "change": {"enum": list(E.CHANGES),
                       "description": "new = to be built; updated = existing, changed by this "
                                      "solution; consumed = existing, used as is; removed = "
                                      "existing, retired by an input (never inferred from absence)."},
            "status": {"enum": list(E.STATUSES),
                       "description": "The change vocabulary plus missing = needed, and nothing "
                                      "realises it."},
            "source": {"type": "object", "additionalProperties": False,
                       "required": ["ref", "name", "media_type", "aliases"],
                       "properties": {
                           "ref": {"type": "string", "minLength": 1,
                                   "description": "Opaque key provenance.source_ref points at."},
                           "name": {"type": "string"}, "media_type": {"type": "string"},
                           "aliases": {"type": "array", "items": {"type": "string"},
                                       "description": "Other names for the same artifact."}}},
            "location": {"type": "object", "additionalProperties": False, "minProperties": 1,
                         "properties": {k: {"type": ["integer", "string"]} for k in LOCATION_KEYS}},
            "provenance": {"type": "object", "additionalProperties": False,
                           "required": ["source_ref", "location", "quote"],
                           "properties": {
                               "source_ref": {"type": "string", "minLength": 1},
                               "location": {"$ref": "#/$defs/location"},
                               "quote": {"type": "string", "minLength": 1,
                                         "description": "Verbatim words from the source, checked "
                                                        "against the cited paragraph."}}},
            "provenance_by_id": {"type": "object", "additionalProperties": {
                "type": "array", "items": {"$ref": "#/$defs/provenance"}}},
            **{f"ref_{k}": _ref_def(rk) for k, rk in E.REFERENCE_KINDS.items()},
            "open_question": {
                "type": "object", "additionalProperties": False,
                "required": ["id", "kind", "text", "refs"],
                "properties": {
                    "id": {"type": "string", "pattern": "^oq-[0-9a-f]{10}$",
                           "description": "Stable across rebuilds of the same content."},
                    "kind": {"enum": list(E.QUESTION_KINDS)},
                    "text": {"type": "string"},
                    "refs": {"type": "object", "additionalProperties": False,
                             "required": ["elements", "relations"],
                             "properties": {g: {"type": "array", "items": {"type": "string"}}
                                            for g in ("elements", "relations")}},
                    "provenance": {"type": "object",
                                   "description": "The entry the question is about, when there is one."}}},
            "review_decision": {
                "description": "One architect decision at the modelling gate (D8), per element or "
                               "relation.",
                "type": "object", "additionalProperties": False,
                "required": ["item_kind", "item_id", "state", "actor"],
                "properties": {
                    "item_kind": {"enum": ["element", "relation"]},
                    "item_id": {"type": "string", "minLength": 1},
                    "state": {"enum": list(E.REVIEW_STATES)},
                    "actor": {"type": "string", "minLength": 1, "pattern": "\\S",
                              "description": "The signed-in human. Blank is refused."},
                    "note": {"type": "string"},
                    "correction": {"type": "object",
                                   "description": "With state=corrected: the fields that change."}}},
        },
    }


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
