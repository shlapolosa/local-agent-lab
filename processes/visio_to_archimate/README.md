# Visio → ArchiMate (first Microsoft Agent Framework workflow)

Drop a Visio diagram in `visio-in/` → a **Business Analyst** agent describes the system → an
**Architect** agent formalises it into ArchiMate → governed render + **human approval** → ADOIT.
This is the lab's first real business process on the Microsoft Agent Framework: two agents that
authenticate with their own Entra identity, egress through the gateway (metered, PII-scanned),
and are traced as one run — exactly the docx operating model.

## Shape

```
ba ──▶ architect_design ──▶ store ──▶ architect_finalize ──▶ stage_import
(reads Visio    (BA desc ->     (spec+views    (agent calls validate     (human-gated
 via read_vsdx   engine spec)    -> art:// ref)  + render BY REF)          ADOIT import)
 TOOL)
```

- A Microsoft Agent Framework **`WorkflowBuilder` graph** (`workflow.py`) — typed nodes, one host
  process, distinct OTel service name `process-visio-to-archimate`.
- **Agents call tools, but BY REFERENCE.** The BA calls a `read_vsdx(path)` tool; the Architect
  emits its spec as structured output, a deterministic node stores it (`art://` ref), and the
  Architect calls the gateway-MCP `semantic_validate_model` + `archimate_render` **by `spec_ref`**.
  Small-arg tool calls are reliable; a large spec passed *inline* as a tool argument is emitted only
  stochastically (AF #2747), so we always pass the ref. A **deterministic fallback** guarantees the
  pipeline completes if a model skips a call. The final ADOIT write stays deterministic + human-gated.
  Client is `OpenAIChatClient` (Responses API) forced stateless via `store=False` (Ollama Cloud's
  Responses store is non-persistent — see CLAUDE.md / [[agent-framework-tool-calling]]).
- **Contracts:** the BA emits `schemas/ba_output.schema.json`; a **deterministic gate rejects
  incomplete output** (one BA retry) before the Architect sees it. Agents never call each other
  directly — the workflow mediates.
- **Identity:** `ba-agent` (role `EA.Model`) and `architect-agent` (`EA.Model` + `Tools.ADOIT`),
  one Entra app registration ↔ one virtual key each, both in team `visio-conversion`. LLM calls use
  each agent's own credential (spend attributes per key); the tool nodes use the Architect's
  identity (which holds the ADOIT/semantic grants).

## Run

```bash
./lab.sh up                                                  # stack must be running
set -a && source .env && set +a
.venv/bin/python -m processes.visio_to_archimate.make_sample_vsdx   # (re)build the test fixture
.venv/bin/python -m processes.visio_to_archimate.host              # run the workflow
./lab.sh review                                              # approve at :8501 (or shared/approvals.py approve <id>)
```

`host.py [file.vsdx]` takes an optional path (default `visio-in/lab-system.vsdx`). It prints the
trace id, the approval request id, and the review URL.

## Round-trip test

The fixture `visio-in/lab-system.vsdx` is generated from the lab's own model
(`architecture/lab_model.json`, `governance-plane` view — 20 elements). Running the workflow
recovers **20/20 element names and 20/20 types**, staged as a real ArchiMate model. Observe one
trace in Jaeger (`process-visio-to-archimate` + gateway + `semantic-mcp`/`adoit-mcp` spans) and
separate spend on the two agent keys.

## Files

- `make_sample_vsdx.py` — genuine minimal `.vsdx` from `lab_model.json` (OPC/OOXML, opens in the
  `vsdx` lib like any real upload).
- `agents.py` — the two ChatAgents (gateway `/v1`, per-agent credential); instructions composed
  from `prompts/` + `references/method.md` + the registered `visio-reader` skill.
- `workflow.py` — the typed graph + deterministic tool nodes + retry loops.
- `host.py` — OTel service name, root span, credential wiring, run + report.
- `prompts/{ba,architect}.md`, `references/method.md`, `schemas/ba_output.schema.json` — greenfield.
- Reader lives in the skill: `.claude/skills/visio-reader/scripts/read_vsdx.py` (registered in
  LiteLLM; the ingest node imports it).
