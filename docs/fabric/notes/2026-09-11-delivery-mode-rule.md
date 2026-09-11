# Note 002 — Delivery-mode rule for the composition

**Status:** agreed 2026-09-11 · **Applies to:** the reuse-first column of the options view, the technology
landscape (1.6c/d) at the next re-cut, and the bake-off.

## Rule

Assign each L4 cell the first mode that applies, in this order:

1. **S — estate as shipped.** The Microsoft estate (or a non-excluded candidate already in the estate) covers
   the row as configured. Nothing is written.
2. **B — buy-lite.** A product covers the row, is not excluded by a fabric principle (residency, federation,
   systems of record), and is piloted rather than built. Procurement, not code.
3. **L — low code.** Only for (a) **end-user-facing surfaces** — cards, consoles, digests, conversational
   agents — and (b) **event triggering and timers** (Power Automate as the trigger is acceptable).
4. **P — pro code.** Anything that **touches a line-of-business system**: reads or writes to SharePoint
   content, ADO, the EA repository, Graph writeback, reconciliation against sources. **Tie-break:** a step
   that is neither user-facing nor LoB-touching — a pipeline / data-path step such as the catalog or
   duplicate detection — is also pro code (initiative doc §5.5: "failure there corrupts the product").

## Outcome for the reuse-first column (options view v1.0)

| Mode | Rows |
|---|---|
| S (7) | 2.2 Knowledge Classification · 2.3 Version Management · 4.1 Knowledge Retrieval · 4.3 Expertise Identification · Access · Audit · Records Retention |
| B (1) | 1.1 Vocabulary Management |
| L (5) | 3.1 Ownership & Stewardship (steward console) · 3.2 Knowledge Review (cards, escalation timer) · 4.2 Knowledge Recommendation (agent) · 5.1 Change Detection (triggers) · 5.3 Subscription Management (follow, digests) |
| P (8) | 1.2 Catalog Management · 2.1 Content Synthesis (writes drafts into SharePoint) · 2.4 Traceability Management · 3.3 Duplicate Management (pipeline step) · 5.2 Change Impact Analysis · 5.4 Republication (writes the wiki) · 5.5 Catalog Reconciliation (reads sources) · 5.6 Remediation Management (writes into LoB systems) |

## What it changes against the Annex D design

The rule converges the two target columns. Remaining differences are exactly the cells where the estate
ships something the design planned to build, i.e. the bake-off list: **2.2** (SharePoint Premium vs
custom Function), **2.3** (SharePoint versioning vs baseline service), **4.1 / 4.3** (Work IQ + Copilot vs
search API + expertise service), **1.1** (taxonomy platform vs the gap). One cell moves the other way:
**5.1 Change Detection** is L (triggers) here and P (receivers) in Annex D — the allow-list and
normalisation then live in the flow, which is acceptable only while the event set is small; the design's
receiver is the fallback when it is not.
