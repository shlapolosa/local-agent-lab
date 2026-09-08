# Determinism criteria register

**Artifact:** determinism_criteria
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py

| # | Criterion | Test | Tier | Reducible |
|---|---|---|---|---|
| 1 | Unbounded input space | Input is free text, an image or an arbitrary document; the domain cannot be enumerated | D1 | No |
| 2 | Unbounded output space | Output is generated rather than selected — draft, summarise, explain | D1–D2 | No |
| 3 | No stable ground truth | Two qualified experts, same input, defensibly disagree — tone, priority, whether something is urgent | D1–D2 | No |
| 4 | Open-world reconciliation | Must act on information that may be missing, stale or contradictory, and decide how to proceed | D2 | No |
| 5 | Combinatorial path space | Selects among many sub-paths where enumeration is impractical. D3 where the plan itself cannot be stated | D2–D3 | No |
| 6 | Tacit rules | A rule exists but lives only in experts' heads; nobody has written it down | D1 → D0 | Yes |
| 7 | Undeclared semantic mapping | Must map an external term to an internal concept the ontology does not define | D1 → D0 | Yes |
