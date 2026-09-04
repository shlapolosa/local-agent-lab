"""Architect "accumulator tools": the Architect BUILDS the ArchiMate engine spec through many SMALL,
validated, deterministic tool calls instead of emitting one giant JSON spec.

Why (measured in this stack, see CLAUDE.md / workflow.py header and `ba_tools.py`): small-argument
tool calls are reliable, but the one-shot spec — a large nested object emitted as the final
message — took ~300 s and produced 16 ArchiMate-illegal relations that `relrepair` then had to
rewrite after the fact. Here every relation is checked against the ArchiMate 3.1 relationship
matrix AT THE MOMENT the model proposes it: an illegal one is REJECTED with the permitted list, so
the model picks a legal type itself and the defect never reaches the spec. Every element type is
checked against the engine's vocabulary with a "did you mean" hint. The spec is assembled
deterministically here — buildable by `adoit_mcp.server._build` by construction — and the
coordinator fetches it with `acc.result()` after `finish()`.

Reuse, not reimplementation:
  * element types   = `archimate_engine._TYPES` (the skill engine's own vocabulary; `Model.el`
                      raises on anything else, so we gate on the same dict);
  * relation types  = `archimate_engine._REL_TYPES`;
  * legality        = `relrepair.check(src_type, rtype, tgt_type) -> (ok, allowed)` — the SAME
                      decision `Model.validate_relations()` makes (SemanticService over Archi's
                      complete Appendix B matrix, coarse engine rules when the semantic layer is
                      not importable);
  * relation ids    = `lab.workloads.ids.rid` (`"r-" + md5("src|type|tgt")[:10]`) — the ONE home of the
                      formula, so ids match what the workflow assigns and stay stable across
                      re-runs/updates;
  * batch/finish    = `lab.workloads.accumulator.Accumulator` (Template Method): this module supplies
                      only the Architect's vocabulary, per-item validation, assembly and gate.

Everything here is pure and deterministic: no Redis, no LLM, no network.

Usage (the coordinator wires it; this module does not touch workflow.py/agents.py):

    acc = ArchitectAccumulator()
    agent = architect_agent(tools=make_tools(acc))
    ... run the agent; it calls set_model / add_elements / add_relations / add_view / finish
    spec = acc.result()         # the assembled engine spec ({name, id, elements, relations, views?})
    ok = acc.last_finish        # the last finish() report, if the model called it
"""
from __future__ import annotations

import copy
import difflib
import re
from typing import Any

from lab.core.archimate import relrepair  # (skill script: legality via the semantic matrix)
from lab.core.archimate.engine import _REL_TYPES, _TYPES, Model
from lab.workloads import ids
from lab.workloads.accumulator import MAX_BATCH, Accumulator, coerce_items, fmt, nonempty_str
from lab.core.canon import squash

# ---- vocabularies, taken from the engine (never hardcoded) --------------------------------------
ELEMENT_TYPES: tuple[str, ...] = tuple(_TYPES.keys())
RELATION_TYPES: tuple[str, ...] = tuple(r for r in _REL_TYPES if r != "Junction")
ACCESS_TYPES: tuple[str, ...] = ("Read", "Write", "ReadWrite", "Access")

ELEMENT_FIELDS: tuple[str, ...] = ("id", "type", "name", "doc", "folder")
RELATION_FIELDS: tuple[str, ...] = ("id", "type", "src", "tgt", "accessType")

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_ADOIT_ID = re.compile(rf"^\{{?{_UUID}\}}?$")


def suggest(value: str, vocab: tuple[str, ...], n: int = 3) -> list[str]:
    """Closest valid names for a wrong one: exact match ignoring case/spaces/underscores first
    ("application component" -> ApplicationComponent), then difflib similarity, then any valid
    name containing the given word ("Component" -> ApplicationComponent, …)."""
    if not isinstance(value, str) or not value.strip():
        return []
    nv = squash(value)
    exact = [t for t in vocab if squash(t) == nv]
    if exact:
        return exact
    close = difflib.get_close_matches(value, vocab, n=n, cutoff=0.6)
    if close:
        return close
    return [t for t in vocab if nv and (nv in squash(t) or squash(t) in nv)][:n]


def _type_error(kind: str, value: Any, vocab: tuple[str, ...]) -> str:
    hint = suggest(value, vocab) if isinstance(value, str) else []
    if hint:
        return (f"{kind} '{value}' is not a valid ArchiMate 3.1 {kind} — did you mean "
                f"{' or '.join(hint)}? (exact CamelCase name required)")
    return f"{kind} '{value}' is not a valid ArchiMate 3.1 {kind}; valid: [{fmt(vocab)}]"


