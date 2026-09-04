# DevUI — live visualisation of a workflow run (LOCAL dev only)

Microsoft Agent Framework **DevUI** serves the Visio→ArchiMate `Workflow` object with a browser
UI: the executor graph, per-node events as a run progresses, the run's spans in a trace panel, and
an OpenAI-compatible `/v1/responses` endpoint to trigger runs. It is a third host for the SAME
workflow, next to `host.py` (one-shot) and `consumer.py` (long-lived) — nothing in the governed
path changes: every LLM and MCP call still goes through the gateway with each agent's own identity.

## Start

```bash
./lab.sh up                                                  # gateway + MCP servers + Jaeger must be up
.venv/bin/python -m lab.workloads.visio_to_archimate.devui_entry # -> http://127.0.0.1:8090
```

`.env` is loaded by the module (shell-exported values win). Flags: `--port` (or `DEVUI_PORT`),
`--open` (launch the browser), `--headless` (API only), `--auth` (Bearer token; off by default —
the server binds loopback only), `--sensitive-spans` (prompt/response bodies on AF spans; off by
default because spans go to whatever `OTEL_EXPORTER_OTLP_ENDPOINT` points at).

## Run one

Pick **visio-to-archimate** in the UI. The start executor takes a `dict`, so the input box is JSON
— paste the default (also printed at start), the Malaffi *Shafafiya* page:

```json
{"diagram": "<repo>/var/inputs/visio_to_archimate/malaffi-application-solution-arch.vsdx#Shafafiya", "requirements": []}
```

A bare path string is NOT accepted (DevUI only JSON-parses strings; it would reach the `ba` node
un-wrapped). `art://` refs and requirements documents work exactly as in `host.py`.

**Each run is a real run**: gateway LLM calls (metered per agent key), MCP tool calls, and at the
end an ADOIT approval request in the review app (`./lab.sh review`). Nothing is mocked.

## Triggering via the API — and why it will NOT animate in your browser

`POST /v1/responses` (OpenAI Responses shape) starts a run; the entity id must ALSO be given as
`metadata.entity_id` (without it: `400 Missing entity_id in metadata`):

```json
{"model": "<entity_id>", "input": "{\"diagram\": \"…vsdx#Shafafiya\", \"requirements\": []}",
 "stream": true, "metadata": {"entity_id": "<entity_id>"}}
```

DevUI streams a run's events **to the client that requested it**. An API-started run therefore
executes (visible in Jaeger and as a session in the dropdown) but the browser's Execution Timeline
and Events panels stay at 0 — they only animate runs started from the page's **Run Workflow**
button. To *watch* a run, start it from the UI. `POST /v1/responses/{id}/cancel` answers
`not_found` for API-started responses (they are not registered for cancel); an unwanted API run
simply completes (real cost) — or restart DevUI to kill it.

## Tracing

`devui_entry` installs the same OTLP tracer as `host.py` but with service name
**`process-visio-to-archimate-devui`**, so DevUI-driven runs are distinguishable in Jaeger from
consumer/CLI runs. One **session** root span is opened at start (its trace id is printed); every
run in that DevUI session — node spans, and via the injected `traceparent` the gateway and MCP
server spans — joins that one trace. DevUI's own trace panel shows the spans of the current run.
The boot line `Failed to enable Agent Framework observability: opentelemetry-exporter-otlp-proto-grpc
is required` is expected and harmless: AF tries to add a second (gRPC) exporter; ours is already
the global provider and AF's spans flow through it.

## Caveats

- **Local only — excluded from the container.** `agent-framework-devui` is deliberately not in
  `deploy/requirements.txt` (its prerelease pins broke the image build); `devui_entry.py` is never
  imported by any container role, `lab.sh` or `consumer.py`.
- **Venv: the repo `.venv`, nothing installed.** `agent-framework-devui 1.0.0b260821` is already
  there, pulled in by the `agent-framework` 1.16.0 meta package. Do NOT `pip install --pre
  agent-framework-devui` — the newer build (b260903) requires `agent-framework-core>=1.17.0` and would
  upgrade the pinned `1.16.0` under the running gateway/consumer. `pip check` is unchanged.
- Agent credentials are resolved once at start (MSAL JWT, or the durable key). A JWT expires after
  about an hour — restart DevUI for a long session, or run with the durable keys only.
- Do not use DevUI's directory scan (`devui src/lab/workloads/`): it would treat `visio_to_archimate/` as an
  entity because of `workflow.py` and look for a module-level `workflow` variable that does not
  exist. The entry registers the built object in-memory instead (`serve(entities=[wf])`).
- Port 8090 by default (DevUI's own default is 8080); loopback bind only.
