# Risk classes and derivation

**Artifact:** risk_derivation
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py

|  | Exposure | Influence |
|---|---|---|
| Question | How bad is it when this step works? | How bad is it when this step is wrong? |
| Derived from | Effect class, reversibility, blast radius | The effects this step determines downstream via data flow, attenuated at qualifying gates |
| Typical high scorer | A commit step — an irreversible write, an external communication | An interpretive step with effect none , whose output selects a branch |
| Control family | Authorisation gates, reversibility limits, blast-radius caps, tool scoping | Evaluation with recall targets, corroboration, confidence-triggered escalation, outcome assertions |
| Failure it addresses | The step does the wrong thing | The step decides the wrong thing, including deciding that nothing need happen |

# Risk classes and derivation — classes

| Class | Exposure — how bad when the step works | Influence — how bad when the step is wrong |
|---|---|---|
| 0 — none | Effect class is none or advisory. Changes nothing outside the workflow | Determines nothing downstream, or only class-0 effects |
| 1 — contained | Reversible, affecting a single record or a single subject | Determines a class-1 effect, unattenuated |
| 2 — significant | Irreversible, or affecting a cohort, or an external communication | Determines a class-2 effect, unattenuated |
| 3 — severe | Financial or contractual commitment, physical or clinical action, or irreversible at population scale | Determines a class-3 effect, unattenuated |

# Risk classes and derivation — moves

| Move | Rule |
|---|---|
| 1 · Base from effect class | none → 0 · advisory → 0 · record write → 1 · external communication → 2 · financial or contractual commitment → 3 · physical or clinical action → 3 |
| 2 · Modifiers | Irreversible +1 . Blast radius of a cohort +1 , of the whole population +2 — taking the higher of the instance and systematic readings. Audience of public or regulator +1 |
| 3 · Domain floor | Clinical or safety: not below 2 . Financial or HR: not below 1 . Domain raises a floor; it never adds a class on top of one |
| 4 · Cap | Class 3 is the ceiling. There is no class 4, and a step that saturates is not thereby worse than another that saturates |
