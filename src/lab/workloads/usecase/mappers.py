"""One deterministic mapper per step: its output, onto the run's ArchiMate model.

A mapper is the translation at the edge between a step's bounded context (what a business analyst
or a risk officer wrote down, in that exercise's own vocabulary) and the model every later step
reads. It is keyed by the step KEY, never the number — numbers are the process's, keys are the
record's, and a mapper is about the record.

Rules every mapper obeys:
- deterministic and total: it never raises into the run (`apply` records a failure under
  `model.dropped` and the model stays as it was), and an illegal relation is counted, not thrown;
- it never invents: an element it names comes from the step's output or from the pinned corpus
  the step was shown (`component_catalogue`, `topology_archetypes` in the pool);
- ids are a pure function of the output (`ids.slug`), prefixed by kind, so a second run of the
  same step updates rather than duplicates — the accumulation semantics that make one model
  possible across screening, design and investment;
- a join across steps is by the id the steps share: the workflow graph's node ids (`n1`..) are the
  facet vector's, the determinism classifier's and the exposure derivation's, so all four land on
  ONE `bp-<id>` element; a function name from step 4 is the one step 5 and step 10 cite.

CAFÉ rides as `props` on the elements the draw.io projection reads: `cafe.zone`,
`cafe.component_id`, `cafe.families` on a selected component, `cafe.archetype`/`cafe.topology` on
the root. Nothing here draws.
"""
from __future__ import annotations

import traceback
from typing import Any, Callable, Mapping

from lab.workloads import ids
from lab.workloads.usecase.model import Model

__all__ = ["MAPPERS", "ROOT", "UNMAPPED", "apply", "as_list", "summary"]

ROOT = "usecase"
Mapper = Callable[[Mapping[str, Any], Model, Mapping[str, Any]], None]


# ------------------------------------------------------------------ small pure helpers
def as_list(value) -> list[str]:
    """A value that may be a list or the `;`-joined string a corpus cell or a `props` entry keeps.
    ONE home — `steps._families_realised` and `summary` compare family sets across it."""
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value or "").split(";") if v.strip()]


def _s(value) -> str:
    return str(value or "").strip()


def _root(model: Model, name: str = "") -> str:
    return model.el(ROOT, "Grouping", name or ("" if model.has(ROOT) else "use case"))


def _rows(pool: Mapping[str, Any], key: str) -> list[dict]:
    return [r for r in (pool.get(key) or []) if isinstance(r, Mapping)]


def _catalogue(pool: Mapping[str, Any]) -> dict[str, dict]:
    return {_s(r.get("id")): r for r in _rows(pool, "component_catalogue") if _s(r.get("id"))}


def _bf(model: Model, function: str) -> str | None:
    """The BusinessFunction a step cites by NAME (step 4 declared it) — created if the citing step
    is the first to name it, because a dropped citation is a silent hole in the model."""
    slug = ids.slug(function)
    if not slug:
        return None
    return model.el(f"bf-{slug}", "BusinessFunction", function)


def _bp(model: Model, node_id: str, name: str = "") -> str | None:
    """The BusinessProcess for a workflow-graph node id, shared by steps 10, 15, 17, 18 and 19."""
    if not _s(node_id):
        return None
    return model.el(f"bp-{ids.slug(node_id)}", "BusinessProcess", name)


# ------------------------------------------------------------------ screening (steps 3-11)
def _frame(out, model, pool):
    problem = _s(out.get("problem"))
    root = _root(model, problem[:80])
    model.el(root, "Grouping", props={"problem": problem, "for_whom": _s(out.get("for_whom")),
                                      "source_channel": _s(out.get("source_channel"))})
    who = ids.slug(_s(out.get("for_whom")))
    drv = model.el("drv-problem", "Driver", problem[:120] or "the problem")
    goal = model.el("goal-expected-change", "Goal", _s(out.get("expected_change"))[:120] or "the expected change")
    model.rel("Association", drv, goal)
    if who:
        model.rel("Association", model.el(f"stk-{who}", "Stakeholder", _s(out.get("for_whom"))), drv)
    owner = ids.slug(_s(out.get("accountable_owner")))
    if owner:
        model.rel("Association", model.el(f"ba-{owner}", "BusinessActor", _s(out.get("accountable_owner")),
                                          props={"role": "accountable owner"}), goal)


