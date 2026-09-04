# Visio → ArchiMate (first Microsoft Agent Framework workflow)

Submit a system diagram (a Visio `.vsdx` **or an image**) plus optional requirements documents → a
**Business Analyst** agent describes the system → an **Architect** agent formalises it into
ArchiMate → governed render + **human approval** → ADOIT. This is the lab's first real business
process on the Microsoft Agent Framework: two agents that authenticate with their own Entra
identity, egress through the gateway (metered, PII-scanned), and are traced as one run — exactly the
docx operating model.

## Shape

```
ba ──▶ resolve_existing ──▶ architect_design ──▶ store ──▶ architect_finalize ──▶ stage_import
(reads   (search ADOIT:        (BA desc + matches   (spec ->    (agent calls validate  (human-gated
 inputs   NEW vs UPDATE,        -> engine spec,      art:// ref  + render BY REF)        EA import,
 via gw   match existing ids)    reuse ids, folder)   via sem-mcp)                       decision shown)
 storage)
```

**Existing-architecture-aware.** `resolve_existing` searches the live EA repository (`ea_search`,
through the gateway — the vendor-neutral port; ADOIT 18 is what answers it today) for objects related
to the described system, and a Resolver agent (`prompts/resolve.md`) decides **NEW vs UPDATE**, picks
the **domain**, and matches BA elements to existing repository object ids. The Architect then **reuses those ids verbatim** (so ADOIT is updated,
not duplicated) and tags every element with the domain `folder`; the engine emits `<organizations>`
grouping by domain → layer; relation ids are stable hashes. The reviewer confirms update-vs-new at
the approval gate. If ADOIT is unreachable the run proceeds as NEW.

**Write path — ONE call to the port.** `stage_import` calls `ea_stage_import(spec_ref, model_name,
summary, xml_ref, svg_refs)`: the repository takes the model BY REFERENCE, produces whatever IT needs a
human to import, and returns those `artifacts` plus the human `instructions`. The workload does not
know — and must not assume — what they are. On this ADOIT:CE tenant (REST writes blocked at the edge)
they are two files, both imported through the ADOIT UI after approval:
- **Objects → an Excel file**: ADOIT's "Import objects from Excel" **creates and updates** objects —
  and their **relationships** — matching each row on its **name** (found once → update in place,
  absent → create). This is why object names must stay unique — the existing-aware step's job.
- **Views → the ArchiMate XML** (rendered by `archimate_render` and reused): imports the diagram.
  ArchiMate import always *creates* (never matches on identifier — verified), so it's the views path;
  the Excel file keeps objects de-duplicated and updatable. The granular REST write facade is built but
  gated behind `.env` `ADOIT_REST_WRITE` (off on CE, on for a full ADOIT tenant) — such a tenant's
  adapter would write after the approval and return NO artifacts, with no change to this workload.

- A Microsoft Agent Framework **`WorkflowBuilder` graph** (`workflow.py`) — typed nodes, one host
  process, distinct OTel service name `process-visio-to-archimate`.
- **Agents call tools, but BY REFERENCE.** The BA reads its inputs through the gateway's
  **storage-mcp** (`storage_read_vsdx` / `storage_read_document`); the Architect emits its spec as
  structured output, a deterministic node stores it via `semantic_store_spec` (getting an `art://`
  ref), and the Architect calls the gateway-MCP `semantic_validate_model` + `archimate_render` **by
  `spec_ref`**. Small-arg tool calls are reliable; a large spec passed *inline* as a tool argument is
  emitted only stochastically (AF #2747), so we always pass the ref. A **deterministic fallback**
  guarantees the pipeline completes if a model skips a call. The final ADOIT write stays
  deterministic + human-gated. Client is `OpenAIChatClient` (Responses API) forced stateless via
  `store=False` (Ollama Cloud's Responses store is non-persistent — see CLAUDE.md /
  [[agent-framework-tool-calling]]).
- **Inputs are by reference, and the workload holds no store credentials.** Every input is an
  `art://` ref in the upload store; the workload reads it *only* through storage-mcp via the gateway
  (governed, metered, traced). `inputs.py` keeps the same helpers for local **paths** (dev). Three
  kinds: a `.vsdx` is parsed deterministically; a **diagram image** (png/jpg) is fetched by the
  deterministic BA node (`storage_get`) and attached inline for the model's vision; a **requirements
  document** (docx/pdf/md/txt) is read as text (`storage_read_document`) and its **embedded figures**
  are extracted (`storage_extract_figures`) and attached too. Image sizing is normalised server-side
  (≤1600 px, PNG/JPEG, decorations dropped) — the `visio-reader` skill documents the contract.
  Requirements are evidence, not new boxes.
- **Contracts:** the BA emits `schemas/ba_output.schema.json`; a **deterministic gate rejects
  incomplete output** (one BA retry that re-sends the diagram) before the Architect sees it. Agents
  never call each other directly — the workflow mediates.
- **Identity:** `ba-agent` (role `EA.Model`) and `architect-agent` (`EA.Model` + `Tools.ADOIT`),
  one Entra app registration ↔ one virtual key each, both in team `visio-conversion` (granted
  `ea_mcp` + `semantic_mcp` + `storage_mcp`). LLM calls use each agent's own credential (spend
  attributes per key); the BA node reads inputs with the BA's identity, the tool nodes use the
  Architect's (which holds the EA-repository/semantic grants).

