"""Published measurements (BRS §3, BR-8) — numbers a person can read, computed from what the fabric already
holds, never from content.

  auto-association ratio   delivery contexts the pipeline established (rung C/X) vs those a person was asked for
  approved without rewrite share of draft reviews approved as drafted (approve vs update/decline)
  impact acknowledged      impact notices acknowledged vs declined
  duplicates               duplicateOf edges per published record
  labelled / owned share   records carrying a sensitivity label / an owner
  unacknowledged changes   impact notices still open — published records whose source moved and nobody looked

Three parts, in the shape every substrate consumer has: `gather` reads (SPARQL through the gateway, the approval
hashes in Redis), `compute` is pure, `render` is the page. `tick` is what the reconciler calls on its cadence:
the numbers go to `fabric:metrics` in Redis (what `semantic_metrics` answers with) and to one wiki page."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from lab.platform.contracts import ApprovalKind, SemanticTools
from lab.platform.fabric_events import METRICS_KEY as KEY
from lab.substrate import approvals, fabric_gateway
from lab.substrate.fabric_projector import write_page

__all__ = ["QUERIES", "KEY", "PAGE", "gather", "compute", "render", "tick"]

PAGE = "fabric-metrics.md"
PREFIX = ("PREFIX fab: <urn:fabric:ont#> PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> "
          "PREFIX prov: <http://www.w3.org/ns/prov#> ")
QUERIES: dict[str, str] = {
    "states": PREFIX + "SELECT ?state (COUNT(DISTINCT ?a) AS ?n) WHERE { ?a a fab:Artifact ; fab:lifecycleState ?state } GROUP BY ?state",
    "owned": PREFIX + "SELECT (COUNT(DISTINCT ?a) AS ?n) WHERE { ?a a fab:Artifact ; fab:ownedBy ?o }",
    "labelled": PREFIX + "SELECT (COUNT(DISTINCT ?a) AS ?n) WHERE { ?a a fab:Artifact ; fab:sensitivityLabel ?l }",
    "delivery": PREFIX + ("SELECT ?rung (COUNT(?aid) AS ?n) WHERE { ?aid a fab:Assertion ; fab:asserts ?st ; fab:rung ?rung . "
                          "?st rdf:predicate fab:deliveredUnder . FILTER NOT EXISTS { ?aid prov:wasInvalidatedBy ?x } } GROUP BY ?rung"),
    "duplicates": PREFIX + "SELECT (COUNT(*) AS ?n) WHERE { ?a fab:duplicateOf ?b }",
}


def _n(table: dict, col: str = "n") -> int:
    rows = table.get("rows") or []
    if not rows:
        return 0
    i = (table.get("columns") or [col]).index(col)
    return int(float(rows[0][i] or 0))


def _by(table: dict, key: str) -> dict[str, int]:
    cols = table.get("columns") or []
    ki, ni = cols.index(key), cols.index("n")
    return {str(r[ki]).rsplit("#", 1)[-1].rsplit(":", 1)[-1]: int(float(r[ni] or 0)) for r in table.get("rows") or []}


async def gather(*, call=None, client) -> dict:
    """The raw facts: one SPARQL table per query (through the gateway, READ) and the decided approvals by kind
    (the hashes this substrate already reaches). Counts only."""
    go = call or fabric_gateway.call
    tables = dict(zip(QUERIES, await go([(SemanticTools.query, {"sparql": q}) for q in QUERIES.values()])))
    decisions = approvals.decision_counts((ApprovalKind.DRAFT_REVIEW, ApprovalKind.ASSOCIATION, ApprovalKind.IMPACT_NOTICE),
                                          client=client)
    return {"tables": tables, "decisions": decisions}


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def compute(facts: dict) -> dict:
    """PURE. Every number with its numerator and denominator beside it, so a reader can weigh it."""
    t, d = facts.get("tables") or {}, facts.get("decisions") or {}
    states = _by(t.get("states") or {"columns": ["state", "n"], "rows": []}, "state")
    total, published = sum(states.values()), states.get("published", 0)
    delivery = _by(t.get("delivery") or {"columns": ["rung", "n"], "rows": []}, "rung")
    # established by the pipeline = looked up (C), found in content (X) or DERIVED by a rule (D); asked = H
    derived = delivery.get("D", 0)
    auto, asked = delivery.get("C", 0) + delivery.get("X", 0) + derived, delivery.get("H", 0)
    review = d.get(ApprovalKind.DRAFT_REVIEW, {})
    # approved AS DRAFTED: a final approve with no update/decline before it (the audit log, not the last status)
    approved, reworked = review.get("approve", 0) - review.get("reworked", 0), review.get("reworked", 0)
    notice = d.get(ApprovalKind.IMPACT_NOTICE, {})
    dup = _n(t.get("duplicates") or {})
    return {
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "records": {"total": total, **states},
        "auto_association_ratio": {"value": _ratio(auto, auto + asked), "auto": auto, "asked": asked, "derived": derived},
        "approved_without_rewrite": {"value": _ratio(approved, approved + reworked), "approved": approved, "reworked": reworked,
                                     "open": review.get("pending", 0)},
        "impact_acknowledged": {"value": _ratio(notice.get("approve", 0), notice.get("approve", 0) + notice.get("decline", 0)),
                                "acknowledged": notice.get("approve", 0), "declined": notice.get("decline", 0),
                                "unacknowledged_changes": notice.get("pending", 0)},
        "duplicate_rate": {"value": _ratio(dup, published), "duplicates": dup, "published": published},
        "labelled_share": {"value": _ratio(_n(t.get("labelled") or {}), total), "labelled": _n(t.get("labelled") or {}), "total": total},
        "owned_share": {"value": _ratio(_n(t.get("owned") or {}), total), "owned": _n(t.get("owned") or {}), "total": total},
    }


def _pct(m: dict) -> str:
    return "n/a" if m.get("value") is None else f"{m['value'] * 100:.0f} %"


def render(m: dict) -> str:
    r = m["records"]
    return "\n".join([
        "---", "title: Documentation Fabric — measurements", f"computed: {m['computed_at']}", "---", "",
        "# Documentation Fabric — measurements", "",
        f"*Computed {m['computed_at']} from the catalog, the graph and the review gate. Numbers, never content.*", "",
        "| Measure | Value | Basis |", "|---|---|---|",
        f"| Records | {r['total']} | " + ", ".join(f"{k} {v}" for k, v in r.items() if k != "total") + " |",
        f"| Auto-association ratio | {_pct(m['auto_association_ratio'])} | {m['auto_association_ratio']['auto']} established by the pipeline ({m['auto_association_ratio']['derived']} of them derived), {m['auto_association_ratio']['asked']} asked of a person |",
        f"| Drafts approved without rewrite | {_pct(m['approved_without_rewrite'])} | {m['approved_without_rewrite']['approved']} approved, {m['approved_without_rewrite']['reworked']} sent back or declined, {m['approved_without_rewrite']['open']} open |",
        f"| Impact notices acknowledged | {_pct(m['impact_acknowledged'])} | {m['impact_acknowledged']['acknowledged']} acknowledged, {m['impact_acknowledged']['declined']} declined, {m['impact_acknowledged']['unacknowledged_changes']} unacknowledged changes |",
        f"| Duplicate rate | {_pct(m['duplicate_rate'])} | {m['duplicate_rate']['duplicates']} duplicates over {m['duplicate_rate']['published']} published |",
        f"| Labelled | {_pct(m['labelled_share'])} | {m['labelled_share']['labelled']} of {m['labelled_share']['total']} |",
        f"| Owned | {_pct(m['owned_share'])} | {m['owned_share']['owned']} of {m['owned_share']['total']} |", "",
    ])


async def tick(*, folder: str, client, call=None) -> dict:
    """Compute, remember (`fabric:metrics`), and publish the page. Returns the metrics."""
    go = call or fabric_gateway.call
    m = compute(await gather(call=go, client=client))
    client.set(KEY, json.dumps(m))
    await write_page(PAGE, render(m), folder=folder, call=go, client=client)     # loop-guarded like every fabric write
    return m