def _elements(out, model, pool):
    root = _root(model)
    for a in out.get("active") or []:
        slug = ids.slug(_s(a.get("name")))
        if slug:
            model.rel("Aggregation", root, model.el(f"ba-{slug}", "BusinessActor", _s(a.get("name")),
                                                    props={"kind": _s(a.get("kind")),
                                                           "provenance": _s(a.get("provenance"))}))
    for p in out.get("passive") or []:
        slug = ids.slug(_s(p.get("name")))
        if slug:
            model.rel("Aggregation", root, model.el(f"bo-{slug}", "BusinessObject", _s(p.get("name")),
                                                    props={"provenance": _s(p.get("provenance"))}))
    for b in out.get("behavioural") or []:
        slug = ids.slug(_s(b.get("name")))
        if not slug:
            continue
        bf = model.el(f"bf-{slug}", "BusinessFunction", _s(b.get("name")),
                      props={"verb": _s(b.get("verb")), "object": _s(b.get("object")),
                             "provenance": _s(b.get("provenance"))})
        model.rel("Aggregation", root, bf)
        obj = ids.slug(_s(b.get("object")))
        if obj and model.has(f"bo-{obj}"):
            model.rel("Access", bf, f"bo-{obj}")


def _coverage_map(out, model, pool):
    for m in out.get("matched") or []:
        cap_id = _s(m.get("capability_id"))
        if not cap_id:
            continue
        cap = model.el(cap_id, "Capability", _s(m.get("capability_label")) or cap_id,
                       props={"level": m.get("level"), "confidence": _s(m.get("confidence")),
                              "path": " / ".join(as_list(m.get("path")))})
        bf = _bf(model, _s(m.get("function")))
        if bf:
            model.rel("Realization", bf, cap)
    heat = out.get("heat_map") or {}
    if heat:
        model.el(_root(model), "Grouping", props={f"heat.{k}": heat.get(k)
                                                  for k in ("commodity", "mature", "meets_target")})


def _realisation_match(out, model, pool):
    root = _root(model)
    for m in out.get("matched") or []:
        by = _s(m.get("realised_by"))
        if not ids.slug(by):
            continue
        ac = model.el(f"ac-{ids.slug(by)}", "ApplicationComponent", by,
                      props={"existing": True, "confidence": _s(m.get("confidence"))})
        model.rel("Aggregation", root, ac)
        slug = ids.slug(_s(m.get("element")))
        if model.has(f"bf-{slug}"):
            model.rel("Serving", ac, f"bf-{slug}")
        elif model.has(f"ba-{slug}") or model.has(f"bo-{slug}"):
            model.rel("Association", ac, f"ba-{slug}" if model.has(f"ba-{slug}") else f"bo-{slug}")


def _criticality_band(out, model, pool):
    model.el(_root(model), "Grouping", props={"criticality.band": _s(out.get("band")),
                                              "criticality.provisional": out.get("provisional"),
                                              "criticality.failure_mode": _s(out.get("dominant_failure_mode"))})


def _quality_attributes(out, model, pool):
    seen: dict[str, int] = {}
    for sc in out.get("scenarios") or []:
        bf = _bf(model, _s(sc.get("function")))
        if not bf:
            continue
        n = seen[bf] = seen.get(bf, 0) + 1
        title = f'{_s(sc.get("stimulus"))} → {_s(sc.get("response"))}'.strip(" →") or \
            f'{_s(sc.get("function"))}: {sc.get("response_measure")} {_s(sc.get("unit"))}'
        req = model.el(f"req-{bf[3:]}-{n}", "Requirement", title[:120],
                       props={"response_measure": sc.get("response_measure"), "unit": _s(sc.get("unit")),
                              "percentile": sc.get("percentile"), "taken_from": _s(sc.get("taken_from"))})
        model.rel("Realization", bf, req)


def _ontology_delta(out, model, pool):
    for c in out.get("concepts") or []:
        slug = ids.slug(_s(c.get("object")))
        if slug:
            model.el(f"bo-{slug}", "BusinessObject", _s(c.get("object")),
                     props={"ontology.status": _s(c.get("status")), "ontology.note": _s(c.get("note"))})


