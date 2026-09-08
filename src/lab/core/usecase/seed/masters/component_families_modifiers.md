# Component families — modifiers

**Artifact:** component_families
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py
**Section:** modifiers

| Modifier | Values | What it varies |
|---|---|---|
| Trigger | interactive · event · scheduled | F6 identity shape — user-delegated where an interactive user is present at trigger time, a first-class agent identity otherwise. Also whether F9 liveness applies |
| Human position | in-loop · on-loop · out-of-loop | F5 shape — per-action approval, a policy-bounded gate with exception review, or no gate. Out-of-loop is available only where the commit invariant is satisfied by upstream determinism |
| Criticality | routine · business-critical · safety-of-life | Depth of F8, F9 and F10, the corroboration requirement in F1, and the approval path. Assigned at M0 Gate D and never re-derived here |
