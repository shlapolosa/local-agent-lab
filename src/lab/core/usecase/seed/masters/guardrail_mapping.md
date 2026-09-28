# Risk class to guardrail mapping

**Artifact:** guardrail_mapping
**Source:** cafe-artifacts.xlsx
**Rendered:** imported from the source above by scripts/artifacts_workbook.py

| Class | Mandatory, in addition to the baseline |
|---|---|
| Baseline every step, every class | G01 prompt and registry integrity · G03 first-class agent identity · G04 component admission · G10 registration, named owner and evaluation gate · G14 inventory completeness · G15 ontology conformance · G06 wherever the step retrieves · G28 governed entry point wherever the step is interactive · G29 residency-gated routing on every model call |
| E1 — contained | G02 tool scoping to a minimal action set · G08 step, tool-call and per-source budgets |
| E2 — significant | All of E1 · G09 human confirmation, or a policy-bounded gate whose policy is D0-evaluable · G17 where the step consumes grounding that can go stale · G09 approver holds a current, role-specific authorisation |
| E3 — severe | All of E2 · G09 as per-action human authorisation — a policy-bounded gate is not sufficient at this class · G16 criticality-proportionate rigor · corroborated grounding across independent sources |
| I1 — contained | An evaluation harness with a stated accuracy target on the step |
| I2 — significant | All of I1 · G18 recall target on the branch the step can suppress, and a confidence threshold below which it escalates to a human |
| I3 — severe | All of I2 · G19 at least one outcome assertion for the workflow, monitored independently of the steps producing the outcome · corroboration where the step reconciles across sources |
| Domain floor — clinical or health data | G29 personal or health content to in-region or sovereign model lanes only; out-of-region only after block or redact · G26 retention and explainability · exposure not below 2 |
| Estate level — not step-derived | G14 inventory completeness · G27 one home domain · G28 governed entry for people and received agents · G30 access follows the HR lifecycle · G31 received agents admitted before enablement · G32 model provenance — evaluated at registration (Stage 7) and as standing estate checks, not from facet vectors |