def _workflow_graph(out, model, pool):
    for n in out.get("nodes") or []:
        bp = _bp(model, _s(n.get("id")), _s(n.get("activity")))
        if not bp:
            continue
        model.el(bp, "BusinessProcess", props={"node": _s(n.get("id"))})
        bf = _bf(model, _s(n.get("function")))
        if bf:
            model.rel("Aggregation", bf, bp)
        actor = ids.slug(_s(n.get("performed_by")))
        if actor:
            model.rel("Assignment", model.el(f"ba-{actor}", "BusinessActor", _s(n.get("performed_by"))), bp)
    for e in out.get("edges") or []:
        src, tgt = _bp(model, _s(e.get("from"))), _bp(model, _s(e.get("to")))
        if src and tgt:
            model.rel("Triggering", src, tgt)
        data = ids.slug(_s(e.get("data_class")))
        if data:
            bo = model.el(f"bo-{data}", "BusinessObject", _s(e.get("data_class")))
            if src:
                model.rel("Access", src, bo, accessType="Write")
            if tgt:
                model.rel("Access", tgt, bo, accessType="Read")


def _source_contracts(out, model, pool):
    for s in out.get("sources") or []:
        slug = ids.slug(_s(s.get("source")))
        if slug:
            model.el(f"bo-{slug}", "BusinessObject", _s(s.get("source")),
                     props={k: _s(s.get(k)) for k in ("sensitivity", "freshness", "permission_scope",
                                                      "citation_policy", "propagation")})


# ------------------------------------------------------------------ design (steps 13-25)
def _assertions(out, model, pool):
    """An outcome per assertion, anchored on what the step SAID it is evaluated against when that
    names something in the model — never fanned out over every capability: a relation the step did
    not assert is a relation a reviewer approves without anyone having derived it."""
    root = _root(model)
    for n, a in enumerate(out.get("assertions") or [], start=1):
        statement = _s(a.get("statement"))
        if not statement:
            continue
        outcome = model.el(f"out-{n}", "Outcome", statement[:120],
                           props={"evaluated_against": _s(a.get("evaluated_against")),
                                  "reads_workflow_output": a.get("reads_workflow_output")})
        model.rel("Aggregation", root, outcome)
        against = ids.slug(_s(a.get("evaluated_against")))
        for prefix in ("bo", "ac", "bf", "bp"):
            if against and model.has(f"{prefix}-{against}"):
                model.rel("Association", f"{prefix}-{against}", outcome)
                break


def _step_props(out, model, pool, fields: tuple[str, ...], name_field: str = ""):
    """Facets onto the node's BusinessProcess. `name_field` names a node the graph never declared
    (a facet id with no node still lands); it never renames one the graph did."""
    for st in out.get("steps") or []:
        known = model.has(f"bp-{ids.slug(_s(st.get('id')))}")
        bp = _bp(model, _s(st.get("id")), "" if known or not name_field else _s(st.get(name_field)))
        if bp:
            model.el(bp, "BusinessProcess", props={k: st.get(k) for k in fields if st.get(k) not in (None, "")})


def _determinism(out, model, pool):
    _step_props(out, model, pool, ("tier", "necessity", "reducible_to"))
    model.el(_root(model), "Grouping", props={"governance_tier": _s(out.get("governance_tier"))})


def _facet_vectors(out, model, pool):
    _step_props(out, model, pool, ("determinism", "effect", "reversibility", "blast_radius",
                                   "audience", "authorisation", "domain"), name_field="activity")


def _risk(out, model, pool):
    for node_id, facets in (out.get("steps") or {}).items():
        bp = _bp(model, _s(node_id))
        if bp and isinstance(facets, Mapping):
            model.el(bp, "BusinessProcess", props={"exposure": facets.get("exposure"),
                                                   "influence": facets.get("influence")})


def _obligations(out, model, pool):
    for g in out.get("guardrails") or []:
        if _s(g):
            model.el(f"con-{ids.slug(_s(g))}", "Constraint", _s(g), props={"guardrail": _s(g)})
    for node_id, items in (out.get("by_step") or {}).items():
        bp = _bp(model, _s(node_id))
        for o in items or []:
            g = _s(o.get("guardrail"))
            if not g:
                continue
            con = model.el(f"con-{ids.slug(g)}", "Constraint", (_s(o.get("text")) or g)[:120],
                           props={"guardrail": g, "source": _s(o.get("source"))})
            if bp:
                model.rel("Association", con, bp)


def _build_surface(out, model, pool):
    root = _root(model)
    model.el(root, "Grouping", props={"cafe.topology": _s(out.get("topology")),
                                      "surface.incumbent": _s(out.get("incumbent")),
                                      "surface.incumbent_failed_obligations":
                                          "; ".join(as_list(out.get("incumbent_failed_obligations")))})
    surface = _s(out.get("surface"))
    if ids.slug(surface):
        model.rel("Aggregation", root, model.el(f"node-{ids.slug(surface)}", "Node", surface,
                                                props={"surface": True}))


