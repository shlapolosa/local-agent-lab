# Intake field specs

**Artifact:** intake_field_specs
**Source:** derived from intake_fields.json by scripts/derive_intake_fields.py — the groups stay the published artifact; these are their fields, typed
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py

| Field | Group | Label | Type | Required | Order | Used by |
|---|---|---|---|---|---|---|
| Effort table · Role | Effort table | Role | text | no | 1 | Driver 1 |
| Effort table · headcount | Effort table | headcount | number | no | 2 | Driver 1 |
| Effort table · frequency per week | Effort table | frequency per week | number | no | 3 | Driver 1 |
| Effort table · current minutes per instance | Effort table | current minutes per instance | number | no | 4 | Driver 1 |
| Effort table · expected minutes per instance | Effort table | expected minutes per instance | number | no | 5 | Driver 1 |
| Quality baseline · Current volume | Quality baseline | Current volume | number | no | 6 | Driver 2 |
| Quality baseline · error rate | Quality baseline | error rate | number | no | 7 | Driver 2 |
| Quality baseline · expected reduction | Quality baseline | expected reduction | number | no | 8 | Driver 2 |
| Quality baseline · error class | Quality baseline | error class | text | no | 9 | Driver 2 |
| Sensitivity flags · Personal data | Sensitivity flags | Personal data | yesno | yes | 10 | Driver 3 and the criticality band |
| Sensitivity flags · health data | Sensitivity flags | health data | yesno | yes | 11 | Driver 3 and the criticality band |
| Sensitivity flags · financial | Sensitivity flags | financial | yesno | yes | 12 | Driver 3 and the criticality band |
| Sensitivity flags · regulated | Sensitivity flags | regulated | yesno | yes | 13 | Driver 3 and the criticality band |
| Avoided cost citation · Specific avoided fine or audit-hour reduction | Avoided cost citation | Specific avoided fine or audit-hour reduction | number | no | 14 | Driver 3, where quantified |
| Avoided cost citation · with its source | Avoided cost citation | with its source | text | no | 15 | Driver 3, where quantified |
| Data maturity · Whether the underlying data is fully digital | Data maturity | Whether the underlying data is fully digital | yesno | no | 16 | Driver 1 Year-1 discount |
| Investment · Budget bucket or vendor quote | Investment | Budget bucket or vendor quote | text | no | 17 | Build cost |
| Urgency · Required-by date or urgency band | Urgency | Required-by date or urgency band | date | yes | 18 | Roadmap section |
| Volume assumptions · Runs per month | Volume assumptions | Runs per month | number | no | 19 | Cost — places every banded price line in its band; a driver left blank makes that line requires_input, never a guess |
| Volume assumptions · users | Volume assumptions | users | number | no | 20 | Cost — places every banded price line in its band; a driver left blank makes that line requires_input, never a guess |
| Volume assumptions · records (Finance-owned) | Volume assumptions | records (Finance-owned) | number | no | 21 | Cost — places every banded price line in its band; a driver left blank makes that line requires_input, never a guess |
