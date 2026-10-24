"""The modelling envelope (ADR 2026-10-24): the FR-11 spec UNCHANGED, with what it cannot carry
beside it.

`contracts/archimate-spec.schema.json` refuses any key it does not declare, so the run's working model
(`props`, `dropped`, `gaps`) cannot travel as the spec. The envelope splits the two:
- `spec` is exactly what visualisation consumes;
- beside it sit provenance, sources, map/repository/vocabulary references, per-element change status,
  renames, architect reviews, open questions, dropped relations and gaps.

`contracts/modelling.json` is GENERATED from this module (`lab.core.modelling.contract`), so what the
builder keeps and what the contract publishes are one declaration.

The builder runs on agent output inside a long workflow, so bad input is REPORTED as an open question
and never raised, and whatever it returns validates against the contract.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from lab.core.archimate.ids import rid
from lab.core.modelling.provenance import Provenance, Source, check

__all__ = ["CHANGES", "CONCEPT_STATUSES", "CONTRACT_VERSION", "ELEMENT_KEYS", "ID_PATTERN",
           "QUESTION_KINDS", "REFERENCE_KINDS", "RELATION_KEYS", "REVIEW_KEYS", "REVIEW_STATES",
           "RefField", "RefKind", "SPEC_KEYS", "STATUSES", "build"]

CONTRACT_VERSION = "1.2.0"

#: The keys the FR-11 schema declares (v1.0.0). Parity with the schema is a governance test.
SPEC_KEYS = ("name", "id", "elements", "relations", "views", "standard_views")
ELEMENT_KEYS = ("id", "type", "name", "doc", "folder")
RELATION_KEYS = ("id", "type", "src", "tgt", "accessType")

#: Element and relation ids are IRI local names, so a consumer can mint an IRI from one unchanged.
ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")

#: ONE change vocabulary for every impact colour (D19), in the CAFÉ heatmaps' own words:
#: new = to be built; updated = existing, changed by this solution; consumed = existing, used as is;
#: removed = existing, retired by an input (never inferred from absence).
#: This is the vocabulary's ONE home. Visualisation draws only the standard views for now (user, 24 Oct)
#: and does not read `changes` yet; SAF's impact path does.
CHANGES = ("new", "updated", "consumed", "removed")
#: A capability can also be `missing`: needed, and nothing in the model realises it.
STATUSES = CHANGES + ("missing",)
CONCEPT_STATUSES = ("linked", "candidate")

REVIEW_STATES = ("accepted", "corrected", "rejected")
REVIEW_KEYS = ("item_kind", "item_id", "state", "actor", "note", "correction")

QUESTION_KINDS = ("raised", "no-provenance", "malformed-provenance", "orphan-provenance",
                  "unknown-source", "quote-not-found", "location-mismatch", "unverifiable",
                  "orphan-reference", "malformed-reference",
                  "review-orphaned", "malformed-review", "invalid-id", "name-collision")

_GROUPS = ("elements", "relations")
#: The question kinds a CALLER may raise (the agent's own, and the mapping's merge of two names);
#: every other kind is the builder's own finding and cannot be claimed from outside.
_CALLER_KINDS = ("raised", "name-collision")


@dataclass(frozen=True)
class RefField:
    """One field of a reference. `kind` is its JSON shape: "string" (a number is coerced to its text),
    "level" (an integer or a string), "list" (an array of objects), or "status" (the kind's vocabulary)."""
    name: str
    description: str = ""
    kind: str = "string"


@dataclass(frozen=True)
class RefKind:
    """One kind of reference. Adding a kind is one entry in REFERENCE_KINDS; the builder and the
    published contract both follow it."""
    description: str
    fields: tuple[RefField, ...]
    required: tuple[str, ...]
    statuses: tuple[str, ...]
    element_optional_when: str = ""    # a status under which no element is needed

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)

    @property
    def status_field(self) -> str:
        return next(f.name for f in self.fields if f.kind == "status")


_EL = RefField("element_id", "The model element this reference is about.")
_CONF = RefField("confidence", "How sure the match is, in the matcher's own words.")

