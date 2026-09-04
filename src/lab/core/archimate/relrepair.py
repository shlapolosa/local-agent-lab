"""Deterministic ArchiMate relation repair.

A workflow node ([D] — no LLM) that runs BEFORE a model is stored/rendered: every relation whose
type is NOT permitted between its endpoint types is rewritten to an intent-preserving LEGAL
type. Legal relations are never touched; no relation is invented, dropped or reversed; ids and
direction are preserved. Every change is reported so the approval summary / openQuestions can
show a reviewer exactly what was rewritten and why.

Legality is decided by the SAME check `Model.validate_relations()` uses — the repo's semantic
layer (`archimate_engine._semantic()` -> `SemanticService.check(src_type, rel, tgt_type)`, i.e.
`Vocabulary.check` over Archi's complete ArchiMate 3.1 Appendix B matrix, which also gives the
`allowed` list the engine prints). When the semantic layer is not importable the engine's own
coarse category rules are used instead (probed through a throwaway two-element `Model`, so no
rule is duplicated here). Nothing in this module hardcodes a relationship matrix.

Substitution policy (ordered, every candidate is matrix-checked before it is applied):
  1. INTENT table — the systematic LLM confusions seen in live runs:
       * Composition/Aggregation  active structure -> behaviour (Function/Process/Interaction/Event)
         -> Assignment          ("the component groups these functions" means "performs")
       * Composition/Aggregation  active structure -> service       -> Realization
       * Assignment               technology active structure (SystemSoftware/Node/Device)
                                  -> application/business element   -> Realization
  2. CATEGORY preference — the first permitted relation from the list of the original's category:
       structural [Composition, Aggregation, Assignment, Realization]
       dependency [Serving, Access, Influence]
       dynamic    [Triggering, Flow]
  3. Association — ArchiMate permits it between any two elements; flagged `rule="fallback_association"`
     so a reviewer looks at it.

API
  repair(model)      -> (model, report)   IN PLACE: the same `Model` object is returned, relation
                                          ids/src/tgt/extra attrs kept, only the type rewritten.
  repair_spec(spec)  -> (spec', report)   COPY: a deep copy of the engine spec shape
                                          {elements:[{id,type,name}], relations:[{id,type,src,tgt}]}.
  Report entry: {rid, src, tgt, src_type, tgt_type, original, replaced, rule, reason, allowed}
  `reason` is human-readable; `rule` is one of intent | category_preference | fallback_association
  | unrepairable (replaced == original; e.g. an undeclared endpoint — the validator reports those).
"""
import copy
import functools
import sys

from lab.core.archimate.engine import Model, _REL_TYPES, _TYPES, _aspect, _semantic

# Preference lists per category (policy step 2). The category of a relation type comes from the
# semantic layer's RELATIONS table when importable; this map is the same grouping as a fallback.
_CATEGORY_PREFS = {
    "structural": ["Composition", "Aggregation", "Assignment", "Realization"],
    "dependency": ["Serving", "Access", "Influence"],
    "dynamic": ["Triggering", "Flow"],
}
_FALLBACK_CATEGORY = {t: c for c, ts in _CATEGORY_PREFS.items() for t in ts}
_TECH_ACTIVE = ("SystemSoftware", "Node", "Device")
_BEHAVIOUR_SUFFIX = ("Function", "Process", "Interaction", "Event")


# ------------------------------------------------------------------ legality (reused, not redefined)
@functools.lru_cache(maxsize=1)
def _sem():
    return _semantic()


def _category(rtype):
    try:
        from lab.core.semantic.archimate.vocab import RELATIONS
        return RELATIONS.get(rtype, {}).get("category", _FALLBACK_CATEGORY.get(rtype, "other"))
    except Exception:
        return _FALLBACK_CATEGORY.get(rtype, "other")


def _coarse_ok(src_type, rtype, tgt_type):
    """No semantic layer: the engine's own coarse rules, via a throwaway 2-element Model."""
    m = Model("probe", mid="probe")
    m.el("s", src_type, "s"); m.el("t", tgt_type, "t"); m.rel(rtype, "s", "t", rid="p")
    return not m.validate_relations()


def check(src_type, rtype, tgt_type):
    """(ok, allowed) — the exact decision Model.validate_relations() makes: SemanticService.check
    (Archi's full matrix) when importable, else the engine's coarse rules."""
    sem = _sem()
    if sem is not None:
        c = sem.check(src_type, rtype, tgt_type)
        return bool(c["ok"]), list(c["allowed"])
    allowed = [r for r in _REL_TYPES if r != "Junction" and _coarse_ok(src_type, r, tgt_type)]
    return rtype in allowed, allowed


