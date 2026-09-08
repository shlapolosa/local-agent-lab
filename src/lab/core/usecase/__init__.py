"""The CAFÉ domain — pure, no I/O.

Imported by BOTH the substrate MCP servers that expose the deterministic derivations and the
workload gates that validate agent output, which is why it lives in `lab.core`: workloads may never
import `lab.substrate`, so this is the only tier both can reach. Putting the arithmetic anywhere
else means implementing it twice.

The seven deterministic algorithms, by the step they serve:
    gates.readiness_verdict      14   the four M0 gates
    gates.feasibility_verdict    16   proceed / reject / integration
    exposure.derive              18   exposure and influence per step
    obligations.derive           19   the control requirement set
    composition.compose          22   topology, families, enforcement points
    cost.cost_model              23   the itemised model and the Year-1 total
    benefit.financial_summary    24   the three drivers, the ROI and the recommendation
"""
from lab.core.usecase import (
    benefit,
    composition,
    cost,
    exposure,
    gates,
    model,
    obligations,
    predicates,
    seed,
)

__all__ = ["benefit", "composition", "cost", "exposure", "gates", "model", "obligations",
           "predicates", "seed"]