def _valid_id(v: Any) -> str | None:
    """Ids are stable slugs or ADOIT object ids ({uuid} / bare uuid — reused VERBATIM for matched
    objects). Returns an error message, or None when acceptable."""
    if not nonempty_str(v):
        return "id is required (non-empty string: a stable slug of the name, or the ADOIT id verbatim)"
    s = v.strip()
    if re.search(r"\s", s):
        return f"id '{v}' must not contain whitespace — use a slug (lowercase, dashes) or the ADOIT id verbatim"
    if _ADOIT_ID.match(s):
        return None
    if any(ch in s for ch in "<>\"'&"):
        return f"id '{v}' contains characters not allowed in an XML id (<>\"'&)"
    return None


def _validate_element_item(item: Any) -> tuple[dict | None, list[str]]:
    """Validate one add_elements item. Returns (element_dict, errors); element is None on error."""
    errs: list[str] = []
    if not isinstance(item, dict):
        return None, [f"item must be an object with fields [{fmt(ELEMENT_FIELDS)}]"]
    unknown = sorted(set(item) - set(ELEMENT_FIELDS))
    if unknown:
        errs.append(f"unknown field(s) {unknown}; allowed: [{fmt(ELEMENT_FIELDS)}]")
    id_err = _valid_id(item.get("id"))
    if id_err:
        errs.append(id_err)
    atype = item.get("type")
    if atype not in _TYPES:
        errs.append(_type_error("type", atype, ELEMENT_TYPES))
    if not nonempty_str(item.get("name")):
        errs.append("name is required (non-empty string)")
    for opt in ("doc", "folder"):
        if opt in item and item[opt] is not None and not isinstance(item[opt], str):
            errs.append(f"{opt} must be a string")
    if errs:
        return None, errs
    el: dict = {"id": item["id"].strip(), "type": atype, "name": item["name"].strip()}
    if nonempty_str(item.get("doc")):
        el["doc"] = item["doc"].strip()
    if nonempty_str(item.get("folder")):
        el["folder"] = item["folder"].strip()
    return el, []


def check_relation(src_type: str, rtype: str, tgt_type: str) -> tuple[bool, list[str], str | None]:
    """The legality gate: relrepair.check (semantic matrix). Returns (ok, allowed, note); `note` is
    set only when the checker itself failed (then ok=True — the downstream validator still runs)."""
    try:
        ok, allowed = relrepair.check(src_type, rtype, tgt_type)
        return bool(ok), list(allowed), None
    except Exception as e:  # pragma: no cover — never raise into the model
        return True, [], f"legality check unavailable ({type(e).__name__}: {e}); accepted unchecked"


