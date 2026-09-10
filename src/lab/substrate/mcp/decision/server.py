"""decision-mcp — the deterministic CAFÉ derivations, as governed tools.

Deployed rather than run inside the workload, for the reason the framework gives: these read
governed artifacts that change under governance approval, so a change to the criticality taxonomy
or the guardrail set must not require an application release. Conformance review evaluates the same
predicates against the same facet vectors, so one service is also what stops two implementations of
one rule set quietly drifting apart.

**Where the rules come from, and why it is said out loud in every answer.** NFR-15 requires them to
be read as configuration at call time, never compiled in. Pass a `pin_id` and they are read from the
governed corpus at the versions that pin froze; omit it and the local seed answers. Both are honest
readings-at-call-time, but they are not equally authoritative — so every response carries
`rules_source`, and a design package can show which one it obeyed. A silent fallback would make an
ungoverned answer indistinguishable from a governed one, which is the failure this whole layer is
built to prevent.

The derivations themselves are `lab.core.usecase` — pure, offline, and shared with the workload
gates, because a workload may never import the substrate and the arithmetic must not exist twice.
"""
from __future__ import annotations

from typing import Any

from fastmcp.exceptions import ToolError

from lab.core.reference import cells
from lab.core.reference.errors import ReferenceError
from lab.core.reference.model import RunRef
from lab.core.usecase import composition, exposure, gates, obligations
from lab.core.usecase.model import Step, Workflow
from lab.core.usecase.predicates import PredicateError
from lab.platform import config
from lab.substrate.mcpserver import LabServer, span

SERVICE = "decision-mcp"
server = LabServer(SERVICE, config.DECISION_MCP_PORT)

#: Which corpus artifact answers which derivation, and by which record type. The server reads only
#: what the derivation it was asked for needs — a pin over the whole corpus is available, but a
#: lookup of everything would put unrelated versions in a run's consumption trail.
RULES = {
    "guardrails": ("guardrails", "guardrail"),
    "guardrail_mapping": ("guardrail-mapping", "risk-class"),
    "family_triggers": ("family-triggers", "family"),
}


def _workflow(payload: dict) -> Workflow:
    """The step facet vectors as typed objects. A malformed vector fails HERE, naming the step and
    the facet, rather than silently failing to match a predicate two derivations later."""
    steps = payload.get("steps") or []
    if not steps:
        raise ToolError("a derivation needs at least one step; `steps` was empty")
    try:
        return Workflow(steps=tuple(Step(**s) for s in steps),
                        criticality=payload.get("criticality", "routine"))
    except (TypeError, ValueError) as exc:
        raise ToolError(f"the workflow is not a valid facet vector set: {exc}") from exc


def _rules(pin_id: str, run_id: str, process: str, field: str,
           needs: tuple[str, ...] = ()) -> tuple[dict, dict]:
    """(rules, provenance). Empty rules mean "use the local seed", said plainly in the provenance."""
    if not pin_id:
        return {}, {"kind": "local seed",
                    "note": "the packaged copy of the published artifacts; pass a pin_id from "
                            "reference_pin to derive against the governed corpus instead"}
    library = server.reference()
    try:
        pin = library.pin_by_id(pin_id)
        run = RunRef(run_id=run_id, process=process, field=field)
        found: dict[str, Any] = {}
        pinned = {v.artifact_id for v in pin.versions}
        for key, (artifact_id, record_type) in RULES.items():
            if artifact_id not in pinned:
                # Only what THIS derivation reads is required. Obligations do not read the family
                # triggers and composition does not read the guardrail mapping, so demanding the
                # whole RULES table would refuse runs over a pin that carried everything they
                # actually use.
                if key not in needs:
                    continue
                # REFUSE, rather than falling through to the packaged seed for this one artifact.
                # A per-artifact fallback is exactly the failure this module's docstring names: it
                # would answer from the seed while the response still said "governed corpus", and
                # nothing downstream could tell. Reachable in practice — a partial release leaves a
                # ring holding some artifacts and not others.
                raise ToolError(
                    f"the pin does not carry {artifact_id!r}, which this derivation reads. A "
                    f"control set derived without it would be silently short, and the answer would "
                    f"still claim the governed corpus. Re-pin once {artifact_id!r} is released to "
                    f"this ring.")
            # BY ARTIFACT, not by record type alone: a type is a classification and two artifacts
            # may publish the same one honestly — `family-triggers` and `component-families` both
            # publish `family`. Keyed on type alone this returned both, interleaved, and the
            # derivation indexed a column the other artifact does not have.
            result = library.lookup(pin, artifact_id=artifact_id, record_type=record_type,
                                    key={}, run=run, limit=500)
            found[key] = cells.rows(result.records)
        return found, {"kind": "governed corpus", "pin_id": pin.pin_id,
                       "versions": [{"artifact_id": v.artifact_id, "version": v.version}
                                    for v in pin.versions]}
    except ReferenceError as exc:
        raise ToolError(exc.sentence) from exc
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@server.tool()
def decision_readiness(gates_evidenced: dict, criticality: str = "routine",
                       conditions: dict | None = None) -> dict:
    """Step 14 — the readiness verdict over the four M0 gates.

    `gates_evidenced` maps each of A, B, C, D to true, false, or "partial". A partial B or C may be
    carried as a CONDITION with a named owner and a dated closure, and never for a safety-of-life
    class. Returns pass, conditional or fail, naming every gate that failed."""
    try:
        out = gates.readiness_verdict(gates_evidenced, criticality=criticality,
                                      conditions=conditions or {})
    except gates.GateError as exc:
        raise ToolError(str(exc)) from exc
    span().set_attribute("decision.readiness.failed", len(out.failed))
    return {"verdict": str(out.verdict), "failed": list(out.failed),
            "conditions": {k: dict(v) for k, v in out.conditions.items()}}


