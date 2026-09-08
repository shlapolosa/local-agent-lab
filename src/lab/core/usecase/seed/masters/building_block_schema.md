# EA building block schema

**Artifact:** building_block_schema
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py

| Field | What it records | Why it is required |
|---|---|---|
| Type label | The abstract type — incident management system, ERP, master data store | Portability. No product names |
| Owns | What this block is authoritative for — the system of record for X, the workflow engine for Y | Application boundaries follow data ownership; this is the strongest boundary heuristic available |
| Workflow steps owned | Which steps of the graph this block executes rather than the AI estate | Determines the topology at Stage 4 — a block owning most steps means T3 |
| Interface | How it is reached — API, event, file, human | Determines the integration components in the composition |
| Data classes exchanged | What crosses the boundary, in each direction, with sensitivity | Triggers G21 egress control and the retrieval contract |
| Failure semantics | at-most-once · at-least-once with idempotency key · saga with compensation | G23 presumes an answer to this. Without it, an irreversible effect has no reversal path and no confirmation |
| Who operates it | The team accountable for its availability and change | An obligation resolving here needs a named owner or it is unowned |
| Obligations resolved here | Which guardrail obligations this block discharges | The Stage 5 exit gate reads this |
