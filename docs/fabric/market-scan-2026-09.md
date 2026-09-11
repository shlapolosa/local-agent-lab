# Market scan (September 2026) — providers against the Knowledge Management capability list

Replaces Figure 4 of the initiative doc v1.0. Columns are provider *classes* with the leading product
named; rows are the L4 capabilities of `capability-map-v1.6b`. Ratings are from public product
documentation and 2026 launch coverage (sources at the end), not from a live evaluation.

**Legend** · ● covers as shipped · ◐ partial — covers a slice, or only inside its own store · ○ none ·
✕ structurally excluded by a fabric principle (residency, federation/custody, no ADO/SharePoint estate)

| L4 capability (1.6b) | Microsoft estate as shipped¹ | Glean | Atlassian Rovo + Teamwork Graph | Google Gemini Enterprise | Curated KB suites² | Taxonomy / ontology platforms³ | Docs-as-code (Swimm) | Search specialists⁴ |
|---|---|---|---|---|---|---|---|---|
| **1 Knowledge Organisation** | | | | | | | | |
| 1.1 Vocabulary Management | ◐ term store + SP Premium taxonomy tagging; no ontology, no alignment | ◐ entity graph, not a governed vocabulary | ◐ Teamwork Graph, not a governed vocabulary | ◐ Knowledge Catalog is for data assets | ○ tags/categories | **●** SKOS/OWL, alignment, concept lifecycle — the core product | ○ | ◐ entity/ontology extraction (Sinequa) |
| 1.2 Catalog Management | ◐ Graph/Work IQ index; no artifact lifecycle state | ◐ index of pointers; no lifecycle state | ◐ cross-tool identities; page states | ◐ | ● but **custody** — content moves in ✕ | ◐ linked-data URIs | ○ | ◐ |
| **2 Knowledge Production** | | | | | | | | |
| 2.1 Content Synthesis | ◐ Copilot drafting; Content Assembly for templates; no event-driven re-draft | ◐ agents draft | ◐ Rovo agents draft pages from Jira | ◐ agents draft | ◐ Now Assist drafts KB articles from incidents | ○ | ● code docs only | ○ |
| 2.2 Knowledge Classification | **●** SP Premium classify/extract/autofill; Purview labels; owner from site (partial) | ◐ | ◐ | ◐ | ◐ | ● concept linking / classification (extractors) | ○ | ◐ entity extraction |
| 2.3 Version Management | ● SharePoint versions; baseline-on-approval is build | ○ | ● Confluence versions | ○ | ● | n/a | ◐ git | ○ |
| 2.4 Traceability Management | ◐ ADO links + Work IQ signals; no ladder, no orphan queue | ◐ relations inferred, not captured | **◐/●** work item ↔ page ↔ code edges captured at creation — but Jira/Confluence, not ADO/SharePoint ✕ | ○ | ○ | ○ | ◐ doc ↔ code | ○ |
| **3 Knowledge Governance** | | | | | | | | |
| 3.1 Ownership & Stewardship | ◐ site owners; steward console is build | ◐ verified answers/owners | ◐ page owners | ○ | **●** verifiers, ownership groups, KB owner RACI | ◐ vocabulary stewardship | ◐ doc owners | ○ |
| 3.2 Knowledge Review | ◐ Teams Approvals + Power Automate (build) | ○ | ◐ via apps | ○ | **●** verification cycles, review dates, valid-to, approval flow | ◐ concept workflow | ◐ PR review | ○ |
| 3.3 Duplicate Management | ◐ | ◐ result dedup | ○ | ○ | ◐ | ○ | ○ | ◐ |
| **4 Knowledge Discovery** | | | | | | | | |
| 4.1 Knowledge Retrieval | ● Copilot + Work IQ (MCP/REST/A2A, GA Jun 2026) | ● | ● | ● | ● own corpus only | ◐ graph search | ◐ | ● |
| 4.2 Knowledge Recommendation | ◐ | ● proactive | ◐ | ◐ | ◐ | ○ | ○ | ● (Coveo) |
| 4.3 Expertise Identification | **●** Work IQ people signals | ● | ◐ | ◐ | ◐ | ○ | ○ | ● expert finder (Sinequa) |
| **5 Knowledge Currency** | | | | | | | | |
| 5.1 Change Detection | ● Graph change notifications + ADO service hooks (raw events) | ◐ crawl freshness | ● Jira/Confluence events, Rovo triggers | ◐ | ◐ webhooks | ○ | ● code-change events in CI | ◐ |
| 5.2 Change Impact Analysis | ○ | ○ | ◐ the graph could answer; no product feature | ○ | ○ | ○ | **●** docs invalidated by code change — one domain only | ○ |
| 5.3 Subscription Management | ◐ alerts, Teams, Viva digests | ◐ | ● watch, subscriptions, digests | ◐ | ◐ | ○ | ◐ | ○ |
| 5.4 Republication | ◐ Power Automate (build) | ○ | ◐ | ○ | ◐ | ○ | ● auto-fix simple drift | ○ |
| 5.5 Catalog Reconciliation | ◐ Graph delta queries | ● crawler freshness | ● graph updates itself | ● | n/a (monolith) | ○ | ● | ● |
| 5.6 Remediation Management | ◐ Copilot Studio / Agent 365 could draft; nothing product-level | ◐ agents with write actions behind an approval gateway | **●** Rovo agents plan/execute across Jira & Confluence | ◐ agents act via extensions | ○ | ○ | ● auto-fix + alert | ○ |
| **Consumed (not owned)** | | | | | | | | |
| Access Management | ● Entra + Purview labels | ● inherited permissions | ● within Atlassian | ● | ◐ | ◐ | ◐ | ● early-binding (Coveo/Sinequa) |
| Audit Management | ● Purview audit | ◐ | ◐ | ◐ | ◐ | ◐ | ◐ | ◐ |
| Records Retention | ● Purview | ○ | ○ | ○ | ◐ | ○ | ○ | ○ |
| **Fabric constraints** | in-region (UAE North / M365 UAE) ✓ · federation ✓ | hosted AWS/GCP — residency ✕ | requires Jira/Confluence as systems of record ✕ · residency to verify | Google Cloud region for UAE — to verify · federation ◐ | SaaS, content moves in — federation ✕ · residency ✕ | deployable on Azure / in-tenant ✓ | SaaS; self-hosted option — to verify | Sinequa/Elastic deployable in-region ✓ · Coveo SaaS — verify |

