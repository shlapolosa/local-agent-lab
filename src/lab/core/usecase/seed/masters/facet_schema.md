# Step facet schema

**Artifact:** facet_schema
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py

| Facet | Values | What it governs |
|---|---|---|
| Activity | retrieve · interpret · decide · transform · commit · notify · orchestrate | The verb. Supplies the default for every other facet |
| Determinism tier | D0 · D1 · D2 · D3 | Testing strategy, escalation threshold, agentic screen |
| Input data class | sensitivity (public · internal · confidential · restricted/regulated) × trust (authoritative · corroborated · single-source unverified · external untrusted) × freshness (static · periodic · dynamic · time-critical) | Retrieval contract requirements; corroboration; G06 and G17 |
| Effect class | none · advisory · record write · external communication · financial or contractual commitment · physical or clinical action | Whether the step is a commit step. Drives most guardrail predicates |
| Reversibility | reversible · reversible with cost · irreversible | Exposure, with blast radius |
| Blast radius | single record · single subject · a cohort · the whole population. Read twice — see below | Exposure and influence |
| Audience | internal individual · internal group · partner · customer · public · regulator | Disclosure and communication guardrails |
| Authorisation | per-action human · policy-bounded · autonomous | The commit invariant. Policy-bounded counts only where the policy is D0-evaluable |
| Domain | clinical · financial · HR · safety · general | Raises floors under a regulatory regime. Not a source of exposure in itself |

# Step facet schema — defaults

| Activity | Determinism | Effect class | Reversibility | Blast radius | Audience | Authorisation |
|---|---|---|---|---|---|---|
| retrieve | D0 | none | reversible | single record | internal individual | autonomous |
| interpret | D1 | none | reversible | single subject | internal individual | autonomous |
| decide | D0 | none | reversible | single subject | internal individual | autonomous |
| transform | D1 | advisory | reversible | single subject | internal individual | autonomous |
| commit | D0 | record write | reversible | single record | internal group | policy-bounded |
| notify | D0 | external communication | irreversible | single subject | customer | per-action human |
| orchestrate | D2 | none | reversible | cohort | internal group | policy-bounded |

# Step facet schema — readers

| Facet | Read by | Before v0.25 |
|---|---|---|
| Activity | G02, G06, G07, G15 | Covered |
| Determinism tier | G08, G22 | Partly — nothing validated the bounded-output claim that defines D1 |
| Input sensitivity | G21 | Not read — G06 trimmed permissions on the way in; nothing checked the way out |
| Input trust | G13, G20 | Partly — G12 too narrow to fire outside its original domain |
| Input freshness | G17 | Covered, by two duplicate invariants |
| Effect class | G09, G23 | Covered |
| Reversibility | G23 | Not read |
| Blast radius | G24 | Not read — collected since v0.7, again in v0.11 for the systematic reading |
| Audience | G21, G25 | Not read |
| Authorisation | G03, G09 | Covered |
| Domain | G26 , and G16 via criticality | Not read directly |
| Derived exposure | G13 | Covered |
| Derived influence | G18, G19 | Covered |
