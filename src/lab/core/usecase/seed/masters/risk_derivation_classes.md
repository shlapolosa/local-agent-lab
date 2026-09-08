# Risk classes and derivation — classes

**Artifact:** risk_derivation
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py
**Section:** classes

| Class | Exposure — how bad when the step works | Influence — how bad when the step is wrong |
|---|---|---|
| 0 — none | Effect class is none or advisory. Changes nothing outside the workflow | Determines nothing downstream, or only class-0 effects |
| 1 — contained | Reversible, affecting a single record or a single subject | Determines a class-1 effect, unattenuated |
| 2 — significant | Irreversible, or affecting a cohort, or an external communication | Determines a class-2 effect, unattenuated |
| 3 — severe | Financial or contractual commitment, physical or clinical action, or irreversible at population scale | Determines a class-3 effect, unattenuated |
