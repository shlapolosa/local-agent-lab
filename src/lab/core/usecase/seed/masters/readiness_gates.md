# Readiness gates

**Artifact:** readiness_gates
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py

| Gate | Question | Evidence | Phase |
|---|---|---|---|
| A — Business grounding | Which capability does this serve, and which measure moves? Plus the workflow as an explicit graph, and the outcome assertions where influence is present. | Capability map entry; AI candidate list; KPI tree link; workflow graph; outcome assertions | 1 |
| B — Semantic readiness | Do the concepts exist in the ontology with relationships, rules and data bindings? Are conflicts resolved and logged? | Ontology extract; vocabulary register; data bindings; conflict log | 2 |
| C — Knowledge readiness | Is every grounding source classified for sensitivity, permission scope and freshness, under a declared retrieval contract? | Grounding source registry; retrieval contract; permission propagation map | 3 |
| D — Criticality class | What is the dominant failure mode? Where the workflow determines the class of each instance, the class is assigned per branch and the pre-triage split is a named gate output. | Criticality classification; risk register links; branch definition | 0 |

# Readiness gates — verdicts

| Verdict | Condition | Consequence |
|---|---|---|
| PASS | All four gates evidenced | Proceed to M2 Stage 0 |
| CONDITIONAL | Gates A and D evidenced; B or C partial with a named owner and dated closure plan | Proceed, carrying conditions as binding design constraints. Not available for a safety-of-life class. |
| FAIL | Gate B or C unevidenced | Do not proceed. Return to CAM Phase 2 or 3. A fail is not an exception to be approved. |