REFERENCE_KINDS: Mapping[str, RefKind] = {
    "capabilities": RefKind(
        "Capability-map matches: which capability each element touches.",
        (RefField("element_id", "The model element this is about. Empty only when status=missing."),
         RefField("map", "The capability map's artifact id in the reference corpus."),
         RefField("map_version", "The pinned version the match was made against."),
         RefField("capability_id", "The map's own id, e.g. KNW.11 (technology) or B1.1.2 (business)."),
         RefField("label"), RefField("level", kind="level"), RefField("status", kind="status"), _CONF),
        ("element_id", "map", "capability_id", "status"), STATUSES, element_optional_when="missing"),
    "realisations": RefKind(
        "Realisation-map entries: what realises each matched capability.",
        (_EL, RefField("capability_id"),
         RefField("realised_by", "What realises the capability: a product, platform or existing system."),
         RefField("catalogue_id", "The reference-architecture catalogue id (cmp-...) when the realiser "
                                  "is a catalogue component."),
         RefField("status", kind="status"), _CONF),
        ("element_id", "capability_id", "realised_by", "status"), STATUSES),
    "repository": RefKind(
        "The element resolved against the EA repository (through the EA port's ea_search). Drives "
        "create-vs-update at import and the impact view.",
        (_EL, RefField("repository_id", "Absent when match=new."),
         RefField("repository_class", "The repository's own class name for the object."),
         RefField("match", kind="status"), _CONF,
         RefField("candidates", "The other repository objects considered, for the architect to pick from.",
                  kind="list")),
        ("element_id", "match"), CHANGES),
    "concepts": RefKind(
        "The element linked to a fabric vocabulary concept.",
        (_EL, RefField("concept_iri", "Absent for a candidate the vocabulary does not hold yet."),
         RefField("label"), RefField("scheme"), RefField("status", kind="status"), _CONF),
        ("element_id", "label", "status"), CONCEPT_STATUSES),
}


def _only(d: Mapping[str, Any], keys: Iterable[str]) -> dict:
    return {k: d[k] for k in keys if k in d}


def _spec(working: Mapping[str, Any]) -> dict:
    out = _only(working, SPEC_KEYS)
    out["elements"] = [_only(e, ELEMENT_KEYS) for e in working.get("elements") or []]
    out["relations"] = [_only(r, RELATION_KEYS) for r in working.get("relations") or []]
    return out


def _refs(refs: Any) -> dict:
    refs = refs if isinstance(refs, Mapping) else {}
    return {g: [str(x) for x in refs.get(g) or []] for g in _GROUPS}


def _question(kind: str, text: str, refs: Any = None, about: Any = None) -> dict:
    """The id hashes everything the question says, so two different questions never share one and a
    rebuild of the same content keeps it."""
    r = _refs(refs)
    key = json.dumps([kind, text, r, about], sort_keys=True, default=str)
    q = {"id": "oq-" + hashlib.md5(key.encode()).hexdigest()[:10], "kind": kind, "text": text,
         "refs": r}
    if isinstance(about, Mapping):
        q["provenance"] = dict(about)
    return q


def _coerce(raw: Mapping[str, Any], rk: RefKind) -> dict | None:
    """The reference in the contract's shapes, or None when a field cannot be expressed in them."""
    out = {}
    for f in rk.fields:
        if f.name not in raw or raw[f.name] is None:
            continue
        v = raw[f.name]
        if f.kind == "list":
            if not isinstance(v, list) or not all(isinstance(x, Mapping) for x in v):
                return None
            out[f.name] = [dict(x) for x in v]
        elif f.kind == "level" and isinstance(v, int) and not isinstance(v, bool):
            out[f.name] = v
        elif isinstance(v, (str, int, float)) and not isinstance(v, bool):
            out[f.name] = str(v)
        else:
            return None
    return out


