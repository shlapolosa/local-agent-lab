# Step facet schema — defaults

**Artifact:** facet_schema
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py
**Section:** defaults

| Activity | Determinism | Effect class | Reversibility | Blast radius | Audience | Authorisation |
|---|---|---|---|---|---|---|
| retrieve | D0 | none | reversible | single record | internal individual | autonomous |
| interpret | D1 | none | reversible | single subject | internal individual | autonomous |
| decide | D0 | none | reversible | single subject | internal individual | autonomous |
| transform | D1 | advisory | reversible | single subject | internal individual | autonomous |
| commit | D0 | record write | reversible | single record | internal group | policy-bounded |
| notify | D0 | external communication | irreversible | single subject | customer | per-action human |
| orchestrate | D2 | none | reversible | cohort | internal group | policy-bounded |