class ArchitectAccumulator(Accumulator):
    """Deterministic state the Architect fills through the tools. Elements are keyed by id; a
    re-added id UPDATES the existing element (later fields win), never a duplicate. Relations are
    deduplicated on (src, tgt, type) and admitted only if the ArchiMate matrix permits them."""

    def reset(self) -> None:
        super().reset()
        self.name: str = ""
        self.id: str = ""
        self.elements: dict[str, dict] = {}       # id -> {id, type, name, doc?, folder?}
        self.relations: list[dict] = []           # {id, type, src, tgt, accessType?}
        self._rel_keys: dict[tuple[str, str, str], str] = {}   # (src, tgt, type) -> rid
        self.views: dict[str, dict] = {}          # id -> {id, title, elements}

    # ---- state mutation (returns plain dicts the model reads) ---------------------------------
    def set_model(self, name: str, id: str = "") -> dict:
        if not nonempty_str(name):
            return {"ok": False, "errors": ["name is required (non-empty string: the systemName)"]}
        mid = id.strip() if nonempty_str(id) else (ids.slug(name) or "model")
        id_err = _valid_id(mid)
        if id_err:
            return {"ok": False, "errors": [id_err]}
        self.name, self.id = name.strip(), mid
        return {"ok": True, "name": self.name, "id": self.id}

    def add_elements(self, items: Any) -> dict:
        lst, err = self._batch(items, "total_elements", len(self.elements))
        if err:
            return err
        added, updated, rejected = [], [], []
        for i, item in enumerate(lst):
            el, errs = _validate_element_item(item)
            if errs:
                eid = item.get("id") if isinstance(item, dict) else None
                rejected.append({"index": i, "id": eid, "errors": errs})
                continue
            eid = el["id"]
            if eid in self.elements:
                self.elements[eid].update(el)        # later fields win; never a duplicate
                updated.append(eid)
            else:
                self.elements[eid] = el
                added.append(eid)
        return {"added": added, "updated": updated, "rejected": rejected, "total_elements": len(self.elements)}

    def add_relations(self, items: Any) -> dict:
        lst, err = self._batch(items, "total_relations", len(self.relations), middle="duplicates")
        if err:
            return err
        added, dups, rejected, notes = [], [], [], []
        for i, item in enumerate(lst):
            errs: list[str] = []
            if not isinstance(item, dict):
                rejected.append({"index": i, "errors": [f"item must be an object with fields [{fmt(RELATION_FIELDS)}]"]})
                continue
            unknown = sorted(set(item) - set(RELATION_FIELDS))
            if unknown:
                errs.append(f"unknown field(s) {unknown}; allowed: [{fmt(RELATION_FIELDS)}]")
            rtype = item.get("type")
            if rtype not in RELATION_TYPES:
                errs.append(_type_error("relation type", rtype, RELATION_TYPES))
            src = item.get("src").strip() if nonempty_str(item.get("src")) else None
            tgt = item.get("tgt").strip() if nonempty_str(item.get("tgt")) else None
            for end, eid in (("src", src), ("tgt", tgt)):
                if eid is None:
                    errs.append(f"{end} is required (an element id already added with add_elements)")
                elif eid not in self.elements:
                    near = suggest(eid, tuple(self.elements))
                    errs.append(f"{end} '{eid}' is not an added element id — add it with add_elements first "
                                f"(added: {len(self.elements)} elements"
                                f"{'; did you mean ' + ' or '.join(near) if near else ''}), then resend this relation")
            acc_t = item.get("accessType")
            if acc_t is not None:
                if acc_t not in ACCESS_TYPES:
                    errs.append(f"accessType '{acc_t}' is not one of [{fmt(ACCESS_TYPES)}]")
                elif rtype != "Access":
                    errs.append("accessType is only meaningful on an Access relation")
            rid = item.get("id")
            if rid is not None:
                id_err = _valid_id(rid)
                if id_err:
                    errs.append(id_err)
                elif rid.strip() in self.elements:
                    errs.append(f"relation id '{rid}' collides with an element id")
            if errs:
                rejected.append({"index": i, "src": item.get("src"), "tgt": item.get("tgt"), "type": rtype, "errors": errs})
                continue
            # ---- the legality gate: the ArchiMate matrix decides, at the moment of proposal
            st, tt = self.elements[src]["type"], self.elements[tgt]["type"]
            ok, allowed, note = check_relation(st, rtype, tt)
            if note:
                notes.append(note)
            if not ok:
                rejected.append({"index": i, "src": src, "tgt": tgt, "type": rtype,
                                 "errors": [f"{rtype} not permitted for {st} -> {tt}; allowed: [{fmt(allowed)}]"
                                            + (" — pick one of the allowed types that keeps the intent"
                                               " (weakest relation that is still true) and resend"
                                               if allowed else "")]})
                continue
            key = (src, tgt, rtype)
            if key in self._rel_keys:
                dups.append(key)
                continue
            rid = rid.strip() if rid else ids.rid(src, rtype, tgt)
            if any(r["id"] == rid for r in self.relations):
                rejected.append({"index": i, "src": src, "tgt": tgt, "type": rtype,
                                 "errors": [f"relation id '{rid}' is already used by another relation"]})
                continue
            rel = {"id": rid, "type": rtype, "src": src, "tgt": tgt}
            if acc_t:
                rel["accessType"] = acc_t
            self._rel_keys[key] = rid
            self.relations.append(rel)
            added.append(key)
        out = {"added": [list(k) for k in added], "duplicates": [list(k) for k in dups],
               "rejected": rejected, "total_relations": len(self.relations)}
        if notes:
            out["warnings"] = sorted(set(notes))
        return out

    def add_view(self, id: str, title: str, element_ids: Any) -> dict:
        errs: list[str] = []
        id_err = _valid_id(id)
        if id_err:
            errs.append(id_err)
        if not nonempty_str(title):
            errs.append("title is required (non-empty string)")
        lst = coerce_items(element_ids)
        if isinstance(lst, str):
            errs.append(lst.replace("items", "element_ids"))
            lst = []
        ids = [str(e).strip() for e in lst if isinstance(e, (str, int)) and str(e).strip()]
        ids = list(dict.fromkeys(ids))                       # dedupe, order preserved
        missing = [e for e in ids if e not in self.elements]
        if missing:
            errs.append(f"element_ids not added: {missing} — add them with add_elements first, then resend the view")
        if not ids and not errs:
            errs.append("element_ids must list at least one added element id")
        if errs:
            return {"ok": False, "id": id, "errors": errs, "total_views": len(self.views)}
        vid = id.strip()
        updated = vid in self.views
        self.views[vid] = {"id": vid, "title": title.strip(), "elements": ids}
        edges = sum(1 for r in self.relations if r["src"] in ids and r["tgt"] in ids)
        return {"ok": True, "id": vid, "updated": updated, "elements": len(ids), "relations_in_view": edges,
                "total_views": len(self.views)}

    # ---- assembly ------------------------------------------------------------------------------
    def counts(self) -> dict:
        return {"elements": len(self.elements), "relations": len(self.relations), "views": len(self.views)}

    def result(self) -> dict:
        """The assembled engine spec (a deep copy) — the shape `adoit_mcp.server._build` accepts."""
        spec: dict = {"name": self.name, "id": self.id,
                      "elements": copy.deepcopy(list(self.elements.values())),
                      "relations": copy.deepcopy(self.relations)}
        if self.views:
            spec["views"] = copy.deepcopy(list(self.views.values()))
        return spec

    def _probe_build(self, spec: dict) -> list[str]:
        """Build the spec exactly the way adoit_mcp.server._build does, so finish() proves it renders.
        Returns the engine's 'not permitted' findings (empty = legal)."""
        m = Model(spec["name"], spec.get("id", "model"))
        for e in spec.get("elements", []):
            m.el(e["id"], e["type"], e["name"], e.get("doc"), folder=e.get("folder"))
        for r in spec.get("relations", []):
            m.rel(r["type"], r["src"], r["tgt"], rid=r.get("id"), accessType=r.get("accessType"))
        for v in spec.get("views", []):
            vw = m.view(v["id"], v["title"])
            vw.place(*v["elements"])
            vw.auto_edges()
        return [w for w in m.validate_relations() if "not permitted" in w]

    def _gate(self, spec: dict) -> tuple[list[str], str | None]:
        """Validate the spec: name set, >=1 element, unique ids, valid types, no dangling endpoints,
        every relation legal (re-checked), views over existing ids, and a probe build through the
        engine (`finish()` = the base skeleton: assemble, gate, never raise, stash `last_finish`)."""
        errors: list[str] = []
        if not spec["name"]:
            errors.append("model name not set — call set_model(name) with the systemName")
        if not self.elements:
            errors.append("no elements added — call add_elements with one element per BA element "
                          "(actors, components, data, behaviors)")
        eids = [e["id"] for e in spec["elements"]]
        if len(eids) != len(set(eids)):  # cannot happen via the tools, but the gate is cheap and honest
            errors.append("duplicate element ids")
        bad_types = [f"{e['id']}:{e['type']}" for e in spec["elements"] if e["type"] not in _TYPES]
        if bad_types:
            errors.append(f"invalid element type(s): {bad_types}")
        dangling = [r["id"] for r in spec["relations"]
                    if r["src"] not in self.elements or r["tgt"] not in self.elements]
        if dangling:
            errors.append(f"relation(s) with undeclared endpoints: {dangling}")
        rids = [r["id"] for r in spec["relations"]]
        if len(rids) != len(set(rids)):
            errors.append("duplicate relation ids")
        for r in spec["relations"]:
            if r["id"] in dangling:
                continue
            st, tt = self.elements[r["src"]]["type"], self.elements[r["tgt"]]["type"]
            ok, allowed, _ = check_relation(st, r["type"], tt)
            if not ok:
                errors.append(f"{r['id']} ({r['src']}->{r['tgt']}): {r['type']} not permitted for "
                              f"{st} -> {tt}; allowed: [{fmt(allowed)}]")
        for v in spec.get("views", []):
            miss = [e for e in v["elements"] if e not in self.elements]
            if miss:
                errors.append(f"view '{v['id']}' references unknown element ids: {miss}")
        if not errors:
            try:
                illegal = self._probe_build(spec)
            except Exception as e:
                illegal = [f"engine build failed: {type(e).__name__}: {e}"]
            errors.extend(illegal)
        unrelated = [eid for eid in self.elements
                     if not any(r["src"] == eid or r["tgt"] == eid for r in self.relations)]
        hint = None
        if unrelated and len(self.elements) > 1:
            hint = (f"{len(unrelated)} element(s) have no relation: {unrelated[:8]}"
                    f"{' …' if len(unrelated) > 8 else ''} — connect them with add_relations "
                    "(the BA's relationships map one-to-one) or leave them if the BA left them orphaned")
        return errors, hint