class _Builder:
    """One envelope build: the clean spec, what is known in it, and the questions raised so far."""

    def __init__(self, spec: Mapping[str, Any], sources: Sequence[Source]):
        self.spec = _spec(spec)
        self.sources = {s.ref: s for s in sources}
        self.known = {g: {str(x.get("id")) for x in self.spec[g]} for g in _GROUPS}
        self.valid = {g: {i for i in self.known[g] if ID_PATTERN.fullmatch(i)} for g in _GROUPS}
        self.questions: list[dict] = []

    def ask(self, *args, **kw) -> None:
        q = _question(*args, **kw)
        if all(q["id"] != o["id"] for o in self.questions):
            self.questions.append(q)

    def element(self, eid: str, what: str, raw: Any = None, *, allow_blank: bool = False) -> bool:
        """Is `eid` an element this envelope may key on? Otherwise ask, once, and say no."""
        if eid in self.valid["elements"] or (allow_blank and eid == ""):
            return True
        self.ask("orphan-reference", f"{what} names element {eid or '?'}, which the model does not "
                                     f"have (or whose id is not valid)",
                 {"elements": [eid] if eid else []}, raw)
        return False

    def ids(self) -> None:
        for group in _GROUPS:
            for item_id in sorted(self.known[group] - self.valid[group]):
                self.ask("invalid-id", f"{group[:-1]} id {item_id!r} is not an IRI local name "
                                       f"([A-Za-z0-9_-])", {group: [item_id]})

    def provenance(self, provenance: Any) -> dict:
        kept: dict[str, dict[str, list]] = {g: {} for g in _GROUPS}
        provenance = provenance if isinstance(provenance, Mapping) else {}
        for group in _GROUPS:
            for item_id, entries in (provenance.get(group) or {}).items():
                refs = {group: [item_id]}
                if item_id not in self.valid[group]:
                    self.ask("orphan-provenance", f"provenance names {group[:-1]} {item_id}, which "
                                                  f"the model does not have", refs)
                    continue
                for raw in entries or []:
                    try:
                        p = Provenance.from_dict(raw)
                    except ValueError as e:
                        self.ask("malformed-provenance", str(e), refs,
                                 raw if isinstance(raw, Mapping) else None)
                        continue
                    kept[group].setdefault(item_id, []).append(p.to_dict())
                    kind = check(p, self.sources)
                    if kind:
                        self.ask(kind, f"{kind} for {group[:-1]} {item_id}", refs, p.to_dict())
            for item_id in sorted(self.valid[group] - set(kept[group])):
                self.ask("no-provenance", f"{group[:-1]} {item_id} cites no input", {group: [item_id]})
        return kept

    def references(self, refs: Any) -> dict:
        kept: dict[str, list[dict]] = {kind: [] for kind in REFERENCE_KINDS}
        refs = refs if isinstance(refs, Mapping) else {}
        for kind, rk in REFERENCE_KINDS.items():
            for raw in refs.get(kind) or []:
                ref = _coerce(raw, rk) if isinstance(raw, Mapping) else None
                eid = str((ref or {}).get("element_id") or "")
                missing = [f for f in rk.required
                           if f != "element_id" and not str((ref or {}).get(f) or "").strip()]
                if ref is None or missing or ref.get(rk.status_field) not in rk.statuses:
                    self.ask("malformed-reference",
                             f"{kind} reference needs {', '.join(rk.required)} in the contract's "
                             f"shapes, with {rk.status_field} in {rk.statuses}",
                             {"elements": [eid] if eid else []},
                             raw if isinstance(raw, Mapping) else None)
                    continue
                if self.element(eid, f"{kind} reference", raw,
                                allow_blank=ref[rk.status_field] == rk.element_optional_when):
                    kept[kind].append(ref | {"element_id": eid})
        return kept

    def changes(self, changes: Any) -> dict:
        kept = {}
        for eid, status in (changes if isinstance(changes, Mapping) else {}).items():
            if status not in CHANGES:
                self.ask("malformed-reference", f"change for {eid} must be one of {CHANGES}",
                         {"elements": [str(eid)]})
            elif self.element(str(eid), "change"):
                kept[str(eid)] = status
        return kept

    def renames(self, renamed_from: Any) -> dict:
        kept = {}
        for eid, old in (renamed_from if isinstance(renamed_from, Mapping) else {}).items():
            if self.element(str(eid), "rename") and isinstance(old, (list, tuple)):
                kept[str(eid)] = [str(o) for o in old]
        return kept

    def _relation_renames(self, renamed: Mapping[str, Sequence[str]]) -> dict[str, str]:
        """Old relation id -> current id, for every relation whose endpoint was renamed. A relation id
        is a hash of its endpoints, so renaming either one changes it."""
        olds = lambda e: [e, *renamed.get(e, ())]                                  # noqa: E731
        out = {}
        for r in self.spec["relations"]:
            for s in olds(r.get("src", "")):
                for t in olds(r.get("tgt", "")):
                    out.setdefault(rid(s, r.get("type", ""), t), str(r.get("id")))
        return out

    def reviews(self, reviews: Any, renamed: Mapping[str, Sequence[str]]) -> list:
        """Decisions carry across a re-run (R-1): one on an id that still exists is kept, one on a
        renamed element or on a relation whose endpoint was renamed follows the rename (R-2), and one
        on an id that disappeared becomes a question."""
        followed = {"elements": {old: new for new, olds in renamed.items() for old in olds},
                    "relations": self._relation_renames(renamed)}
        kept = []
        for raw in reviews or []:
            if not isinstance(raw, Mapping):
                self.ask("malformed-review", "a review must be an object")
                continue
            group = f"{raw.get('item_kind')}s"
            item_id = str(raw.get("item_id") or "")
            refs = {group: [item_id]} if group in _GROUPS else None
            if (group not in _GROUPS or raw.get("state") not in REVIEW_STATES or not item_id
                    or not str(raw.get("actor") or "").strip()):
                self.ask("malformed-review", f"a review needs item_kind element|relation, item_id, "
                                             f"state in {REVIEW_STATES} and a named actor", refs)
                continue
            now = item_id if item_id in self.valid[group] else followed[group].get(item_id, item_id)
            if now not in self.valid[group]:
                self.ask("review-orphaned", f"{raw.get('state')} decision by {raw.get('actor')} on "
                                            f"{raw.get('item_kind')} {item_id}, which the model no "
                                            f"longer has", refs)
                continue
            kept.append(_only(raw, REVIEW_KEYS) | {"item_id": now})
        return kept


