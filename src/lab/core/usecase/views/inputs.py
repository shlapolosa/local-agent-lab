"""Step outputs -> the inputs each CAFÉ view draws from. Pure: the pipeline's own judgement about what a
reviewer sees, tested on the shapes the steps emit. Rendering them through the governed tools is the
workload's (`lab.workloads.usecase.views`)."""
from __future__ import annotations

from typing import Any, Mapping

from lab.core.archimate import ids

__all__ = ["RANK", "UNSTATED", "capability_input", "ontology_input", "realisation_input", "workflow_spec"]


#: When several functions exercise one capability, the block shows the status that matters most: a
#: gap first, then what the solution introduces, then what it changes, then what it only reuses.
RANK = ("missing", "new", "updated", "consumed")


#: A matched capability with no status: step 5 found it NEEDED and nothing said it already exists.
UNSTATED = "new"


def _rows(out: Mapping[str, Any] | None, key: str) -> list[dict]:
    return [dict(r) for r in (out or {}).get(key) or [] if isinstance(r, Mapping)]


def capability_input(coverage: Mapping[str, Any] | None) -> list[dict]:
    """Step 5 -> one block per matched L3: its strongest status, and the functions it serves."""
    by_cap: dict[str, dict] = {}
    for m in _rows(coverage, "matched"):
        cid = str(m.get("capability_id") or "").strip()
        if not cid:
            continue
        status = str(m.get("status") or UNSTATED)
        entry = by_cap.setdefault(cid, {"id": cid, "status": status, "functions": []})
        if RANK.index(status if status in RANK else UNSTATED) < RANK.index(entry["status"]):
            entry["status"] = status
        if m.get("function") and m["function"] not in entry["functions"]:
            entry["functions"].append(m["function"])
    return [{"id": e["id"], "status": e["status"], "note": ", ".join(e["functions"])[:120]}
            for e in by_cap.values()]


def realisation_input(coverage: Mapping[str, Any] | None,
                      realisation: Mapping[str, Any] | None) -> list[dict]:
    """Steps 5 and 6 -> the preferred route of every matched capability. A capability step 6
    shortlisted nothing for is drawn MISSING: a realisation gap, which is what the view is for."""
    preferred = {str(s.get("capability_id")): s for s in _rows(realisation, "shortlist")
                 if s.get("preferred")}
    out = []
    for cap in capability_input(coverage):
        pick = preferred.get(cap["id"])
        if pick:
            out.append({"id": cap["id"], "status": cap["status"], "route": pick.get("route", ""),
                        "product": pick.get("realisation", "")})
        else:
            out.append({"id": cap["id"], "status": "missing", "note": "no realisation shortlisted"})
    return out


def ontology_input(delta: Mapping[str, Any] | None) -> dict:
    """Step 9 -> concepts by ontology id; a gap by its object name, which is what the step's own
    relationships call it."""
    concepts = []
    for c in _rows(delta, "concepts"):
        gap = c.get("status") == "gap"
        entry = {"id": str(c.get("object") if gap else c.get("id") or c.get("object")),
                 "status": c.get("status", "")}
        for key in ("note",) + (("name", "module", "kind", "definition") if gap else ()):
            if c.get(key):
                entry[key] = c[key]
        concepts.append(entry)
    return {"concepts": concepts, "relationships": _rows(delta, "relationships")}


def workflow_spec(graph: Mapping[str, Any] | None, coverage: Mapping[str, Any] | None,
                  *, title: str = "") -> dict | None:
    """Step 10's graph -> a BPMN spec: a lane per performer (in order of first appearance), a task
    per node labelled with the L3 its function exercises (step 5's match), a start event wherever
    nothing leads in and an end wherever nothing leads out. None for a graph with no nodes — a
    start joined straight to an end would draw a process that does nothing."""
    nodes, edges = _rows(graph, "nodes"), _rows(graph, "edges")
    if not nodes:
        return None
    cap_of: dict[str, str] = {}
    for m in _rows(coverage, "matched"):
        cap_of.setdefault(str(m.get("function")), str(m.get("capability_id") or ""))
    lanes: dict[str, str] = {}
    spec_nodes = []
    for n in nodes:
        who = str(n.get("performed_by") or "Unassigned")
        lane = lanes.setdefault(who, ids.slug(who) or f"lane{len(lanes)}")
        task = {"id": str(n["id"]), "type": "task", "lane": lane, "name": str(n.get("activity") or n["id"])}
        if cap_of.get(str(n.get("function"))):
            task["cap"] = cap_of[str(n.get("function"))]
        spec_nodes.append(task)
    lane_of = {t["id"]: t["lane"] for t in spec_nodes}
    spec_edges = [{"from": str(e["from"]), "to": str(e["to"]), "label": str(e.get("data_class") or "")[:24]}
                  for e in edges if str(e.get("from")) in lane_of and str(e.get("to")) in lane_of]
    leads_in = {e["to"] for e in spec_edges}
    leads_out = {e["from"] for e in spec_edges}
    for t in list(spec_nodes):
        if t["id"] not in leads_in:
            spec_nodes.append({"id": f"start-{t['id']}", "type": "start", "lane": t["lane"]})
            spec_edges.append({"from": f"start-{t['id']}", "to": t["id"]})
        if t["id"] not in leads_out:
            spec_nodes.append({"id": f"end-{t['id']}", "type": "end", "lane": t["lane"]})
            spec_edges.append({"from": t["id"], "to": f"end-{t['id']}"})
    return {"title": title or "Workflow", "lanes": [{"id": v, "label": k} for k, v in lanes.items()],
            "nodes": spec_nodes, "edges": spec_edges}
