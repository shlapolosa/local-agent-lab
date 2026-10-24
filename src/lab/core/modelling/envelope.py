"""The modelling envelope (ADR 2026-10-24): the FR-11 spec UNCHANGED, with what it cannot carry
beside it.

`contracts/archimate-spec.schema.json` refuses any key it does not declare, so the run's working model
(`props`, `dropped`, `gaps`) cannot travel as the spec. The envelope splits the two:
- `spec` is exactly what visualisation consumes;
- beside it sit provenance, sources, map/repository/vocabulary references, per-element change status,
  renames, architect reviews, open questions, dropped relations and gaps.
`contracts/modelling.json` is the published shape, held to this module by
`tests/governance/test_modelling_contract.py`.

The builder runs on agent output inside a long workflow, so bad input is REPORTED as an open question
and never raised.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from lab.core.modelling.provenance import Provenance, Source, check

__all__ = ["CHANGES", "CONTRACT_VERSION", "ELEMENT_KEYS", "ID_PATTERN", "QUESTION_KINDS",
           "REFERENCE_KINDS", "RELATION_KEYS", "REVIEW_KEYS", "REVIEW_STATES", "SPEC_KEYS",
           "STATUSES", "build"]

CONTRACT_VERSION = "1.1.0"

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
                  "unknown-source", "quote-not-found", "unverifiable",
                  "orphan-reference", "malformed-reference",
                  "review-orphaned", "malformed-review", "invalid-id")

_GROUPS = ("elements", "relations")


@dataclass(frozen=True)
class RefKind:
    """One kind of reference: the fields it keeps, which one holds its status, and the allowed values.
    Adding a kind is one entry in REFERENCE_KINDS."""
    keys: tuple[str, ...]
    status_field: str
    statuses: tuple[str, ...]
    subject: str                       # the field naming what is referenced, required non-empty
    element_optional_when: str = ""    # a status under which no element is needed


REFERENCE_KINDS: Mapping[str, RefKind] = {
    "capabilities": RefKind(("element_id", "map", "map_version", "capability_id", "label", "level",
                             "status", "confidence"), "status", STATUSES, "capability_id",
                            element_optional_when="missing"),
    "realisations": RefKind(("element_id", "capability_id", "realised_by", "catalogue_id", "status",
                             "confidence"), "status", STATUSES, "capability_id"),
    "repository": RefKind(("element_id", "repository_id", "repository_class", "match", "confidence",
                           "candidates"), "match", CHANGES, "element_id"),
    "concepts": RefKind(("element_id", "concept_iri", "label", "scheme", "status", "confidence"),
                        "status", CONCEPT_STATUSES, "label"),
}


def _only(d: Mapping[str, Any], keys: Iterable[str]) -> dict:
    return {k: d[k] for k in keys if k in d}


def _spec(working: Mapping[str, Any]) -> dict:
    out = _only(working, SPEC_KEYS)
    out["elements"] = [_only(e, ELEMENT_KEYS) for e in working.get("elements") or []]
    out["relations"] = [_only(r, RELATION_KEYS) for r in working.get("relations") or []]
    return out


def _refs(refs: Mapping[str, Any] | None) -> dict:
    refs = refs or {}
    return {g: [str(x) for x in refs.get(g) or []] for g in _GROUPS}


def _question(kind: str, text: str, refs: Mapping[str, Any] | None = None,
              provenance: Mapping[str, Any] | None = None) -> dict:
    r = _refs(refs)
    key = "|".join([kind, text, *r["elements"], *r["relations"],
                    str((provenance or {}).get("quote", ""))])
    q = {"id": "oq-" + hashlib.md5(key.encode()).hexdigest()[:10], "kind": kind, "text": text,
         "refs": r}
    if provenance:
        q["provenance"] = dict(provenance)
    return q


class _Builder:
    """One envelope build: the clean spec, what is known in it, and the questions raised so far."""

    def __init__(self, spec: Mapping[str, Any], sources: Sequence[Source]):
        self.spec = _spec(spec)
        self.sources = {s.ref: s for s in sources}
        self.known = {g: {str(x.get("id")) for x in self.spec[g]} for g in _GROUPS}
        self.questions: list[dict] = []

    def ask(self, *args, **kw) -> None:
        self.questions.append(_question(*args, **kw))

    def ids(self) -> None:
        for group in _GROUPS:
            for item_id in sorted(self.known[group]):
                if not ID_PATTERN.fullmatch(item_id):
                    self.ask("invalid-id", f"{group[:-1]} id {item_id!r} is not an IRI local name "
                                           f"([A-Za-z0-9_-])", {group: [item_id]})

    def provenance(self, provenance: Mapping[str, Mapping[str, Sequence[Mapping]]]) -> dict:
        kept: dict[str, dict[str, list]] = {g: {} for g in _GROUPS}
        for group in _GROUPS:
            for item_id, entries in (provenance.get(group) or {}).items():
                refs = {group: [item_id]}
                if item_id not in self.known[group]:
                    self.ask("orphan-provenance", f"provenance names {group[:-1]} {item_id}, which "
                                                  f"the model does not have", refs)
                    continue
                for raw in entries or []:
                    try:
                        p = Provenance.from_dict(raw)
                    except ValueError as e:
                        self.ask("malformed-provenance", str(e), refs, raw)
                        continue
                    kept[group].setdefault(item_id, []).append(p.to_dict())
                    kind = check(p, self.sources)
                    if kind:
                        self.ask(kind, f"{kind} for {group[:-1]} {item_id}", refs, p.to_dict())
            for item_id in sorted(self.known[group] - set(kept[group])):
                self.ask("no-provenance", f"{group[:-1]} {item_id} cites no input", {group: [item_id]})
        return kept

    def references(self, refs: Mapping[str, Sequence[Mapping]] | None) -> dict:
        kept: dict[str, list[dict]] = {kind: [] for kind in REFERENCE_KINDS}
        elements = self.known["elements"]
        for kind, rk in REFERENCE_KINDS.items():
            for raw in (refs or {}).get(kind) or []:
                eid = str(raw.get("element_id") or "")
                subject = {"elements": [eid] if eid else []}
                status = raw.get(rk.status_field)
                if status not in rk.statuses or not str(raw.get(rk.subject) or "").strip():
                    self.ask("malformed-reference", f"{kind} reference needs {rk.subject} and "
                                                    f"{rk.status_field} in {rk.statuses}", subject, raw)
                    continue
                if eid not in elements and not (eid == "" and status == rk.element_optional_when):
                    self.ask("orphan-reference", f"{kind} reference names element {eid or '?'}, "
                                                 f"which the model does not have", subject, raw)
                    continue
                kept[kind].append(_only(raw, rk.keys))
        return kept

    def changes(self, changes: Mapping[str, str] | None) -> dict:
        kept = {}
        for eid, status in (changes or {}).items():
            subject = {"elements": [eid]}
            if status not in CHANGES:
                self.ask("malformed-reference", f"change for {eid} must be one of {CHANGES}", subject)
            elif eid not in self.known["elements"]:
                self.ask("orphan-reference", f"change names element {eid}, which the model does "
                                             f"not have", subject)
            else:
                kept[eid] = status
        return kept

    def renames(self, renamed_from: Mapping[str, Sequence[str]] | None) -> dict:
        kept = {}
        for eid, old in (renamed_from or {}).items():
            if eid in self.known["elements"]:
                kept[eid] = [str(o) for o in old]
            else:
                self.ask("orphan-reference", f"rename names element {eid}, which the model does "
                                             f"not have", {"elements": [eid]})
        return kept

    def reviews(self, reviews: Sequence[Mapping], renamed: Mapping[str, Sequence[str]]) -> list:
        """Decisions carry across a re-run (R-1): one on an id that still exists is kept, one on a
        renamed id follows the rename (R-2), and one on an id that disappeared becomes a question."""
        now_named = {old: new for new, olds in renamed.items() for old in olds}
        kept = []
        for raw in reviews:
            kind = raw.get("item_kind")
            group = f"{kind}s"
            item_id = str(raw.get("item_id") or "")
            refs = {group: [item_id]} if group in _GROUPS else None
            if (group not in _GROUPS or raw.get("state") not in REVIEW_STATES or not item_id
                    or not str(raw.get("actor") or "").strip()):
                self.ask("malformed-review", f"a review needs item_kind element|relation, item_id, "
                                             f"state in {REVIEW_STATES} and a named actor", refs)
                continue
            item_id = item_id if item_id in self.known[group] else now_named.get(item_id, item_id)
            if item_id not in self.known[group]:
                self.ask("review-orphaned", f"{raw.get('state')} decision by {raw.get('actor')} on "
                                            f"{kind} {raw.get('item_id')}, which the model no longer "
                                            f"has", refs)
                continue
            kept.append(_only(raw, REVIEW_KEYS) | {"item_id": item_id})
        return kept


def build(*, spec: Mapping[str, Any], provenance: Mapping[str, Mapping[str, Sequence[Mapping]]],
          sources: Sequence[Source], questions: Sequence[Mapping[str, Any]] = (),
          references: Mapping[str, Sequence[Mapping]] | None = None,
          changes: Mapping[str, str] | None = None,
          renamed_from: Mapping[str, Sequence[str]] | None = None,
          reviews: Sequence[Mapping[str, Any]] = ()) -> dict:
    """Wrap a working model as the envelope.

    `provenance` is `{elements: {id: [..]}, relations: {id: [..]}}`; `references` is keyed by
    REFERENCE_KINDS; `changes` is `{element_id: status}`; `renamed_from` is `{new_id: [old ids]}`;
    `reviews` are architect decisions, typically the previous run's, carried across this one."""
    b = _Builder(spec, sources)
    for q in questions:
        b.ask("raised", str(q.get("text") or ""), q.get("refs"))
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
            "dropped": list(spec.get("dropped") or []), "gaps": list(spec.get("gaps") or [])}
