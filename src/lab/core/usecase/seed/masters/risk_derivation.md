# Risk classes and derivation

**Artifact:** risk_derivation
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py
**Section:** properties

|  | Exposure | Influence |
|---|---|---|
| Question | How bad is it when this step works? | How bad is it when this step is wrong? |
| Derived from | Effect class, reversibility, blast radius | The effects this step determines downstream via data flow, attenuated at qualifying gates |
| Typical high scorer | A commit step — an irreversible write, an external communication | An interpretive step with effect none , whose output selects a branch |
| Control family | Authorisation gates, reversibility limits, blast-radius caps, tool scoping | Evaluation with recall targets, corroboration, confidence-triggered escalation, outcome assertions |
| Failure it addresses | The step does the wrong thing | The step decides the wrong thing, including deciding that nothing need happen |
