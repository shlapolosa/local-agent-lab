# Surface enforceability

**Artifact:** surface_enforceability
**Source:** cafe-artifacts.xlsx
**Rendered:** imported from the source above by scripts/artifacts_workbook.py

| Obligation | Declarative agent | Copilot Studio custom engine | Foundry hosted agent | Incumbent platform | Alternative runtime |
|---|---|---|---|---|---|
| G01 signed prompt and registry | △ | ✓ | ✓ | △ | △ |
| G02 tool scoping and review | ✓ | ✓ | ✓ | △ | △ |
| G03 first-class agent identity | ✓ | ✓ | ✓ | ✗ platform service account | △ |
| G05 sandboxed code execution | ✗ | △ | ✓ | △ | △ |
| G06 declared retrieval contract | ✓ | ✓ | ✓ | △ | △ |
| G07 authenticated A2A | ✗ | △ | ✓ | △ | △ |
| G08 budgets and circuit breakers | ✗ | △ | ✓ | ✓ platform owns control flow | ✓ |
| G09 human confirmation | ✓ | ✓ | △ | ✓ | △ |
| G10 registration and eval gate | ✓ | ✓ | ✓ | △ | △ |
| G17 liveness surfacing | ✗ | △ | △ | ✓ | △ |
| G18 recall target + confidence escalation | ✗ | △ | ✓ | ✓ | ✓ |
| G19 independent outcome monitoring | ✗ | ✗ | ✗ | ✓ reads its own system of record | △ |
| G20 content inspection at retrieval | △ | △ | ✓ | △ | △ |
| G21 outbound classification control | ✓ | △ | △ | △ | △ |
| G22 structured output enforcement | ✗ | △ | ✓ | △ | ✓ |
| G23 reversal or pre-commit confirmation | △ | ✓ | △ | ✓ | △ |
| G24 staged release and rate limiting | ✗ | △ | △ | ✓ | ✓ |
| G25 disclosure at emission | △ | ✓ | ✓ | ✓ | ✓ |
| G29 residency-gated model routing | ✗ Microsoft-managed routing, not via the gateway | △ only when models are called through the gateway | ✓ via the AI gateway | △ | ✓ via the AI gateway |
