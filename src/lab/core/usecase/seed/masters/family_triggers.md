# Family triggers

**Artifact:** family_triggers
**Source:** TRANSLATED from component_families.json by hand — not extracted
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py

| id | name | prose | predicate | variant | guardrails | topology |
|---|---|---|---|---|---|---|
| F1 | Grounding and retrieval | reads a grounding source — federated variant where sources exceed one | step reads any grounding source | {"name": "federated", "prose": "where sources exceed one", "unexpressed": "The count of grounding sources is a property of the retrieval contracts from step 11, not of a step's facet vector. The caller supplies it as 'grounding_sources'."} | G06; G13 |  |
| F2 | Inference | is D1 or above | step.determinism ≥ D1 |  | G01; G22 |  |
| F3 | Semantic binding | reasons over or emits a named concept | the step reasons over or emits a named concept |  | G15 |  |
| F4 | Action and transaction | has an effect class of record write or above | step.effect ∈ {record write, external communication, financial or contractual commitment, physical or clinical action} |  | G02; G23 |  |
| F5 | Authorisation and approval | commits with an authorisation other than autonomous | step.activity = commit ∧ step.authorisation ≠ autonomous |  | G09 |  |
| F6 | Identity and access | always — shape varies with the trigger modifier | always |  | G03 |  |
| F7 | Control plane and inventory | always | always |  | G10; G14 |  |
| F8 | Evaluation | always — sized by the highest influence class present | always |  | G10; G18 |  |
| F9 | Observation and assurance | carries influence 2+, or consumes grounding that can go stale | influence ≥ 2 ∨ step.input.freshness ∈ {dynamic, time-critical} |  | G17; G19 |  |
| F10 | Evidence and retention | has any effect, or operates in a regulated domain | step.effect ≠ none ∨ step.domain ∈ {clinical, financial, HR, safety} |  | G09; G26 |  |
| F11 | Content inspection | reads content the enterprise did not author | step reads any grounding source, tool output or agent response — any content the enterprise did not author |  | G20 |  |
| F12 | Egress control | emits externally, or reads confidential or restricted data | step.effect = external communication ∨ input.sensitivity ∈ {confidential, restricted} |  | G21; G25 |  |
| F13 | Release and rate control | has a blast radius of cohort or population | step.blast_radius ∈ {cohort, population} |  | G24 |  |
| F14 | Delegation | only in T4 |  |  | G07 | T4 |
