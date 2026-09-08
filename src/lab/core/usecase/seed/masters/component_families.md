# Component families

**Artifact:** component_families
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py

|  | Family | Present when any step… | Guardrails |
|---|---|---|---|
| F1 | Grounding and retrieval | reads a grounding source — federated variant where sources exceed one | G06, G13 |
| F2 | Inference | is D1 or above | G01, G22 |
| F3 | Semantic binding | reasons over or emits a named concept | G15 |
| F4 | Action and transaction | has an effect class of record write or above | G02, G23 |
| F5 | Authorisation and approval | commits with an authorisation other than autonomous | G09 |
| F6 | Identity and access | always — shape varies with the trigger modifier | G03 |
| F7 | Control plane and inventory | always | G10, G14 |
| F8 | Evaluation | always — sized by the highest influence class present | G10, G18 |
| F9 | Observation and assurance | carries influence 2+, or consumes grounding that can go stale | G17, G19 |
| F10 | Evidence and retention | has any effect, or operates in a regulated domain | G09, G26 |
| F11 | Content inspection | reads content the enterprise did not author | G20 |
| F12 | Egress control | emits externally, or reads confidential or restricted data | G21, G25 |
| F13 | Release and rate control | has a blast radius of cohort or population | G24 |
| F14 | Delegation | only in T4 | G07 |

# Component families — modifiers

| Modifier | Values | What it varies |
|---|---|---|
| Trigger | interactive · event · scheduled | F6 identity shape — user-delegated where an interactive user is present at trigger time, a first-class agent identity otherwise. Also whether F9 liveness applies |
| Human position | in-loop · on-loop · out-of-loop | F5 shape — per-action approval, a policy-bounded gate with exception review, or no gate. Out-of-loop is available only where the commit invariant is satisfied by upstream determinism |
| Criticality | routine · business-critical · safety-of-life | Depth of F8, F9 and F10, the corroboration requirement in F1, and the approval path. Assigned at M0 Gate D and never re-derived here |
