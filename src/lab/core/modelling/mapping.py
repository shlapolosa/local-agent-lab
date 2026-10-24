"""The modelling agent's output -> the envelope. Deterministic and pure.

Ids come from `ids.element_id(type, name)`, the same rule the use-case mappers follow. Relations
resolve their endpoints by element NAME (what the agent sees and writes). Every relation is checked
against the published matrix by `Model.rel`, and an illegal, unknown or ambiguous one is DROPPED with
its reason, never raised. Citations name a source key; the ref replaces it here, and an unknown key
passes through so the envelope flags it as `unknown-source`.
"""
from __future__ import annotations

from typing import Any, Mapping

from lab.core.archimate import ids
from lab.core.modelling import envelope
from lab.core.modelling.provenance import Source
from lab.core.usecase.run_model import Model

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
    model = Model(name=str(output.get("systemName") or "model"), id="model")
    prov: dict[str, dict[str, list]] = {"elements": {}, "relations": {}}
    by_name: dict[str, set[str]] = {}

    for e in output.get("elements") or []:
        eid = ids.element_id(e["type"], e["name"])
        if not eid:
            continue
        model.el(eid, e["type"], e["name"], doc=e.get("role"))
        prov["elements"].setdefault(eid, []).extend(_prov(e.get("provenance"), sources))
        by_name.setdefault(_key(e["name"]), set()).add(eid)

    def resolve(name: str) -> tuple[str, str]:
        hits = by_name.get(_key(name), set())
        if len(hits) == 1:
            return next(iter(hits)), ""
        return "", f"{'ambiguous endpoint' if hits else 'endpoint not declared'}: {name}"

    for r in output.get("relationships") or []:
        (src, why_s), (tgt, why_t) = resolve(r["source"]), resolve(r["target"])
        if why_s or why_t:
            model.dropped.append({"type": r["type"], "src": src or r["source"],
                                  "tgt": tgt or r["target"], "reason": why_s or why_t})
            continue
        access = r.get("accessType") if r["type"] == "Access" else None
        if model.rel(r["type"], src, tgt, accessType=access):
            prov["relations"].setdefault(ids.rid(src, r["type"], tgt), []).extend(
                _prov(r.get("provenance"), sources))

    questions = [{"text": q.get("text", ""),
                  "refs": {"elements": sorted({i for n in q.get("elements") or []
                                               for i in by_name.get(_key(n), ())})}}
                 for q in output.get("openQuestions") or []]
    return envelope.build(spec=model.to_spec(), provenance=prov, sources=list(sources.values()),
                          questions=questions, **extra)
