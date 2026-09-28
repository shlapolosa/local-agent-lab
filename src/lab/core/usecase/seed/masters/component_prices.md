# Component price catalogue

**Artifact:** component_prices
**Source:** cafe-artifacts.xlsx
**Rendered:** imported from the source above by scripts/artifacts_workbook.py
**Caveat:** opex_low/opex_expected/opex_high, unit and note are the reference price sheet's own figures, illustrative of the STRUCTURE. variant, envelope_in, volume_driver, expected_at, high_at and the component mapping are this lab's structural placeholders — Finance's to replace in the corpus, not the sheet's. capex_once is not in the sheet: a design that needs it gets requires_input, never a guess. A line is volume-driven exactly when volume_driver is not none.

| component | variant | component_name | zone | unit | opex_low | opex_expected | opex_high | capex_once | envelope_in | volume_driver | expected_at | high_at | source_line | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cmp-967db4e8ad | developer | AI traffic gateway | gw | Instance | 175.0 | 175.0 | 175.0 |  | low; expected; high | none | 0 | 0 | API Management (Developer) | Shared gateway; scales to Standard for production |
| cmp-f560d81190 | container-registry-basic | Compute | pf | Instance | 20.0 | 20.0 | 20.0 |  | low; expected; high | none | 0 | 0 | Container Registry (Basic) | Shared with the platform |
| cmp-f560d81190 | container-apps | Compute | pf | vCPU-hour and memory-hour | 100.0 | 250.0 | 400.0 |  | low; expected; high | runs_per_month | 5000 | 50000 | Container Apps | Scales to zero when idle |
| cmp-5ebda000ea | hub-and-project | Hosted agent runtime | ag | Fixed plus per-run | 180.0 | 180.0 | 180.0 |  | low; expected; high | none | 0 | 0 | AI Foundry hub and project | Hosts the agents |
| cmp-525072e4ab | frontier-provisioned | Regional Provisioned models | mp | PTU per month | 9200.0 | 9200.0 | 9200.0 |  | high | none | 0 | 0 | Azure OpenAI — frontier model, provisioned | Provisioned when steady; consumption when bursty |
| cmp-bd9ee43705 | small-consumption | Foundry Global Standard | mp | Per 1K tokens | 500.0 | 1250.0 | 2000.0 |  | low; expected | runs_per_month | 5000 | 50000 | Azure OpenAI — smaller models | Depends on call and token volume from the workflow graph |
| cmp-8b6a0424ac | embeddings-consumption | Standard embeddings & speech | mp | Per 1K tokens | 50.0 | 125.0 | 200.0 |  | low; expected; high | records | 100000 | 1000000 | Azure OpenAI — embeddings | Retrieval indexing |
| cmp-e2eb6b87f6 | basic | Permission-aware search | kn | Instance | 275.0 | 275.0 | 275.0 |  | low; expected; high | none | 0 | 0 | AI Search (Basic) | Registry and retrieval index |
| cmp-6b2726fb06 | standard | Secrets & keys | sec | Per 10K operations | 20.0 | 20.0 | 20.0 |  | low; expected; high | none | 0 | 0 | Key Vault | Secrets and customer-managed keys |
| cmp-ad7e4cd271 | ingest | Observability & cost | gov | Per GB ingest | 100.0 | 250.0 | 400.0 |  | low; expected; high | runs_per_month | 5000 | 50000 | Application Insights and Log Analytics | Traces, metrics and audit |
| cmp-bb7cd41d32 | m365-included | Content & records | dt | M365 licensing | 0.0 | 0.0 | 0.0 |  | low; expected; high | none | 0 | 0 | SharePoint and Graph | State and documents |
| cmp-6c71a39bbd | message-pack | Low-code agents | ag | Per-message pack | 700.0 | 700.0 | 700.0 |  | low; expected; high | runs_per_month | 5000 | 50000 | Conversational front door | Only where a conversational channel is used |