@server.tool()
def decision_feasibility(capability_matched: bool, existing_realisation: bool,
                         capability_is_commodity: bool, capability_is_mature: bool,
                         capability_meets_target: bool) -> dict:
    """Step 16 — the feasibility verdict, over derived evidence rather than an estimate.

    Rules in order, first to fire decides: no capability match rejects; an existing realisation
    returns the use case as an INTEGRATION; a capability that is commodity, mature and meeting
    target rejects; otherwise proceed. `halts` is true for anything but proceed — steps 17 to 25
    must not be attempted and no partial design package produced."""
    out = gates.feasibility_verdict(
        capability_matched=capability_matched, existing_realisation=existing_realisation,
        capability_is_commodity=capability_is_commodity, capability_is_mature=capability_is_mature,
        capability_meets_target=capability_meets_target)
    span().set_attribute("decision.feasibility.halts", out.halts)
    return {"verdict": str(out.verdict), "rule": out.rule, "halts": out.halts}


@server.tool()
def decision_exposure(workflow: dict) -> dict:
    """Step 18 — exposure and influence per step.

    Exposure is how bad it is when the step WORKS, scored from its own effect, reversibility, blast
    radius and audience. Influence is how bad it is when it is WRONG: read, not scored — the walk
    goes forward to every effect the step determines, attenuated at gates. A step with effect
    `none` can carry influence 3, which is the case a single score would miss entirely."""
    wf = _workflow(workflow)
    derived = exposure.derive(wf)
    span().set_attributes({"decision.steps": len(wf),
                           "decision.max_influence": max((d["influence"] for d in derived.values()),
                                                         default=0)})
    return {"steps": derived,
            "max_exposure": max((d["exposure"] for d in derived.values()), default=0),
            "max_influence": max((d["influence"] for d in derived.values()), default=0)}


@server.tool()
def decision_obligations(workflow: dict, conditions: dict | None = None, pin_id: str = "",
                         run_id: str = "", process: str = "", field: str = "") -> dict:
    """Step 19 — the control requirement set, and the commit invariant.

    Three sources, and a set missing any one would still look complete: every guardrail predicate
    evaluated against every step's facet vector, whatever the exposure and influence classes mandate
    regardless of any predicate, and the workflow-level commit invariant.

    `conditions` answers the prose terms a facet vector cannot — "step invokes any registered tool",
    "the step reasons over or emits a named concept". An unanswered one REFUSES rather than reading
    false: a guardrail that quietly fails to fire is invisible, and the run would complete with a
    control set that is silently short."""
    wf = _workflow(workflow)
    rules, provenance = _rules(pin_id, run_id, process, field,
                               needs=("guardrails", "guardrail_mapping"))
    try:
        out = obligations.derive(wf, conditions=conditions or {},
                                 guardrails=rules.get("guardrails"),
                                 mapping_rows=rules.get("guardrail_mapping"))
    except (obligations.ObligationError, PredicateError) as exc:
        raise ToolError(str(exc)) from exc
    span().set_attributes({"decision.obligations": len(out.guardrails()),
                           "decision.commit_invariant_holds": out.commit_invariant_holds})
    return {
        "by_step": {step: [{"guardrail": o.guardrail, "text": o.text, "source": o.source}
                           for o in items] for step, items in out.by_step.items()},
        "guardrails": sorted(out.guardrails()),
        "commit_invariant_holds": out.commit_invariant_holds,
        "violations": [{"step": v.step, "reason": v.reason} for v in out.violations],
        "rules_source": provenance,
    }


@server.tool()
def decision_composition(workflow: dict, topology: str, conditions: dict | None = None,
                         grounding_sources: int = 0, obligations_required: list[str] | None = None,
                         pin_id: str = "", run_id: str = "", process: str = "",
                         field: str = "") -> dict:
    """Step 22 — compose the architecture from the derived evidence.

    The family set is the UNION over every step's facet vector, so absence is as much a result as
    presence: a composition carrying a family no step calls for is over-built. `unbound` names any
    obligation that resolved to no enforcement point — Q5.3 makes that a STOP, and it can only stop
    if somebody is told."""
    wf = _workflow(workflow)
    rules, provenance = _rules(pin_id, run_id, process, field, needs=("family_triggers",))
    try:
        out = composition.compose(wf, topology=topology, conditions=conditions or {},
                                  grounding_sources=grounding_sources,
                                  obligations=obligations_required or (),
                                  families=rules.get("family_triggers"))
    except (composition.CompositionError, PredicateError) as exc:
        raise ToolError(str(exc)) from exc
    span().set_attributes({"decision.families": len(out.families),
                           "decision.unbound": len(out.unbound)})
    return {"topology": out.topology, "families": sorted(out.families),
            "variants": dict(out.variants), "modifiers": dict(out.modifiers),
            "enforcement": {k: list(v) for k, v in out.enforcement.items()},
            "unbound": sorted(out.unbound),
            "connectors": [list(c) for c in out.connectors],
            "rules_source": provenance}


if __name__ == "__main__":
    server.serve()
