# Workload external contract: MCP tool first, A2A later, REST for human channels

Status: decided (Sep 4 2026) · Supersedes nothing · Informs `lab.platform.contracts`, the gateway registry

## Requirement

Workloads must be **discoverable and queryable by agents and other channels** (Copilot Studio via
Teams today; web and mobile later), **in a governed way, through the gateway**. A workload may also
need to reach outward (completion, "a human must approve this now").

## Decision

1. **The task contract is the product.** Submit / status / result / approve already exist internally
   (`lab.platform.workflows.request|status|mark`, `lab.substrate.approvals`, `lab.platform.runlog`).
   Make it explicit in `lab.platform.contracts`; every external surface is an ADAPTER over it.
2. **Primary exposure: one MCP server per workload, registered in the gateway.** Tools:
   `<process>_submit(diagram_ref, requirement_refs) -> request_id` (enqueues and acknowledges),
   `<process>_status(request_id)`, `<process>_result(request_id)`.
3. **A2A stays where the design already put it**: between AGENTS (agent card ↔ virtual key ↔ Entra
   app registration), for when processes split into separate hosts. A workload-level A2A façade is
   ADDITIVE and deferred until an orchestrator needs natural-language capability routing or A2A push
   notifications.
4. **REST (202 + enqueue, poll status) is added when a web/mobile client actually exists** — same
   task contract, HTTP adapter, OpenAPI document. Not before (YAGNI).

## Why not wrap the workload as an agent

A workload is a **deterministic Agent Framework workflow that CONTAINS agents**; containment is an
implementation detail, not an interface. Two findings decide it:

- **`Workflow.as_agent()` degrades the contract.** Its own docs: inputs are converted to a message
  list and "the workflow's start executor must accept `list[Message]`, otherwise initialization will
  fail". Our start executor takes a typed dict (`{diagram, requirements}`). Wrapping means accepting
  free text at the boundary and re-parsing it.
- **The gateway's MCP registry already IS governed discovery.** Servers are registered in
  `config/litellm-config.yaml`, granted per team via `object_permission.mcp_servers`, the tool list is
  filtered by grant (a key with no grant sees zero tools — verified), and every call is metered and
  traced. A2A is also proxied (`/a2a/{agent_id}`, `/message/send`, `/message/stream`, agent card,
  `POST /v1/agents`, per-agent cost) but it is the second mechanism, not the first.

| Exposure | Discoverable by agents | Typed contract kept | Governed by the gateway today |
|---|---|---|---|
| MCP server per workload | yes (tool list + team grants) | yes (JSON schema per tool) | yes |
| A2A agent façade | yes (agent card) | no (message coercion) | yes |
| Plain REST enqueue | no (needs its own registry) | yes (OpenAPI) | not without passthrough work |

Copilot Studio consumes MCP servers (onboarding wizard) AND A2A agents (GA Apr 2026) through the same
custom-connector infrastructure, so the low-code channel does not force A2A.

## Async is mandatory, sync is impossible

A run takes 600-1000 s (measured). No connector, gateway or mobile client holds a request that long.
`submit` returns a `request_id` immediately — the enqueue-and-acknowledge shape — and status is polled
or pushed. This is the existing Redis Streams contract, exposed.

## Outbound: state is not notification

Writing status where external parties read it gives STATE; it does not NOTIFY, and an approval can sit
for hours. Two mechanisms already exist: the **approvals channel abstraction** (review app, Telegram,
CLI are consumer groups — Teams becomes a fourth, the smallest useful change) and, if a workload-level
A2A façade lands, **A2A push notifications** to a client-registered webhook.

## Consequences / open items

- **Tier placement**: the MCP server kit lives in `lab.substrate.mcpserver`, and workloads MUST NOT
  import the substrate. If workloads serve MCP, the KIT moves to `lab.platform` by the importer rule
  (both tiers use it); the servers stay in their own tiers. Decide deliberately, not by accident.
- **Egress governance**: a workload POSTing a webhook to Teams is egress; today all egress goes
  through the gateway. Outbound notification needs the same rule or a stated exception.
- **File inputs**: external channels must upload before submitting (`art://` refs, upload store).
  Natural over REST/multipart, awkward over MCP/A2A — an argument for the REST surface when web/mobile
  arrive.
- **Identity**: external callers use Entra (JWT) or a durable virtual key; the gateway already
  validates both, so this is configuration, not new work.