def _composition(out, model, pool):
    topology = _s(out.get("topology"))
    admitted: list[str] = []
    for row in _rows(pool, "topology_archetypes"):
        if _s(row.get("id")) == topology:
            admitted = as_list(row.get("value"))
            break
    # The drawing stands on ONE archetype; the corpus may admit several for a topology, so the
    # whole list is recorded beside the choice and the view warns when they differ.
    model.el(_root(model), "Grouping", props={"cafe.topology": topology,
                                              "cafe.archetype": admitted[0] if admitted else "",
                                              "cafe.archetypes": "; ".join(admitted),
                                              "cafe.families": "; ".join(as_list(out.get("families"))),
                                              "unbound": "; ".join(as_list(out.get("unbound")))})
    enforcement = out.get("enforcement") or {}
    for fam in as_list(out.get("families")):
        grp = model.el(f"fam-{ids.slug(fam)}", "Grouping", fam, props={"family": fam})
        for g in as_list(enforcement.get(fam)):
            model.rel("Aggregation", grp, model.el(f"con-{ids.slug(g)}", "Constraint", g, props={"guardrail": g}))


def _component_selection(out, model, pool):
    root = _root(model)
    catalogue = _catalogue(pool)
    enforcement = (pool.get("composition") or {}).get("enforcement") or {}
    for c in out.get("selected") or []:
        cid = _s(c.get("component_id"))
        if not cid:
            continue
        row = catalogue.get(cid, {})
        zone, families = _s(row.get("zone")), as_list(row.get("families"))
        ac = model.el(f"ac-{ids.slug(cid)}", "ApplicationComponent", _s(c.get("component")) or _s(row.get("name")) or cid,
                      props={"cafe.component_id": cid, "cafe.zone": zone, "cafe.families": "; ".join(families),
                             "rejected_alternatives": "; ".join(as_list(c.get("rejected_alternatives")))})
        if zone:
            model.rel("Aggregation", model.el(f"zone-{ids.slug(zone)}", "Grouping", zone, props={"cafe.zone": zone}), ac)
        else:
            model.rel("Aggregation", root, ac)
        capability = _s(c.get("capability"))
        if ids.slug(capability):
            model.rel("Assignment", ac, model.el(f"af-{ids.slug(capability)}", "ApplicationFunction", capability))
        for fam in families:
            model.rel("Aggregation", model.el(f"fam-{ids.slug(fam)}", "Grouping", fam, props={"family": fam}), ac)
            for g in as_list(enforcement.get(fam)):
                model.rel("Realization", ac, model.el(f"con-{ids.slug(g)}", "Constraint", g, props={"guardrail": g}))
    for b in out.get("building_blocks") or []:
        what = _s(b.get("what"))
        if ids.slug(what):
            model.rel("Aggregation", root, model.el(f"bb-{ids.slug(what)}", "ApplicationComponent", what,
                                                    props={"owner": _s(b.get("owner")), "kind": "building-block"}))


def _cost_inputs(out, model, pool):
    model.el(_root(model), "Grouping", props={"cost.build_amount": out.get("build_amount"),
                                              "cost.build_provenance": _s(out.get("build_provenance"))})


def _cost(out, model, pool):
    model.el(_root(model), "Grouping", props={
        "cost.monthly_expected": (out.get("monthly") or {}).get("expected"),
        "cost.year_one_expected": (out.get("year_one") or {}).get("expected")})


def _benefit(out, model, pool):
    summary_ = out.get("summary") or {}
    model.el(_root(model), "Grouping", props={"benefit.annual": summary_.get("annual_benefit"),
                                              "benefit.payback_months": summary_.get("payback_months"),
                                              "benefit.verdict": _s((out.get("recommendation") or {}).get("verdict"))})