¹ M365 Copilot, Work IQ, SharePoint (+Premium), Purview, Entra, Teams, Power Platform, Copilot Studio, Azure DevOps — as configured, before any pro-code.
² Guru, ServiceNow Knowledge Management, Bloomfire, Document360.
³ PoolParty Semantic Suite, Progress Semaphore, TopBraid EDG, Synaptica Graphite.
⁴ Glean listed separately; here Coveo, Sinequa, Elastic (build).

## Findings

1. **No single product covers the L4 set — the v1.0 conclusion stands, but it is now cell-precise.** The
   best single column is the Microsoft estate as shipped: 5 full, 11 partial, 1 none of the 18 owned L4s.
   Every partial is the composition work; the none is Change Impact Analysis.
2. **The nearest single-product *shape* is Atlassian Teamwork Graph + Rovo** — the only vendor whose core
   object model is work item ↔ page ↔ code with edges *captured at creation*, plus agentic writeback. It is
   excluded because it requires Jira and Confluence as the systems of record; DOH runs ADO and SharePoint.
   It is the reference for what the composed build should feel like, not a candidate.
3. **Vocabulary Management — the gap cell in 1.6d — has a mature specialist market.** PoolParty, Semaphore,
   TopBraid EDG and Synaptica are all SKOS/OWL, all support alignment and concept lifecycle, and are
   deployable in-tenant. This is the second **buy-lite** candidate alongside SharePoint Premium. The cheapest
   estate option, the SharePoint term store with SP Premium taxonomy tagging, covers concept schemes but not
   ontology or cross-scheme alignment.
4. **"Impact analysis has zero market coverage in any column" (v1.0 §4.3) is no longer accurate.** Swimm's
   Auto-sync detects documentation invalidated by a code change and fixes trivial drift, alerting on the rest —
   impact analysis and rung-4 remediation, in one domain. The pattern is proven; the cross-system version over
   the ADO key is still nobody's product. Reword the finding to "no general-purpose coverage".
5. **Curated KB suites are the reference model for Governance**, not a candidate: verification cycles,
   ownership groups, valid-to dates and approval flows are exactly 3.1–3.2. They are excluded by federation —
   content moves into their store — so they serve as pattern proof, as Sembly does for synthesis.
6. **Work IQ moved from "watch" to "consume at MVP".** GA on 16 June 2026 with a remote MCP server, REST and
   A2A, billed on consumption independent of Copilot licences. It covers 4.3 Expertise Identification and the
   retrieval half of 4.1 over M365 as shipped, and is the natural signal source for rung-3 association
   suggestions. Residency and billing controls remain to be verified for the UAE geo.
7. **Glean's "read-only" verdict is stale.** Glean agents now take write actions behind a policy and approval
   gateway. The exclusion stands on residency alone (hosted on AWS/GCP), and it still has no vocabulary
   governance, no captured traceability and no impact analysis.

## Considered and placed — Obsidian (asked 2026-09-10)

