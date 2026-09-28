# Quality attribute patterns — envelope_patterns

**Artifact:** quality_attributes
**Source:** cafe-artifacts.xlsx
**Rendered:** imported from the source above by scripts/artifacts_workbook.py
**Section:** envelope_patterns

| Pattern | Values | Kind | Driven by |
|---|---|---|---|
| Latency envelope | interactive <2s · conversational <10s · background minutes · batch hours | derived | Trigger modifier, audience, business service level |
| Retrieval shape | single-corpus · federated · graph-traversal · hybrid with rerank | derived | Source count from E0.7, precision need, latency envelope |
| State shape | stateless · session-scoped · durable and checkpointed | derived | Workflow length, resumability requirement, topology |
| Failure semantics | at-most-once · at-least-once with idempotency key · saga with compensation | derived | Effect class, reversibility, EA block register |
| Change ownership | engineering · business · hybrid | chosen | Who authors rules and prompts after go-live |
| Model placement | shared endpoint · dedicated · fine-tuned · local | chosen | Data gravity, latency, cost shape, substitutability |
| Continuity tier | Tier 0 mission critical · Tier 1 critical · Tier 2 business important · Tier 3 standard | derived | Criticality class (step-07), availability rating of the service (step-12), business service level |
