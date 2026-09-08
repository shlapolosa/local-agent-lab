# Benefit drivers

**Artifact:** benefit_drivers
**Source:** Intake_Agent_Requirements_v2_7.docx
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py
**Caveat:** The formulas are authoritative; the reference VALUES (role rates, cost per error) are held in their own registries and are not published here.

| Driver | Formula | Reference values |
|---|---|---|
| 1 — Operational efficiency (time saved on the task) | annual hours saved = headcount × frequency per week × 50 × (current minutes − expected minutes) ÷ 60; annual saving = annual hours saved × role hourly rate | Role rates from the role rate registry — clinician, nurse and administrative bands are held there as defaults and are overridable. A Year-1 discount applies where the underlying data is not fully digital |
| 2 — Quality and accuracy (fewer errors and rework) | annual quality saving = current volume × error rate × expected reduction × cost per error | Cost per error from the cost-per-error reference by error class — clinical and operational classes are held there |
| 3 — Compliance and risk reduction (avoided findings and audit effort) | Qualitative by default. Quantified only where a specific avoided fine or audit-hour reduction is cited at intake | Anchored on the sensitivity flags captured at intake — personal data, health data, financial, regulated — and the residency posture from the design |