Obsidian is a local-first personal knowledge tool: a folder of Markdown files with frontmatter
properties, wikilinks and backlinks, tags, a graph view, and since early 2026 "Bases" (database views
over properties). Free for work since 20 Feb 2025 (commercial licence optional). No first-party MCP
server as of Aug 2026; the community Local REST API plugin exposes a Streamable-HTTP MCP endpoint and
Obsidian 1.12 added a first-class CLI. Sync and Publish are hosted paid add-ons.

| L4 | Rating | Why |
|---|---|---|
| 1.1 Vocabulary Management | ○ | tags are a folksonomy; no schemes, alignment or lifecycle |
| 1.2 Catalog Management | ◐ | file path as identity, properties as metadata, Bases as catalog views; lifecycle state only by convention |
| 2.1 Content Synthesis | ◐ | templates (Templater), AI plugins draft; no event-driven re-draft |
| 2.2 Knowledge Classification | ○ | manual properties; no owner/label resolution |
| 2.3 Version Management | ◐ | file recovery, git plugin |
| 2.4 Traceability Management | ◐ | wikilinks/backlinks are reference edges captured at authoring; no delivery association |
| 3.1–3.3 Governance | ○ | single-user: no owners, review, permissions, labels or audit |
| 4.1 Knowledge Retrieval | ◐ | local search; embeddings via plugins; graph view is Relationship Navigation at personal scale |
| 4.2 / 4.3 | ○ | — |
| 5.1 Change Detection | ◐ | file watchers |
| 5.2–5.6 Currency | ○ | backlinks show what links, not what a change invalidates |
| Constraints | | local vault ✓ residency (Sync/Publish hosted — verify) · federation ✕ content moves into the vault · NFR-3/NFR-8 ✕ a local copy escapes the source's read-time access decision |

**Verdict.** Not a candidate for any owned L4 and excluded as a consumer surface: a personal vault is a
copy that no source system trims at read time, so it would be the one door without label pass-through.
Two legitimate uses:

1. **Pattern proof for the three-axes model** (note 001) at personal scale — identity = path, subject =
   tags/properties, structural = wikilinks, discovery = graph view and Bases. It is the strongest evidence
   that the model is natural to people, which matters for adoption.
2. **A throwaway projection surface for the one-week laptop-local POC (§2.3)** — the fabric's Projection
   Regeneration (5.4) writes Markdown anyway (the ADO wiki is Markdown); a vault of generated notes with
   frontmatter = catalog record and wikilinks = reference edges lets a reviewer *see* the graph without
   building a UI. Throwaway by declaration, like the n8n walking skeleton; never a production door.

## What this does to the sourcing decision

Composed build, single branch — unchanged. The composition is now specified per cell: estate as shipped for
the ● cells; buy-lite pilots for 1.1 (taxonomy platform vs term store) and 2.2 (SP Premium vs custom
Function); pro-code only for 1.2, 2.4, 5.2 and the orchestration that joins them; low-code for 3.1–3.2, 5.3.
The bake-off in `capability-map-v1.6d` runs over exactly those cells.

## Sources
- Glean agents and approval gateway: gend.co (2026), rmax.ai, fritz.ai review 2026
- Work IQ GA 16 Jun 2026, MCP/REST/A2A, consumption billing: Microsoft 365 Developer Blog; Microsoft Learn "Work IQ MCP overview"; devlery.com
- Atlassian Team '26, Teamwork Graph opened via CLI + MCP, Rovo agentic execution: SiliconANGLE 6 May 2026; atlassian.com/blog
- SharePoint Premium 2026 (classify/extract, autofill, taxonomy tagging, content assembly, pay-as-you-go): EPC Group guide 2026; Microsoft Community Hub
- PoolParty (SKOS/OWL, ontology management, extraction/classification): help.poolparty.biz; poolparty.biz/ontology-management
- Taxonomy platform comparison 2026 (PoolParty, Synaptica Graphite, TopBraid EDG, Semaphore): ovaledge.com; topquadrant.com docs; progress.com/semaphore
- Swimm Auto-sync: swimm.io feature updates; thectoclub.com review 2026
- Enterprise search comparison 2026 (Coveo, Sinequa, Elastic, Glean; permission models): chapsvision.com; coworker.ai; flur.ee
- Curated KB suites (Guru verification, ServiceNow ownership groups / valid-to / review cycles): livepro.com; servicenow.com community 2026; bloomfire.com
- Gemini Enterprise (formerly Agentspace; Knowledge Catalog; connectors incl. SharePoint, Jira, Confluence): cloud.google.com; atlan.com guide 2026
- Obsidian: obsidian.md/blog/free-for-work (20 Feb 2025); affine.pro Obsidian MCP guide 2026 (no first-party MCP as of Aug 2026; Local REST API MCP endpoint; CLI in 1.12); enersys.co.th Obsidian 2026 guide (Bases)
