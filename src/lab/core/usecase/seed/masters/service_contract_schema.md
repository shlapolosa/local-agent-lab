# Service contract schema

**Artifact:** service_contract_schema
**Source:** CAFE_Artifacts_Visualisation_v0_25.html
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py

| Field | What it records |
|---|---|
| Service name | Verb-plus-object, consumer-facing. "Classify incident", not "classification microservice" |
| Consumers | Which steps, agents or EA blocks call it |
| Offered behaviour | What it does, stated as an interface contract rather than an implementation |
| Service level | Availability, latency at a percentile, throughput, data freshness, retention. Derived from the business service level, never invented |
| Owned entities | Which business objects this service is authoritative for |
| Failure semantics | What the consumer may assume on failure |
| Versioning and compatibility | How change is exposed to consumers |
