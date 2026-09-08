# Reference price sheet

**Artifact:** price_sheet
**Source:** Intake_Agent_Requirements_v2_7.docx
**Rendered:** generated from the source above by scripts/extract_cafe_seed.py
**Caveat:** The figures are illustrative of the STRUCTURE; the live values are held in the artifact structured store and versioned. Every costed line must cite the sheet version it came from, and an estimate against this seed says so.

| Service | Typical unit | Reference monthly estimate | Banded | Notes |
|---|---|---|---|---|
| API Management (Developer) | Instance | ~175 | No | Shared gateway; scales to Standard for production |
| Container Registry (Basic) | Instance | ~20 | No | Shared with the platform |
| Container Apps | vCPU-hour and memory-hour | ~100–400 | Yes | Scales to zero when idle |
| AI Foundry hub and project | Fixed plus per-run | ~180 | No | Hosts the agents |
| Azure OpenAI — frontier model, provisioned | PTU per month | ~9,200 | No | Provisioned when steady; consumption when bursty |
| Azure OpenAI — smaller models | Per 1K tokens | ~500–2,000 | Yes | Depends on call and token volume from the workflow graph |
| Azure OpenAI — embeddings | Per 1K tokens | ~50–200 | Yes | Retrieval indexing |
| AI Search (Basic) | Instance | ~275 | No | Registry and retrieval index |
| Key Vault | Per 10K operations | ~20 | No | Secrets and customer-managed keys |
| Application Insights and Log Analytics | Per GB ingest | ~100–400 | Yes | Traces, metrics and audit |
| SharePoint and Graph | M365 licensing | Included | No | State and documents |
| Conversational front door | Per-message pack | ~700+ | Yes | Only where a conversational channel is used |
