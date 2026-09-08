# Step facet schema

**Artifact:** facet_schema
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py
**Section:** facets

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