def _delivery_artifacts(out, model, pool):
    """Services, work and the deliverable. A service is aggregated by the use case and SERVES the
    functions its `consumers` name; which component realises it is not something step 25 says, so
    no realisation is drawn — a fan-out over every selected component would be invented."""
    root = _root(model)
    for sc in out.get("service_contracts") or []:
        name = _s(sc.get("name"))
        if not ids.slug(name):
            continue
        svc = model.el(f"svc-{ids.slug(name)}", "ApplicationService", name,
                       props={"service_level": _s(sc.get("service_level")),
                              "service_level_source": _s(sc.get("service_level_source")),
                              "owned_entities": "; ".join(as_list(sc.get("owned_entities")))})
        model.rel("Aggregation", root, svc)
        for consumer in as_list(sc.get("consumers")):
            if model.has(f"bf-{ids.slug(consumer)}"):
                model.rel("Serving", svc, f"bf-{ids.slug(consumer)}")
    entry = out.get("catalog_entry") or {}
    dlv = None
    if ids.slug(_s(entry.get("name"))):
        dlv = model.el(f"dlv-{ids.slug(_s(entry.get('name')))}", "Deliverable", _s(entry.get("name")),
                       props={"owner": _s(entry.get("owner")), "capability": _s(entry.get("capability"))})
    items = [w for w in out.get("work_items") or [] if ids.slug(_s(w.get("key")))]
    for w in items:
        model.el(f"wp-{ids.slug(_s(w.get('key')))}", "WorkPackage", _s(w.get("title")) or _s(w.get("key")),
                 props={"owner": _s(w.get("owner")), "obligations": "; ".join(as_list(w.get("obligations")))})
    for w in items:
        wp, parent = f"wp-{ids.slug(_s(w.get('key')))}", ids.slug(_s(w.get("parent")))
        if parent and model.has(f"wp-{parent}"):
            model.rel("Aggregation", f"wp-{parent}", wp)
        elif dlv:
            model.rel("Realization", wp, dlv)


#: Step key -> mapper. Adding a step's projection is one entry here and nothing else.
MAPPERS: dict[str, Mapper] = {
    "frame": _frame, "elements": _elements, "coverage_map": _coverage_map,
    "realisation_match": _realisation_match, "criticality_band": _criticality_band,
    "quality_attributes": _quality_attributes, "ontology_delta": _ontology_delta,
    "workflow_graph": _workflow_graph, "source_contracts": _source_contracts,
    "assertions": _assertions, "determinism": _determinism, "facet_vectors": _facet_vectors,
    "risk": _risk, "obligations": _obligations, "build_surface": _build_surface,
    "composition": _composition, "component_selection": _component_selection,
    "cost_inputs": _cost_inputs, "cost": _cost, "benefit": _benefit,
    "delivery_artifacts": _delivery_artifacts,
}

#: Agent steps whose output is EVIDENCE for a governed derivation rather than architecture: the
#: derivation's own output (`benefit`) is what the model carries. Named so the parity test can say
#: which steps are deliberately unmapped instead of any step being silently so.
UNMAPPED = frozenset({"benefit_inputs"})


def apply(step_key: str, out: Any, model: Model, pool: Mapping[str, Any]) -> bool:
    """Run the step's mapper, if there is one. Total: a mapper that raises leaves the model as it
    was before the call and the failure under `dropped`, because a run must not die on its own
    bookkeeping — but it must SAY so."""
    mapper = MAPPERS.get(step_key)
    if mapper is None or not isinstance(out, Mapping):
        return False
    before = model.to_spec()
    try:
        mapper(out, model, pool)
    except Exception as exc:                          # noqa: BLE001 — recorded, never raised
        restored = Model.from_spec(before)
        model.elements, model.relations, model.touched = restored.elements, restored.relations, set()
        model.dropped = list(before["dropped"]) + [{"mapper": step_key, "error": f"{exc!r}"[:200],
                                                     "trace": traceback.format_exc().splitlines()[-1][:200]}]
        return False
    return True


def summary(model: Model, pool: Mapping[str, Any]) -> dict:
    """The projection a later step is SHOWN — id and name per element, grouped by type, plus which
    of the composition's required families a selected component already realises. Never the whole
    model: `agents.message` dumps every context entry in full, and an architect reads a summary,
    not a spec."""
    by_type: dict[str, list[dict]] = {}
    for e in model.elements.values():
        by_type.setdefault(e["type"], []).append({"id": e["id"], "name": e["name"]})
    required = as_list((pool.get("composition") or {}).get("families"))
    realised: dict[str, list[str]] = {f: [] for f in required}
    for a in model.by_type("ApplicationComponent"):
        for fam in as_list((a.get("props") or {}).get("cafe.families")):
            realised.setdefault(fam, []).append(a["id"])
    return {"elements": by_type, "required_families": required, "realised_families": realised,
            "counts": model.counts()}
