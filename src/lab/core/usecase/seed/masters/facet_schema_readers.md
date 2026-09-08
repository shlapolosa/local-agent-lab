# Step facet schema — readers

**Artifact:** facet_schema
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py
**Section:** readers

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