# ---- tool functions: closures over ONE accumulator; plain typed functions + docstrings the model sees
def make_tools(acc: ArchitectAccumulator) -> list:
    """Return the Architect's accumulator tools bound to `acc`, ready for `Agent(tools=[...])`."""

    def set_model(name: str, id: str = "") -> dict:
        return acc.set_model(name, id)
    set_model.__doc__ = (
        "Name the ArchiMate model: name = the BA's systemName; id (optional) = its slug — derived "
        "from the name when omitted. Call this once, first (you may call it again to refine). "
        "Returns {ok, name, id} or {ok: false, errors}.")

    def add_elements(items: list[dict]) -> dict:
        return acc.add_elements(items)
    add_elements.__doc__ = (
        f"Add up to {MAX_BATCH} ArchiMate elements in one call (split larger sets across calls). "
        "Each item is a flat object: {id, type, name, doc?, folder?}. "
        "id = a stable slug of the name (lowercase, ASCII, dashes; e.g. 'litellm-proxy') — or, for an "
        "element that is the SAME as one in the EXISTING ARCHITECTURE block, that adoit_id VERBATIM so "
        "ADOIT updates it in place; type = the exact ArchiMate 3.1 CamelCase type (e.g. ApplicationComponent, "
        "ApplicationService, DataObject, BusinessActor, SystemSoftware); name = the element name; "
        "doc = the BA's role text (+ a note if you re-typed it); folder = the domain when one is stated. "
        "Every item is validated on its own: valid items are ADDED, invalid ones are REJECTED with precise "
        "errors (a wrong type comes back with a 'did you mean' hint) — fix and resend ONLY the rejected "
        "items. Re-adding an existing id UPDATES it (later fields win), so correct a mistake by resending "
        "the same id. Returns {added: [ids], updated: [ids], rejected: [{index, id, errors}], total_elements}.")

    def add_relations(items: list[dict]) -> dict:
        return acc.add_relations(items)
    add_relations.__doc__ = (
        f"Add up to {MAX_BATCH} directed ArchiMate relations between elements ALREADY added with add_elements. "
        "Each item is a flat object: {type, src, tgt, accessType?}. src/tgt are element ids exactly as added; "
        f"type is one of [{fmt(RELATION_TYPES)}]; accessType (Access only) is one of [{fmt(ACCESS_TYPES)}]. "
        "Direction matters: whole->part, realizer->realized, server->served, accessor->data, trigger->triggered. "
        "EVERY relation is checked against the ArchiMate 3.1 relationship matrix: one that is not permitted "
        "between the two element types is REJECTED with the list of allowed types — pick the allowed type that "
        "keeps the intent (the weakest relation that is still true: active structure REALIZES a service and is "
        "ASSIGNED to a function/process; technology REALIZES the application element it hosts; Access targets "
        "a passive object) and resend ONLY that item. A relation whose src/tgt is not an added id is REJECTED — "
        "add the element first. Identical (src, tgt, type) triples are deduplicated. Returns {added: [[src,tgt,type]], "
        "duplicates, rejected: [{index, src, tgt, type, errors}], total_relations}.")

    def add_view(id: str, title: str, element_ids: list[str]) -> dict:
        return acc.add_view(id, title, element_ids)
    add_view.__doc__ = (
        "Declare one diagram view: id = a slug, title = its caption, element_ids = the ids of the elements "
        "it shows (all must already be added; duplicates are ignored; relations among them are drawn "
        "automatically). Optional — the standard layer-mapping views are generated downstream regardless; "
        "add a view only for a meaningful subset (e.g. the system's context or a single domain). Re-using "
        "an id replaces that view. Returns {ok, id, elements, relations_in_view, total_views} or {ok: false, errors}.")

    def finish() -> dict:
        return acc.finish()
    finish.__doc__ = (
        "Call LAST, after all elements, relations and views are added. Assembles the engine spec and "
        "validates it (name set, at least one element, every type valid, every relation legal, no dangling "
        "endpoints, views over added ids, and a trial build through the modelling engine). Returns {ok: true, "
        "counts} when the spec is complete and valid, or {ok: false, errors: [...]} telling you exactly what "
        "to fix (then fix it with the other tools and call finish again). A `hint` lists elements with no "
        "relation. Your final reply after ok=true should be a short confirmation only — do NOT repeat the "
        "spec as JSON.")

    return [set_model, add_elements, add_relations, add_view, finish]


__all__ = ["ArchitectAccumulator", "make_tools", "check_relation", "suggest",
           "ELEMENT_TYPES", "RELATION_TYPES", "ACCESS_TYPES", "MAX_BATCH"]
