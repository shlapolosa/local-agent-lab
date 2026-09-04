"""BA "accumulator tools": the Business Analyst BUILDS its structured output through many SMALL,
validated, deterministic tool calls instead of emitting one giant JSON document.

Why (measured in this stack, see CLAUDE.md / workflow.py header): small-argument tool calls are
reliable, but a large nested object emitted in one shot — as a tool argument or as the final
message — is flaky, and `response_format` JSON-schema is NOT honoured by the upstream model. So
the model adds a handful of elements per call, gets a precise per-item accept/reject report,
corrects only what failed, and the document is assembled deterministically here — schema-valid
by construction. `finish()` validates the assembled document against
`schemas/ba_output.schema.json` (the same contract workflow.py gates on) and the coordinator
fetches it with `acc.result()`.

Everything here is pure and deterministic: no Redis, no LLM, no network. Enums are loaded from
the schema file at import so they cannot drift from the contract. The batch/finish skeleton is
`lab.workloads.accumulator.Accumulator` (Template Method); this module supplies only the BA's
vocabulary, per-item validation, assembly and gate.

Usage (the coordinator wires it; this module does not touch workflow.py/agents.py):

    acc = BAAccumulator()
    agent = make_agent("ba", instructions, credential, tools=make_tools(acc))
    ... run the agent; it calls set_system / add_elements / add_relationships / note_questions / finish
    doc = acc.result()          # the assembled ba_output document
    ok = acc.last_finish        # the last finish() report, if the model called it

Note: `agents.ba_tools(headers)` (the governed storage-MCP READ tools) is a different thing and
composes with these — pass both in `tools=[...]`.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

from lab.workloads.accumulator import MAX_BATCH, Accumulator, coerce_items, fmt, nonempty_str

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "schemas" / "ba_output.schema.json"
SCHEMA: dict = json.loads(SCHEMA_PATH.read_text())
_VALIDATOR = Draft7Validator(SCHEMA)

# ---- enums, loaded from the schema (never hardcoded) -------------------------------------------
_EL = SCHEMA["definitions"]["element"]["properties"]
_REL = SCHEMA["definitions"]["relationship"]["properties"]
_PROV_ONEOF = _EL["provenance"]["oneOf"]
_PROV_OBJ = next(s for s in _PROV_ONEOF if s.get("type") == "object")["properties"]

# element groups = the top-level array properties whose items are #/definitions/element
GROUPS: tuple[str, ...] = tuple(
    k for k, v in SCHEMA["properties"].items()
    if v.get("type") == "array" and v.get("items", {}).get("$ref") == "#/definitions/element")
LAYERS: tuple[str, ...] = tuple(_EL["layer"]["enum"])
ASPECTS: tuple[str, ...] = tuple(_EL["aspect"]["enum"])
RELATIONSHIP_TYPES: tuple[str, ...] = tuple(_REL["type"]["enum"])
PROVENANCE_REPRESENTATIONS: tuple[str, ...] = tuple(
    next(s for s in _PROV_ONEOF if s.get("type") == "string")["enum"])
PROVENANCE_SOURCES: tuple[str, ...] = tuple(_PROV_OBJ["source"]["enum"])
# Expanding the bare-string shorthand: which input kind a representation can only have come from.
# `document` is the general case; `requirements` is narrower and the model must say so explicitly.
SOURCE_OF_REPRESENTATION: dict[str, str] = {"structure": "diagram", "vision": "diagram",
                                            "document": "document"}

ELEMENT_REQUIRED: tuple[str, ...] = tuple(SCHEMA["definitions"]["element"]["required"])
ELEMENT_FIELDS: tuple[str, ...] = tuple(_EL.keys())            # everything the schema allows
RELATIONSHIP_FIELDS: tuple[str, ...] = tuple(_REL.keys())

ITEM_FIELDS: tuple[str, ...] = ("group",) + ELEMENT_FIELDS    # what add_elements accepts per item

_ELEMENT_VALIDATOR = Draft7Validator({"definitions": SCHEMA["definitions"], **SCHEMA["definitions"]["element"]})
_RELATIONSHIP_VALIDATOR = Draft7Validator({"definitions": SCHEMA["definitions"], **SCHEMA["definitions"]["relationship"]})


def normalise_provenance(p: Any) -> tuple[Any, list[str]]:
    """Accept the bare-string shorthand or the object; return (normalised, errors).

    THE one provenance normaliser: the accumulator calls it per item, and the json-mode gate in
    `workflow.py` calls it over the finished document, so both BA modes hand the Architect exactly
    one shape. A missing provenance is an error here — every element must say where it came from."""
    errs: list[str] = []
    if p is None:
        return None, ["provenance is required: a representation shorthand "
                      f"[{fmt(PROVENANCE_REPRESENTATIONS)}] or an object {{source, representation}}"]
    if isinstance(p, str):
        s = p.strip()
        if s not in PROVENANCE_REPRESENTATIONS:
            errs.append(f"provenance '{p}' is not one of [{fmt(PROVENANCE_REPRESENTATIONS)}] "
                        f"(or an object {{source, representation}})")
            return None, errs
        # the shorthand EXPANDS to the full object, so everything downstream sees ONE shape
        return {"source": SOURCE_OF_REPRESENTATION[s], "representation": s}, errs
    if isinstance(p, dict):
        out: dict = {}
        unknown = sorted(set(p) - set(_PROV_OBJ))
        if unknown:
            errs.append(f"provenance has unknown field(s) {unknown}; allowed: [{fmt(_PROV_OBJ)}]")
        if "source" in p:
            if p["source"] not in PROVENANCE_SOURCES:
                errs.append(f"provenance.source '{p['source']}' is not one of [{fmt(PROVENANCE_SOURCES)}]")
            else:
                out["source"] = p["source"]
        if "representation" in p:
            if p["representation"] not in PROVENANCE_REPRESENTATIONS:
                errs.append(f"provenance.representation '{p['representation']}' is not one of "
                            f"[{fmt(PROVENANCE_REPRESENTATIONS)}]")
            else:
                out["representation"] = p["representation"]
        for f in ("source", "representation"):
            if f not in p:
                errs.append(f"provenance.{f} is required")
        return (out if not errs else None), errs
    errs.append("provenance must be a string shorthand (representation) or an object {source, representation}")
    return None, errs


def _validate_element_item(item: Any) -> tuple[dict | None, str | None, list[str]]:
    """Validate one add_elements item. Returns (element_dict, group, errors); element is None on error."""
    errs: list[str] = []
    if not isinstance(item, dict):
        return None, None, [f"item must be an object with fields [{fmt(ITEM_FIELDS)}]"]

    unknown = sorted(set(item) - set(ITEM_FIELDS))
    if unknown:
        errs.append(f"unknown field(s) {unknown}; allowed: [{fmt(ITEM_FIELDS)}]")

    group = item.get("group")
    if group not in GROUPS:
        errs.append(f"group '{group}' is not one of [{fmt(GROUPS)}]")

    for f in ELEMENT_REQUIRED:
        if f in ("layer", "aspect", "provenance"):
            continue  # enum-/shape-checked below with a precise message
        if not nonempty_str(item.get(f)):
            errs.append(f"{f} is required (non-empty string)")

    if item.get("layer") not in LAYERS:
        errs.append(f"layer '{item.get('layer')}' is not one of [{fmt(LAYERS)}]")
    if item.get("aspect") not in ASPECTS:
        errs.append(f"aspect '{item.get('aspect')}' is not one of [{fmt(ASPECTS)}]")

    ids = item.get("sourceShapeIds")
    if ids is not None:
        if isinstance(ids, (str, int)):
            ids = [str(ids)]
        if not isinstance(ids, list):
            errs.append("sourceShapeIds must be a list of strings")
        else:
            ids = [str(i) for i in ids]

    prov, perrs = normalise_provenance(item.get("provenance"))
    errs.extend(perrs)

    if errs:
        return None, group if group in GROUPS else None, errs

    el: dict = {
        "name": item["name"].strip(),
        "role": item["role"].strip(),
        "layer": item["layer"],
        "aspect": item["aspect"],
        "candidateType": item["candidateType"].strip(),
    }
    if ids:
        el["sourceShapeIds"] = ids
    el["provenance"] = prov

    # backstop: the schema itself is the last word on shape
    schema_errs = [f"{'/'.join(map(str, e.path)) or '<element>'}: {e.message}"
                   for e in sorted(_ELEMENT_VALIDATOR.iter_errors(el), key=lambda e: list(e.path))]
    if schema_errs:
        return None, group, schema_errs
    return el, group, []


class BAAccumulator(Accumulator):
    """Deterministic state the BA fills through the tools. Elements are keyed by name (exact,
    whitespace-trimmed) and carry their group; a re-added name UPDATES the existing element
    (later fields win; sourceShapeIds are unioned), never a duplicate."""

    def reset(self) -> None:
        super().reset()
        self.system_name: str = ""
        self.summary: str = ""
        self.elements: dict[str, dict] = {}       # name -> {"group": g, "element": {...}}
        self.relationships: list[dict] = []
        self._rel_keys: set[tuple[str, str, str]] = set()
        self.open_questions: list[str] = []

    # ---- state mutation (returns plain dicts the model reads) ---------------------------------
    def set_system(self, system_name: str, summary: str) -> dict:
        errs = []
        if not nonempty_str(system_name):
            errs.append("systemName is required (non-empty string)")
        if not nonempty_str(summary):
            errs.append("summary is required (non-empty string)")
        if errs:
            return {"ok": False, "errors": errs}
        self.system_name, self.summary = system_name.strip(), summary.strip()
        return {"ok": True, "systemName": self.system_name, "summary": self.summary}

    def add_elements(self, items: Any) -> dict:
        lst, err = self._batch(items, "total_elements", len(self.elements))
        if err:
            return err
        added, updated, rejected = [], [], []
        for i, item in enumerate(lst):
            el, group, errs = _validate_element_item(item)
            if errs:
                nm = item.get("name") if isinstance(item, dict) else None
                rejected.append({"index": i, "name": nm, "errors": errs})
                continue
            name = el["name"]
            if name in self.elements:
                cur = self.elements[name]["element"]
                merged_ids = list(dict.fromkeys(cur.get("sourceShapeIds", []) + el.get("sourceShapeIds", [])))
                cur.update(el)                       # later fields win
                if merged_ids:
                    cur["sourceShapeIds"] = merged_ids
                self.elements[name]["group"] = group   # later group wins too (a reclassification)
                updated.append(name)
            else:
                self.elements[name] = {"group": group, "element": el}
                added.append(name)
        return {"added": added, "updated": updated, "rejected": rejected, "total_elements": len(self.elements)}

    def add_relationships(self, items: Any) -> dict:
        lst, err = self._batch(items, "total_relationships", len(self.relationships), middle="duplicates")
        if err:
            return err
        added, dups, rejected = [], [], []
        for i, item in enumerate(lst):
            errs: list[str] = []
            if not isinstance(item, dict):
                rejected.append({"index": i, "errors": [f"item must be an object with fields [{fmt(RELATIONSHIP_FIELDS)}]"]})
                continue
            unknown = sorted(set(item) - set(RELATIONSHIP_FIELDS))
            if unknown:
                errs.append(f"unknown field(s) {unknown}; allowed: [{fmt(RELATIONSHIP_FIELDS)}]")
            for f in ("from", "to", "intent"):
                if not nonempty_str(item.get(f)):
                    errs.append(f"{f} is required (non-empty string)")
            rtype = item.get("type")
            if rtype not in RELATIONSHIP_TYPES:
                errs.append(f"type '{rtype}' is not one of [{fmt(RELATIONSHIP_TYPES)}]")
            src = item.get("from").strip() if nonempty_str(item.get("from")) else None
            tgt = item.get("to").strip() if nonempty_str(item.get("to")) else None
            for end, nm in (("from", src), ("to", tgt)):
                if nm is not None and nm not in self.elements:
                    errs.append(f"{end} '{nm}' is not a declared element — add it with add_elements "
                                f"first (declared: {len(self.elements)} elements), then resend this relationship")
            if errs:
                rejected.append({"index": i, "from": item.get("from"), "to": item.get("to"),
                                 "type": rtype, "errors": errs})
                continue
            rel = {"from": src, "to": tgt, "type": rtype, "intent": item["intent"].strip()}
            schema_errs = [f"{'/'.join(map(str, e.path)) or '<relationship>'}: {e.message}"
                           for e in _RELATIONSHIP_VALIDATOR.iter_errors(rel)]
            if schema_errs:
                rejected.append({"index": i, "from": src, "to": tgt, "type": rtype, "errors": schema_errs})
                continue
            key = (src, tgt, rtype)
            if key in self._rel_keys:
                dups.append(key)
                continue
            self._rel_keys.add(key)
            self.relationships.append(rel)
            added.append(key)
        return {"added": [list(k) for k in added], "duplicates": [list(k) for k in dups],
                "rejected": rejected, "total_relationships": len(self.relationships)}

    def note_questions(self, items: Any) -> dict:
        lst = coerce_items(items)
        if isinstance(lst, str):
            return {"error": lst, "added": 0, "skipped": 0, "total_questions": len(self.open_questions)}
        added = skipped = 0
        for q in lst:
            if not nonempty_str(q):
                skipped += 1
                continue
            q = q.strip()
            if q in self.open_questions:
                skipped += 1
                continue
            self.open_questions.append(q)
            added += 1
        return {"added": added, "skipped": skipped, "total_questions": len(self.open_questions)}

    # ---- assembly ------------------------------------------------------------------------------
    def counts(self) -> dict:
        c = {g: 0 for g in GROUPS}
        for v in self.elements.values():
            c[v["group"]] += 1
        c["elements"] = len(self.elements)
        c["relationships"] = len(self.relationships)
        c["openQuestions"] = len(self.open_questions)
        return c

    def result(self) -> dict:
        """The assembled ba_output document (a deep copy; key order = the schema's required order)."""
        doc: dict = {"systemName": self.system_name, "summary": self.summary}
        for g in GROUPS:
            doc[g] = [copy.deepcopy(v["element"]) for v in self.elements.values() if v["group"] == g]
        doc["relationships"] = copy.deepcopy(self.relationships)
        doc["openQuestions"] = list(self.open_questions)
        return doc

    def _gate(self, doc: dict) -> tuple[list[str], str | None]:
        """Validate against the schema AND the workflow's completeness gate (`finish()` = the base
        skeleton: assemble, gate, never raise, stash `last_finish`)."""
        errors = [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}"
                  for e in sorted(_VALIDATOR.iter_errors(doc), key=lambda e: list(e.path))]
        # completeness beyond shape (mirrors workflow._incomplete so the gate can't disagree)
        if not doc["systemName"] or not doc["summary"]:
            errors.append("systemName/summary not set — call set_system(systemName, summary)")
        if not self.elements:
            errors.append("no elements described — call add_elements with the system's actors, "
                          "components, data and behaviors")
        dangling = [r for r in doc["relationships"]
                    if r["from"] not in self.elements or r["to"] not in self.elements]
        if dangling:  # cannot happen via the tools, but the gate is cheap and honest
            errors.append(f"{len(dangling)} relationship endpoint(s) reference undeclared elements")
        unrelated = [n for n in self.elements
                     if not any(r["from"] == n or r["to"] == n for r in self.relationships)]
        hint = None
        if unrelated and len(self.elements) > 1:
            hint = (f"{len(unrelated)} element(s) have no relationship: {unrelated[:8]}"
                    f"{' …' if len(unrelated) > 8 else ''} — connect them with "
                    "add_relationships or explain in note_questions if the diagram leaves them orphaned")
        return errors, hint