## Run

Two entry points share `host.run_once()`:

**Long-lived host (the normal shape) — event-triggered from the review app's Submit page:**
```bash
./lab.sh up            # substrate: gateway, semantic-mcp, adoit-mcp, storage-mcp, workflow-mcp, review,
                       #            redis, jaeger + any configured approval channel (telegram/teams)
./lab.sh consumer      # wf-visio: consumes workflow:requests and runs the workflow per event
./lab.sh review        # open :8501 -> Submit mode: upload a diagram (+ docs) -> Run
```
The review app writes the uploads to the upload store, publishes a `workflow:requests` event, and
shows the run's status → trace → approval as the consumer writes them back. **Runs** mode watches any
run live — whichever host started it (consumer, CLI, DevUI): current node, the per-node "Inside the
run" panel, and links to the approval and artifacts it produced. Approve in **Review** mode (or
`python -m lab.substrate.approvals approve <id>`); `python -m lab.platform.workflows list` shows
requests. An agent or another client does the same through the governed **workflow-mcp** tools on the
gateway (`visio_to_archimate_submit/_status/_result`, plus `approvals_list/_get/_decide`).

**One-shot / CLI (dev, demo, smoke):**
```bash
set -a && source .env && set +a
# a path (local tools):
.venv/bin/python -m lab.workloads.visio_to_archimate.host [diagram.vsdx|image.png] [-r doc.docx ...]
# or by reference (upload once, read through storage-mcp):
.venv/bin/python -m lab.substrate.review.uploads upload diagram.png req.docx   # -> art:// refs
.venv/bin/python -m lab.workloads.visio_to_archimate.host art://<id>/diagram.png -r art://<id>/req.docx
# or publish an event and let the consumer run it:
.venv/bin/python -m lab.platform.workflows request visio_to_archimate art://<id>/diagram.png art://<id>/req.docx
```
With no args, `host.py` falls back to the fixture, or to `VISIO_DIAGRAM` / `VISIO_REQUIREMENTS`
env (`# CLOUD:` lines) for a container job. It prints the trace id, approval request id, and review URL.

## Where inputs live

The **upload store** is `UPLOADS_URL` (default = the artifact store). Locally that is Postgres, so
no object store is needed. **Target state on the cloud** is a Railway **Bucket** (S3-compatible;
`railway.py bucket up` once the bucket exists) so uploads live in real object storage — `S3Store`
in `src/lab/substrate/artifacts.py` is ready; until then cloud uploads land in Postgres too, transparently.
Bucket/DB credentials live only in storage-mcp and the review app; they are stripped from every
workload service (`deploy/railway.py configure_workload()`).

## Round-trip test

The fixture `var/inputs/visio_to_archimate/lab-system.vsdx` is generated from the lab's own model
(`var/out/architecture/lab_model.json`, `governance-plane` view — 20 elements). Running the workflow
recovers the element names and types, staged as a real ArchiMate model. Observe one trace in Jaeger
(`process-visio-to-archimate` + gateway + `semantic-mcp`/`adoit-mcp`/`storage-mcp` spans) and
separate spend on the two agent keys. Verified on the cloud (Sep 2026): an uploaded image + docs →
approval with a 20–30 element model, the Eligibility Service recovered from a document's embedded
figure.

## Files

- `make_sample_vsdx.py` — genuine minimal `.vsdx` from `lab_model.json` (OPC/OOXML, opens in the
  `vsdx` lib like any real upload).
- `inputs.py` — input dispatch (`kind`/`media_type`/`load`) for local **paths**; `upload()` → the
  upload store. Refs are read through storage-mcp, never here.
- `agents.py` — the two ChatAgents (gateway `/v1`, per-agent credential); the BA's `ba_tools()`
  (gateway storage read tools) and the Architect's `architect_tools()` (validate + render).
- `workflow.py` — the typed graph; the BA node fetches images via storage-mcp and attaches them,
  reads by ref, stores the spec via `semantic_store_spec`; deterministic tool nodes + retry loops.
- `host.py` — `run_once()` (OTel service name, root span, credential wiring) shared by the CLI and
  the consumer; `main()` is the CLI/one-shot entry.
- `consumer.py` — the long-lived host: consumes `workflow:requests` (Redis Streams), runs
  `run_once` per event, writes status/trace/approval back, PEL crash recovery on start.
- `devui_entry.py` — the third (LOCAL, dev-only) host: the same workflow inside Agent Framework
  DevUI, every run also a row on the Runs board. See `docs/workloads/visio_to_archimate/DEVUI.md`.
- `prompts/{ba,architect}.md`, `references/method.md`, `schemas/ba_output.schema.json` — greenfield.
- `deploy/compose.yml` — the workload as its own container set (`visio-host` consumer + `visio-job`).
- Shared parsing + the image sizing contract live in `src/lab/platform/docparse.py`; the Visio reader is
  `src/lab/core/visio/read_vsdx.py` (registered in LiteLLM).
