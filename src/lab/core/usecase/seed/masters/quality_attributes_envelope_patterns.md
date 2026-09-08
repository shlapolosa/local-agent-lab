# Quality attribute patterns — envelope_patterns

**Artifact:** quality_attributes
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py
**Section:** envelope_patterns

| Pattern | Values | Kind | Driven by |
|---|---|---|---|
| Latency envelope | interactive <2s · conversational <10s · background minutes · batch hours | derived | Trigger modifier, audience, business service level |
| Retrieval shape | single-corpus · federated · graph-traversal · hybrid with rerank | derived | Source count from E0.7, precision need, latency envelope |
| State shape | stateless · session-scoped · durable and checkpointed | derived | Workflow length, resumability requirement, topology |
| Failure semantics | at-most-once · at-least-once with idempotency key · saga with compensation | derived | Effect class, reversibility, EA block register |
| Change ownership | engineering · business · hybrid | chosen | Who authors rules and prompts after go-live |
| Model placement | shared endpoint · dedicated · fine-tuned · local | chosen | Data gravity, latency, cost shape, substitutability |