# ------------------------------------------------------------------ policy
def _intent(src_type, rtype, tgt_type):
    """Step 1: the explicit intent table. Returns (replacement, why) or None."""
    a_s, layer_t = _aspect(src_type), _TYPES.get(tgt_type, "Other")
    if rtype in ("Composition", "Aggregation") and a_s == "Active":
        if tgt_type.endswith(_BEHAVIOUR_SUFFIX):
            return "Assignment", (f"{rtype} from active structure {src_type} to behaviour {tgt_type} "
                                  f"reads as 'performs' — active structure is ASSIGNED to behaviour")
        if tgt_type.endswith("Service"):
            return "Realization", (f"{rtype} from active structure {src_type} to service {tgt_type} "
                                   f"reads as 'provides' — active structure REALIZES a service")
    if rtype == "Assignment" and src_type in _TECH_ACTIVE and layer_t in ("Application", "Business"):
        return "Realization", (f"Assignment from technology {src_type} to {layer_t.lower()} element "
                               f"{tgt_type} reads as 'hosts/implements' — technology REALIZES it")
    return None


def decide(src_type, rtype, tgt_type):
    """The repair decision for one (src_type, rtype, tgt_type). Returns None when the relation is
    already legal, else a dict {replaced, rule, reason, allowed}."""
    ok, allowed = check(src_type, rtype, tgt_type)
    if ok:
        return None
    hit = _intent(src_type, rtype, tgt_type)
    if hit and hit[0] in allowed:
        return {"replaced": hit[0], "rule": "intent",
                "reason": f"{rtype} not permitted for {src_type} -> {tgt_type}; {hit[1]}", "allowed": allowed}
    cat = _category(rtype)
    for cand in _CATEGORY_PREFS.get(cat, []):
        if cand != rtype and cand in allowed:
            return {"replaced": cand, "rule": "category_preference",
                    "reason": (f"{rtype} not permitted for {src_type} -> {tgt_type}; nearest permitted "
                               f"{cat} relation is {cand}"), "allowed": allowed}
    if "Association" in allowed:
        return {"replaced": "Association", "rule": "fallback_association",
                "reason": (f"fallback_association: {rtype} not permitted for {src_type} -> {tgt_type} and no "
                           f"{cat} alternative is either — downgraded to Association; REVIEW the intent"),
                "allowed": allowed}
    return {"replaced": rtype, "rule": "unrepairable",
            "reason": f"unrepairable: {rtype} not permitted for {src_type} -> {tgt_type} and nothing is allowed",
            "allowed": allowed}


def _repair_rows(types, rows):
    """types: id -> element type; rows: iterable of (rid, rtype, src, tgt). Yields report entries
    only for relations that are not legal as given."""
    for rid, rtype, src, tgt in rows:
        st, tt = types.get(src), types.get(tgt)
        base = {"rid": rid, "src": src, "tgt": tgt, "src_type": st, "tgt_type": tt, "original": rtype}
        if st is None or tt is None:
            yield {**base, "replaced": rtype, "rule": "unrepairable",
                   "reason": "unrepairable: relationship endpoint not declared", "allowed": []}
            continue
        d = decide(st, rtype, tt)
        if d is not None:
            yield {**base, **d}


# ------------------------------------------------------------------ public API
def repair(model):
    """Repair `model` IN PLACE (same object returned; relation ids, endpoints, direction and extra
    attributes kept; only illegal types rewritten). Returns (model, report)."""
    types = {eid: t for eid, (t, _, _) in model.elements.items()}
    rows = [(rid, rt, s, g) for rid, (rt, s, g, _) in model.relations.items()]
    report = list(_repair_rows(types, rows))
    for e in report:
        if e["replaced"] != e["original"]:
            _, s, g, extra = model.relations[e["rid"]]
            model.relations[e["rid"]] = (e["replaced"], s, g, extra)
    return model, report


def repair_spec(spec):
    """Repair the engine/MCP spec shape {elements:[{id,type,...}], relations:[{id,type,src,tgt,...}]}.
    Returns (deep-copied spec with types rewritten, report); the input is not modified."""
    out = copy.deepcopy(spec)
    types = {e["id"]: e["type"] for e in out.get("elements", [])}
    rels = out.get("relations", [])
    rows = [(r.get("id") or f"r{i + 1}", r["type"], r["src"], r["tgt"]) for i, r in enumerate(rels)]
    report = list(_repair_rows(types, rows))
    by_rid = {rid: r for (rid, _, _, _), r in zip(rows, rels)}
    for e in report:
        if e["replaced"] != e["original"]:
            by_rid[e["rid"]]["type"] = e["replaced"]
    return out, report


def summarize(report):
    """One human-readable line per change, for approval summaries / openQuestions."""
    return [f"{e['rid']} ({e['src']}->{e['tgt']}, {e['src_type']} -> {e['tgt_type']}): "
            f"{e['original']} -> {e['replaced']} [{e['rule']}] — {e['reason']}" for e in report]


def main(argv=None):
    """CLI: relrepair <spec.json> -> repaired spec on stdout, report on stderr."""
    import json
    argv = sys.argv[1:] if argv is None else argv
    spec = json.load(open(argv[0]))
    fixed, rep = repair_spec(spec)
    print(json.dumps(fixed, indent=2))
    for line in summarize(rep):
        print(line, file=sys.stderr)


if __name__ == "__main__":
    main()