# ---- tool functions: closures over ONE accumulator; plain typed functions + docstrings the model sees
def make_tools(acc: BAAccumulator) -> list:
    """Return the BA's accumulator tools bound to `acc`, ready for `Agent(tools=[...])`."""

    def set_system(systemName: str, summary: str) -> dict:
        return acc.set_system(systemName, summary)
    set_system.__doc__ = (
        "Name the system the diagram depicts and summarise it in one or two plain-language "
        "sentences. Call this once, first (you may call it again to refine). "
        "Returns {ok, systemName, summary} or {ok: false, errors}.")

    def add_elements(items: list[dict]) -> dict:
        return acc.add_elements(items)
    add_elements.__doc__ = (
        f"Add up to {MAX_BATCH} elements of the system in one call (split larger sets across calls). "
        "Each item is a flat object: {group, name, role, layer, aspect, candidateType, provenance?, sourceShapeIds?}. "
        f"group is one of [{fmt(GROUPS)}]; name = the caption/identity read from the diagram; "
        "role = plain-language what it is and does; "
        f"layer is one of [{fmt(LAYERS)}]; aspect is one of [{fmt(ASPECTS)}]; "
        "candidateType = your best-guess exact ArchiMate 3.1 type name (e.g. ApplicationComponent, DataObject, BusinessActor); "
        f"provenance (optional) is either a string, one of [{fmt(PROVENANCE_REPRESENTATIONS)}], or an object "
        f"{{source: one of [{fmt(PROVENANCE_SOURCES)}], representation: one of [{fmt(PROVENANCE_REPRESENTATIONS)}]}}; "
        "sourceShapeIds (optional) = list of diagram shape ids the element was read from. "
        "Every item is validated on its own: valid items are ADDED, invalid ones are REJECTED with precise "
        "errors — fix and resend ONLY the rejected items. Re-adding an existing name UPDATES it (later "
        "fields win), so correct a mistake by resending the same name. "
        "Returns {added: [names], updated: [names], rejected: [{index, name, errors}], total_elements}.")

    def add_relationships(items: list[dict]) -> dict:
        return acc.add_relationships(items)
    add_relationships.__doc__ = (
        f"Add up to {MAX_BATCH} directed relationships between elements ALREADY added with add_elements. "
        "Each item is a flat object: {from, to, type, intent}. from/to are element names exactly as added; "
        f"type is one of [{fmt(RELATIONSHIP_TYPES)}]; intent = plain-language reading of the dependency "
        "(e.g. 'the gateway exposes the /v1 interface'). Direction matters: server->served, whole->part, "
        "realizer->realized, accessor->data, trigger->triggered. An item whose from/to is not a declared "
        "element is REJECTED — add that element first, then resend the relationship. Identical "
        "(from, to, type) triples are deduplicated. "
        "Returns {added: [[from,to,type]], duplicates, rejected: [{index, from, to, type, errors}], total_relationships}.")

    def note_questions(items: list[str]) -> dict:
        return acc.note_questions(items)
    note_questions.__doc__ = (
        "Record open questions: what the diagram does not settle (ambiguous shapes, missing types, "
        "caption/stencil contradictions, orphans, requirements that mention things the diagram does not show). "
        "Each item is one plain-language sentence. Duplicates are ignored. Returns {added, skipped, total_questions}.")

    def finish() -> dict:
        return acc.finish()
    finish.__doc__ = (
        "Call LAST, after all elements, relationships and questions are added. Assembles the complete "
        "system description and validates it against the output contract. Returns {ok: true, counts} "
        "when the description is complete and valid, or {ok: false, errors: [...]} telling you exactly "
        "what to fix (then fix it with the other tools and call finish again). A `hint` lists elements "
        "with no relationships. Your final reply after ok=true should be a short confirmation only — "
        "do NOT repeat the description as JSON.")

    return [set_system, add_elements, add_relationships, note_questions, finish]


__all__ = ["BAAccumulator", "make_tools", "SCHEMA", "SCHEMA_PATH", "GROUPS", "LAYERS", "ASPECTS",
           "RELATIONSHIP_TYPES", "PROVENANCE_REPRESENTATIONS", "PROVENANCE_SOURCES", "MAX_BATCH"]
