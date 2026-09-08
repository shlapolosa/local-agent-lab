# Process steps

**Artifact:** process_steps
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py

| Step | Input artifacts | What is decided | Output artifacts |
|---|---|---|---|
| E0.1 Frame the use case Pre-work | — | No decision. Records the problem and names one accountable person | Use case record |
| E0.2 Decompose Pre-work | Use case record | No decision. Separates active, behavioural and passive elements. Sequencing anything here is the error | Element inventory |
| E0.3 Match capabilities Pre-work | Element inventory; business capability map | No decision. A gap means either the map is incomplete or the function is not business work — both are findings, not choices | Capability coverage map |
| E0.4 Match realisations Decision | Element inventory; as-is application architectures, else traditional capability map, else survey | Integration or build? And which confidence level the match carries — lookup, assumption or survey | Realisation match with confidence |
| E0.5 Derive quality attributes Decision | Capability coverage map; existing business service levels; quality attribute form | Change ownership and model placement — the two chosen envelope patterns. The other four are derived | Quality attribute scenarios; envelope values |
| E0.6 Check the ontology Pre-work | Element inventory (passive); ontology | No decision. Conflicts are resolved by the Ontology Council, not by the project | Ontology delta |
| E0.7 Sequence the workflow Pre-work | Element inventory; ontology delta | No decision. Granularity is derived — one step per function per active element, split where determinism, effect or authorisation changes | Workflow graph |
| E0.8 Contract the sources Pre-work | Workflow graph; grounding source classification | No decision. Classification is a property of the source, not of this use case | Retrieval contracts |
| E0.9 Assign criticality Decision | Use case record; criticality taxonomy; risk register | Which class , and whether the population is homogeneous or must split behind a pre-triage router | Criticality assignment |
| E0.10 Declare outcome assertions Pre-work | Workflow graph; criticality assignment | No decision. Assertions restate commitments the business already holds | Outcome assertions |
| Q0.8–Q0.9 Readiness verdict Gate | All of the above; readiness gate definitions | GATE. Pass, conditional or fail. A fail returns the work to CAM Phase 2 or 3 — it is not an exception to approve | Readiness record |
| Q1.1–Q1.5 Classify determinism Gate | Workflow graph; determinism criteria register | GATE at Q1.1: is the graph explicit? Decision at Q1.3: necessity or default, per step. GATE at Q1.5: all D0 exits to automation | Step tier classification; containment record |
| Q2.1–Q2.4 Type the steps Decision | Step tier classification; facet schema and risk derivations | Facet overrides only. Defaults come from the activity verb; every override needs written justification and is logged | Facet vectors |
| Q3.1–Q3.4 Derive obligations Gate | Facet vectors; guardrail set; risk class mapping; criticality assignment | No discretion. Predicates evaluate. GATE at Q3.2: the commit invariant. GATE at Q3.4: escalation threshold | Control requirement set |
| Q4.1–Q4.3 Choose the build surface Decision | Control requirement set; realisation match; build surface matrix; enforceability matrix | Incumbent or not , then which surface . GATE at Q4.3: can it enforce every obligation? No returns to Stage 2 | Build surface decision |
| Q5.1–Q5.3 Select components Decision | Control requirement set; quality attribute scenarios; realisation match; AI capability map | Which candidate per capability , scored against three requirement sets. Tradeoff where the intersection is empty. GATE at Q5.3: every obligation bound | Component selection; decision records; enforcement binding |
| Q6.1–Q6.2 Compose Decision | Component selection; facet vectors; reference architecture model | Topology only — who owns control flow. Families, connectors and enforcement points are all derived | Conceptual, logical and physical designs |
| Q7.1 Govern Pre-work | Designs; control requirement set; enforcement binding | No decision. Records evidence per guardrail and obtains approvals | Guardrail evidence record |
| Q7.2–Q7.3 Operate Gate | Outcome assertions; guardrail evidence record; criticality taxonomy | GATE at Q7.2: are assertions holding? GATE at Q7.3: has the tier changed — exit to de-registration, or re-enter at Stage 0 | Operating record |
