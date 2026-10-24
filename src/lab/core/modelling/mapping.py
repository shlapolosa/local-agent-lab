"""The modelling agent's output -> the envelope. Deterministic and pure.

PRECONDITION: the output has passed `agent_schema.schema()` (the workload gates it first). Anything
that passes, the envelope accepts without raising.

Ids come from `ids.element_id(type, name)`, the same rule the use-case mappers follow. Relations
resolve their endpoints by element NAME (what the agent sees and writes); a name the model gives two
types resolves to the one reading the published matrix permits. Every relation is checked by
`Model.rel`, and an illegal, unknown or ambiguous one is DROPPED with its reason and the citations that
proposed it, never raised. Citations name a source key; the ref replaces it here, and an unknown key
passes through so the envelope flags it as `unknown-source`.
"""
from __future__ import annotations

from typing import Any, Mapping

from lab.core.archimate import ids, relrepair
from lab.core.modelling import envelope
from lab.core.modelling.model import Model
from lab.core.modelling.provenance import Source

__all__ = ["to_envelope"]


def _prov(cites, sources: Mapping[str, Source]) -> list[dict]:
    return [{"source_ref": sources[c["source"]].ref if c.get("source") in sources else str(c.get("source")),
             "location": c.get("location") or {}, "quote": c.get("quote") or ""}
            for c in cites or []]


def _key(name: str) -> str:
    return " ".join(str(name).split()).casefold()


def to_envelope(output: Mapping[str, Any], sources: Mapping[str, Source], **extra) -> dict:
    """`sources` is the keyed map the agent was shown. `extra` passes straight to `envelope.build`
    (references, changes, renamed_from, reviews)."""
    model = Model(name=str(output.get("systemName") or "model"))
    prov: dict[str, dict[str, list]] = {"elements": {}, "relations": {}}
    by_name: dict[str, set[str]] = {}
    named: dict[str, str] = {}                    # id -> the name that minted it
    questions: list[dict] = []

    for e in output.get("elements") or []:
        eid = ids.element_id(e["type"], e["name"])
        if not eid:
            continue
        if eid in named and named[eid] != _key(e["name"]):
            questions.append({"text": f"'{e['name']}' and an earlier element take the same id {eid}, "
                                      f"so they were merged; are they the same thing?",
                              "refs": {"elements": [eid]}, "kind": "name-collision"})
        named.setdefault(eid, _key(e["name"]))
        model.el(eid, e["type"], e["name"], doc=e.get("role"))
        prov["elements"].setdefault(eid, []).extend(_prov(e.get("provenance"), sources))
        by_name.setdefault(_key(e["name"]), set()).add(eid)

    def resolve(r) -> tuple[str, str, str]:
        """(src, tgt, why-dropped). Several readings of a name: keep the pair the matrix permits."""
        srcs, tgts = by_name.get(_key(r["source"]), set()), by_name.get(_key(r["target"]), set())
        for end, hits in ((r["source"], srcs), (r["target"], tgts)):
            if not hits:
                return "", "", f"endpoint not declared: {end}"
        legal = [(s, t) for s in sorted(srcs) for t in sorted(tgts)
                 if relrepair.check(model.elements[s]["type"], r["type"], model.elements[t]["type"])[0]]
        if len(srcs) == len(tgts) == 1 or len(legal) == 1:
            s, t = legal[0] if legal else (next(iter(srcs)), next(iter(tgts)))
            return s, t, ""
        end = r["source"] if len(srcs) > 1 else r["target"]
        return "", "", f"ambiguous endpoint: {end}"

    for r in output.get("relationships") or []:
        cites = _prov(r.get("provenance"), sources)
        src, tgt, why = resolve(r)
        if why:
            model.dropped.append({"type": r["type"], "src": src or r["source"], "tgt": tgt or r["target"],
                                  "reason": why, "provenance": cites})
            continue
        access = r.get("accessType") if r["type"] == "Access" else None
        before = len(model.dropped)
        rel_id = model.rel(r["type"], src, tgt, accessType=access)
        if rel_id:
            prov["relations"].setdefault(rel_id, []).extend(cites)
        elif len(model.dropped) > before:
            model.dropped[-1]["provenance"] = cites

    questions += [{"text": q.get("text", ""),
                   "refs": {"elements": sorted({i for n in q.get("elements") or []
                                                for i in by_name.get(_key(n), ())})}}
                  for q in output.get("openQuestions") or []]
    return envelope.build(spec=model.to_spec(), provenance=prov, sources=list(sources.values()),
                          questions=questions, **extra)