def build(*, spec: Mapping[str, Any], provenance: Any, sources: Sequence[Source],
          questions: Sequence[Mapping[str, Any]] = (), references: Any = None, changes: Any = None,
          renamed_from: Any = None, reviews: Sequence[Mapping[str, Any]] = ()) -> dict:
    """Wrap a working model as the envelope.

    `provenance` is `{elements: {id: [..]}, relations: {id: [..]}}`; `references` is keyed by
    REFERENCE_KINDS; `changes` is `{element_id: status}`; `renamed_from` is `{new_id: [old ids]}`;
    `reviews` are architect decisions, typically the previous run's, carried across this one."""
    b = _Builder(spec, sources)
    for q in questions:
        if isinstance(q, Mapping):
            kind = q.get("kind") if q.get("kind") in _CALLER_KINDS else "raised"
            b.ask(kind, str(q.get("text") or ""), q.get("refs"))
    b.ids()
    prov = b.provenance(provenance)
    refs = b.references(references)
    chg = b.changes(changes)
    renamed = b.renames(renamed_from)
    revs = b.reviews(reviews, renamed)
    return {"contract_version": CONTRACT_VERSION, "spec": b.spec,
            "sources": [s.to_dict() for s in sources], "provenance": prov, "references": refs,
            "changes": chg, "renamed_from": renamed, "reviews": revs,
            "open_questions": b.questions,
            "dropped": [dict(d) for d in spec.get("dropped") or [] if isinstance(d, Mapping)],
            "gaps": [dict(g) for g in spec.get("gaps") or [] if isinstance(g, Mapping)]}
