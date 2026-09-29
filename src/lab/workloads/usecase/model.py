"""The ONE architecture model a use-case run grows, step by step.

Every agent step's output is mapped onto it by a deterministic mapper (`mappers.MAPPERS`), so by
the time the solution architect selects components the business, data and application layers are
already there as DATA the step can read.

The shape is the engine's spec (`lab.core.archimate.engine`): `{name, id, elements[],
relations[]}`. Nothing draws it any more — the use case is drawn as the CAFÉ views
(`lab.workloads.usecase.views`, 29 Sep 2026) — but it rides the record and step 21 reads its
summary. Two things beyond the engine's shape are carried: `props`
(the CAFÉ zone, family and archetype tags, and the step facets — a
tier, an exposure, a band — that the record keeps but the XML export does not yet) and `dropped`, the proposals the
published relationship matrix refused. A mapper is deterministic and runs inside a 600-1000 s
workflow, so an illegal relation is COUNTED and left out, never raised — the model stays legal,
and the count says how much of a step's output could not be expressed.

Pure: no I/O, no gateway. `lab.workloads.usecase` because it is this run's working artifact; the
legality decision it defers to lives in `lab.core.archimate.relrepair`.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping

from lab.core.archimate import relrepair
from lab.core.archimate.engine import _REL_TYPES, _TYPES
from lab.workloads import ids

__all__ = ["LAYER_OF", "Model"]

#: ArchiMate type -> its layer, from the taxonomy the engine loads. The layer is the element's
#: `folder`, so the XML's organisation tree groups what a reviewer scans by layer.
LAYER_OF: Mapping[str, str] = _TYPES


@dataclass
class Model:
    name: str = "use case"
    #: Not the root ELEMENT's id (`mappers.ROOT`, "usecase"): the engine mints `id-<x>` for the model
    #: and for every element alike, and the XSD refuses two xs:IDs the same.
    id: str = "usecase-model"
    elements: dict[str, dict] = field(default_factory=dict)              # id -> element
    relations: dict[tuple[str, str, str], dict] = field(default_factory=dict)   # (src,tgt,type) -> relation
    dropped: list[dict] = field(default_factory=list)
    #: Things a MAPPER could not join, as distinct from a relation the matrix refused. `dropped`
    #: means "this edge is illegal ArchiMate" and several rules assert it is empty; overloading it
    #: with "step 21 named a capability step 5 never matched" would make that invariant mean two
    #: things and silently weaken it. Different fault, different owner, different list.
    gaps: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------------ growing it
    def el(self, eid: str, atype: str, name: str = "", *, doc: str | None = None,
           folder: str | None = None, props: Mapping[str, Any] | None = None) -> str:
        """Add or UPDATE an element by id: later fields win, `props` are merged, a blank `name`
        never erases a known one. An unknown type is a programming error in a mapper, not data."""
        if atype not in _TYPES:
            raise ValueError(f"unknown ArchiMate element type: {atype}")
        if not eid:
            raise ValueError("an element needs an id")
        cur = self.elements.get(eid) or {"id": eid, "type": atype, "name": name or eid}
        cur["type"] = atype
        if name:
            cur["name"] = name
        if doc:
            cur["doc"] = doc
        cur["folder"] = folder or cur.get("folder") or LAYER_OF.get(atype, "Other")
        if props:
            merged = dict(cur.get("props") or {})
            merged.update({k: v for k, v in props.items() if v not in (None, "")})
            if merged:
                cur["props"] = merged
        self.elements[eid] = cur
        return eid

    def rel(self, rtype: str, src: str, tgt: str, *, accessType: str | None = None) -> bool:
        """Propose a relation. Both endpoints must already be in the model and the type must be
        permitted between their types by the published matrix — otherwise it is recorded under
        `dropped` with what WOULD have been allowed, and the model is left legal."""
        if rtype not in _REL_TYPES:
            raise ValueError(f"unknown ArchiMate relation type: {rtype}")
        if src not in self.elements or tgt not in self.elements:
            self.dropped.append({"type": rtype, "src": src, "tgt": tgt,
                                 "reason": "endpoint not declared"})
            return False
        key = (src, tgt, rtype)
        if key in self.relations:
            return True
        ok, allowed = relrepair.check(self.elements[src]["type"], rtype, self.elements[tgt]["type"])
        if not ok:
            self.dropped.append({"type": rtype, "src": src, "tgt": tgt,
                                 "types": f'{self.elements[src]["type"]} -> {self.elements[tgt]["type"]}',
                                 "allowed": list(allowed)})
            return False
        rel = {"id": ids.rid(src, rtype, tgt), "type": rtype, "src": src, "tgt": tgt}
        if accessType:
            rel["accessType"] = accessType
        self.relations[key] = rel
        return True

    # ------------------------------------------------------------------ reading it
    def has(self, eid: str) -> bool:
        return eid in self.elements

    def by_type(self, atype: str) -> list[dict]:
        return [copy.deepcopy(e) for e in self.elements.values() if e["type"] == atype]

    def props_of(self, eid: str) -> dict:
        return dict((self.elements.get(eid) or {}).get("props") or {})

    def counts(self) -> dict:
        return {"elements": len(self.elements), "relations": len(self.relations),
                "dropped": len(self.dropped), "gaps": len(self.gaps)}

    # ------------------------------------------------------------------ the spec shape
    def to_spec(self) -> dict:
        """The engine spec, plus `props`/`dropped` which the engine ignores. `standard_views` asks
        the renderer for the layer-pair catalogue (views with no edge are dropped by the engine)."""
        return {"name": self.name, "id": self.id,
                "elements": [copy.deepcopy(e) for e in self.elements.values()],
                "relations": [copy.deepcopy(r) for r in self.relations.values()],
                "dropped": copy.deepcopy(self.dropped),
                "gaps": copy.deepcopy(self.gaps),
                "standard_views": True}

    @classmethod
    def from_spec(cls, spec: Mapping[str, Any]) -> "Model":
        """The inverse of `to_spec`, tolerant of a spec the engine or a person wrote: relations
        without an id get the stable one, unknown endpoints are dropped and counted."""
        m = cls(name=str(spec.get("name") or "use case"), id=str(spec.get("id") or "usecase-model"))
        for e in spec.get("elements") or []:
            m.el(e["id"], e["type"], e.get("name", ""), doc=e.get("doc"), folder=e.get("folder"),
                 props=e.get("props"))
        for r in spec.get("relations") or []:
            m.rel(r["type"], r["src"], r["tgt"], accessType=r.get("accessType"))
        m.dropped = list(spec.get("dropped") or []) + m.dropped
        return m
