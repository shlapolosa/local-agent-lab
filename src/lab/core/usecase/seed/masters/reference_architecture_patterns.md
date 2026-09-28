# Logical reference architecture — patterns

**Artifact:** reference_architecture_patterns
**Source:** cafe-artifacts.xlsx
**Rendered:** imported from the source above by scripts/artifacts_workbook.py

| id | name | path | building_blocks |
|---|---|---|---|
| P1 | Inline assistant (T1) | EX1 → GW2 → GW3 → MS1 → MS2 | Human interaction channels → AI gateway → Sensitive-data policy point → Model router → In-region model serving |
| P2 | Agent-orchestrated (T2) | EX1 → GW2 → AG1 → AG4 → KS3 → TS2 → GW3 → MS1 | Human interaction channels → AI gateway → Agent runtime → Runtime policy enforcement → Retrieval service → Tool & action services → Sensitive-data policy point → Model router |
| P3 | Platform-orchestrated (T3) | AG2 → AG1 → AG5 → AG6 → TS2 → IN1 | Workflow orchestrator → Agent runtime → Runtime safety → Human oversight → Tool & action services → Integration adapters |
| P4 | Delegated (T4) | AG1 → AG3 → AG4 → IN1 | Agent runtime → Agent registry & router → Runtime policy enforcement → Integration adapters |
| P5 | Governed AI access (received & device agents) | EX3 → SC3 → GW2 → GW3 → MS1 → MS3 | Device-resident agents → AI provider egress control → AI gateway → Sensitive-data policy point → Model router → Sovereign model provider |
