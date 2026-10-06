# The Use Case Desk — how the Teams agent and the use-case workflow integrate

Status: describes production as measured on 4 Oct 2026 (Azure, APIM-only gateway), with the dev
differences called out where they exist. Companion to `use-case-screening-walkthrough.md` (what the
workflow does inside) and `docs/decisions/2026-09-24-azure-production.md` (why production is shaped
this way).

## 1. What it is

A person in Microsoft Teams (or the Copilot Studio test pane) talks to an agent, **Use Case Desk**, to
submit an AI use case for assessment, find use cases already submitted, follow a run to its outcome,
and answer the human questions the assessment raises. The assessment itself is a chain of four
**workloads** — deterministic Agent Framework workflows that contain agents — running on Azure
Container Apps:

```
use_case_screening ─(criticality)─► use_case_design ─(conformance)─► use_case_investment ─(authorisation)─► use_case_provisioning
```

Each arrow is a **human approval**. The agent never runs any of this. It holds exactly one capability:
calling governed tools on one MCP server, `workflow_mcp`, through the gateway.

Three properties shape everything below:

1. **The agent knows nothing about use cases.** Every input, every question and every approval prompt
   is served to it at run time by the tools themselves.
2. **Everything is asynchronous.** A run takes minutes and an approval can take days; no tool call ever
   waits for either.
3. **The gateway is the only door.** The agent reaches the workflow through APIM, which decides what it
   may see and call. It never holds a store credential and cannot reach a workload directly.

## 2. The parts

| Part | What it is | Where |
|---|---|---|
| **Use Case Desk (Prod)** | Copilot Studio agent (bot `880a927e-…`), Default Power Platform environment (UAE). Orchestrator picks tools by their descriptions. | Power Platform |
| **AI use case assessment (Prod)** | Custom connector, one MCP operation `InvokeMCP` (`x-ms-agentic-protocol: mcp-streamable-1.0`) at `POST /mcp/workflow_mcp/mcp`, key header `api-key` | Power Platform |
| **Connection** | Holds the team's APIM **subscription key** (bare key, no `Bearer`). The Power Platform API hub injects it on every call. | Power Platform API hub |
| **APIM** `apim-lab-prod-i4ov2m` | Production's only gateway. API `mcp-workflow-mcp` at `/mcp/workflow_mcp`. Authenticates, filters the tool listing, checks every call, swaps credentials. | Azure, UAE North |
| **workflow-frontdoor** | `workflow-mcp` server: the governed front door to every business process. Generates the process tools; hosts the approval gate tools. | Container Apps |
| **Redis Streams** | `workflow:requests`, `approvals:requests`, `approvals:decisions`, `workflow:finished`: the durable seams between conversation time and run time | Container Apps (`redis`) |
| **wf-usecase-\*** | The four workload hosts, one consumer group each on `workflow:requests` | Container Apps |
| **continuations** | Turns an approval into the next run | Container Apps |
| **teams** channel | Posts each open approval to the Teams "Approvals" channel | Container Apps → Power Automate webhook |
| **usecase-notifier** | Tells the submitter the outcome, only after an architect decided | Container Apps → webhook |
| **review app** | Web UI: submit with document upload, review approvals with their artifacts | Container Apps |
| **reference-mcp** | Governed corpus: serves the intake questionnaire (`intake-field-specs`) at a pinned version | Container Apps |

## 3. The request path

```
Teams user
  └─ Use Case Desk (Prod)                         Copilot Studio orchestrator
       └─ connector "AI use case assessment (Prod)" · operation InvokeMCP (MCP streamable HTTP)
            └─ Power Platform API hub            injects the connection's APIM subscription key
                 └─ APIM  POST /mcp/workflow_mcp/mcp      api-key: <usecase-submitter subscription key>
                      1. subscription → product "usecase-submitter" (the TEAM)
                      2. team has no grant on this server        → 403 "no grant on workflow_mcp"
                      3. tools/list → response filtered to the team's granted tools (11)
                      4. tools/call → 403 unless the tool is in the grant
                      5. strip api-key; Authorization: Bearer {{mcp-shared-secret}} (Key Vault ref)
                      6. forward; responses streamed, except a filtered listing (buffered, one event)
                 └─ workflow-frontdoor  (validates MCP_SHARED_SECRET, runs the tool)
```

The connector is a **thin MCP pipe**: Copilot Studio speaks MCP itself (initialize, `tools/list`,
`tools/call`, with the `mcp-session-id` header carried across calls), and the connector only names the
endpoint and the credential. Each tool appears in the agent as an action named and described exactly
as the server declares it.

**Identity.** APIM authenticates the **connector**, one key per team (`usecase-submitter`), not the
person. The person's identity enters only as a tool argument (`submitter` on submit, `actor` on a
decision), filled by the agent from the signed-in Teams user. See §9.

**Dev differs only in configuration.** On Railway the same connector shape points at LiteLLM's single
aggregated `/mcp` with `Authorization: Bearer <virtual key>`, and LiteLLM's per-team
`mcp_tool_permissions` does what APIM's policy does in production. The server, the tools and the
agent's behaviour are identical.

## 4. The tools the agent holds

The `usecase-submitter` team's grant on `workflow_mcp` (`deploy/grants.py` → `usecase.SUBMITTER_TOOLS`).
APIM lists exactly these 11; everything else on the server (37 tools) is invisible to the agent and
refused if called.

| Tool | Purpose | Kind |
|---|---|---|
| `use_case_screening_submit` | Queue a screening run; returns a `request_id` immediately | write (starts work) |
| `use_case_screening_fields` | The published intake questionnaire | read |
| `use_case_screening_status` / `_result` | Where a run is / its declared outputs once done | read |
| `use_case_screening_runs` | Find runs by what a person remembers (`q`, newest first) | read |
| `use_case_design_status` / `_result` / `_runs` | Follow the design half | read |
| `approvals_list` / `approvals_get` | Open approvals; one approval's question and artifacts | read |
| `approvals_decide` | Record a **human's** decision | write (releases work) |

Deliberately **absent**:

- **`use_case_design_submit` does not exist.** Design, investment and provisioning are *continuations*
  (`ProcessSpec.external = False`): their submit tool is never generated, so no grant can name it and
  no agent can be told it might try. The only way to start design is a human approving the criticality
  question. A caller may still observe them (`status`/`result`/`runs`), because a flow that cannot poll
  the run its own approval began cannot tell anyone it finished.
- **`approvals_ask`** (raising a question) belongs to the workloads' own identities, never to a
  channel's.
- **Investment and provisioning tools** are not in this team's grant; the agent follows the chain up
  to design.

## 5. How the agent knows what to ask

Three layers, none of them in the agent's configuration.

### 5.1 Tool schemas generated from the process contract

`use_case_screening` is one `ProcessSpec` in `lab.platform.contracts` (the `usecase` slice).
`workflow-mcp` generates the tools from it (`src/lab/substrate/mcp/workflow/server.py`), and each
typed input becomes a JSON-schema parameter Copilot Studio reads:

| Input | Kind | Required | In the schema |
|---|---|---|---|
| `submission` | REF | one of these two | `art://<id>/<name>` of an uploaded document |
| `submission_handle` | HANDLE | one of these two | `collab://…` handle to fetch from SharePoint/OneDrive |
| `attachments` | REF_LIST | no | supporting documents |
| `submitter` | IDENTITY | **yes** | the accountable business owner; "never invent" |
| `intake` | MAPPING | no | answers keyed by the published labels (§5.2) |
| `effort` | TABLE | no | typed rows: `role` (enum junior…exec), `headcount`, `frequency_per_week`, `current_minutes`, `expected_minutes` |
| `conversation` | CONVERSATION | no | id of the chat the request came from |
| `idempotency_key` | (every submit) | no | makes a retry return the same run (§6.3) |

A `CHOICE` becomes an `enum` and a `TABLE` a typed row model, so the agent sees closed sets and
columns instead of guessing them. `ProcessSpec.validate()` is the single validator for every surface:
MCP, REST and the review app all refuse the same things with the same messages.

### 5.2 The questionnaire is published data, served by a tool

The `intake` field declares `questions="intake-field-specs"`, an artifact in the governed reference
corpus. `use_case_screening_fields` pins that artifact at its released version, reads its
`intake-field` records through `reference-mcp`, and returns each question as
`Field · Group · Label · Type · Required · Order · Used by · Choices`. The tool's own description tells
the agent to call it **before** submitting and to use the labels verbatim, because a label nothing
published matches is accepted, stored and read by nothing.

The review app's Submit form and the intake CSV template are generated from the same artifact. So
**adding or removing a question is a corpus publish**: the Teams interview, the web form and the
template change together, and no code or agent configuration is edited.

### 5.3 Approvals carry their own question

When a run reaches a gate it stages an approval whose payload includes a `question`:

```json
{ "prompt": "Confirm the criticality class derived for this use case. …",
  "items": [ {"label": "criticality_class", "samples": ["routine", "business-critical", "safety-of-life"]},
             {"label": "justification", "samples": []} ] }
```

`approvals_get` returns it with a `summary` (including `owed`: what the work left open, worst first),
the run's artifacts and `answer_required`. The agent puts the prompt to the person and relays the
answer through `approvals_decide`, keyed by those labels: `{"criticality_class": {"tag":
"safety-of-life"}, "justification": {"tag": "…"}}`. The three gates ask:

| Gate | Raised by | Asks | Approving starts |
|---|---|---|---|
| Criticality | screening | confirm or override the derived class, with a justification | `use_case_design` |
| Conformance | design | approve or return; is every obligation bound to an enforcement point? | `use_case_investment` |
| Authorisation | investment | approve, approve with conditions, or defer; and the authority | `use_case_provisioning` |

### 5.4 The agent's instructions

The agent's prompt in Copilot Studio (template in `config/clients/copilot-studio/README.md`) shapes
the conversation: check the document says what the problem is, who has it and what changes; never
invent an owner; search by a remembered word rather than asking for an id; report the verdict, the
class and what is still open. It contains no field list; fields always come from §5.1 and §5.2.

## 6. Asynchrony

### 6.1 Why

Measured in production (4 Oct 2026): screening 7 min, design 9 min, investment and provisioning
seconds each, and three human gates in between that can take days. A Copilot Studio turn, and the
connector call inside it, must return in seconds. So every process is split into tools that each
return immediately: **submit = enqueue and acknowledge; status/result/runs = observe.**

### 6.2 The four streams

| Stream | Written by | Read by | Carries |
|---|---|---|---|
| `workflow:requests` | `_submit`, `continuations` | one consumer group per workload host | work to do |
| `approvals:requests` | a workload's `approvals_ask` | one group per channel: review app, `teams` | questions for humans |
| `approvals:decisions` | `approvals.human_decision` (every channel) | `continuations`, `usecase-notifier` | answers; the audit log |
| `workflow:finished` | a host closing a run | `meeting-notifier` (meetings) | results to announce |

Redis **Streams**, not pub/sub, because these must be durable and acknowledged:

- a consumer that crashes leaves its entry pending, and the next read **reclaims** it (XAUTOCLAIM);
- a running host holds its entry with a **heartbeat**, so a reclaim never re-runs a live run, and a
  reclaimed entry whose run already started is failed rather than started twice;
- each workload gets one consumer group, so each request is processed exactly once per process.

### 6.3 One use case, end to end (production, 4 Oct 2026)

```
 conversation (seconds)              streams                           hosts / people (minutes–days)
 agent → screening_submit ─────────► workflow:requests ──────────────► wf-usecase-screening   (7 min)
   ◄── {request_id, pending}                                              │ raises criticality question
                                     approvals:requests ──┬──────────► teams → card in "Approvals"
                                                          └──────────► review app
 agent → approvals_list / _get       (same request, read)
 person → approvals_decide ────────► approvals:decisions ─┬──────────► continuations ─► workflow:requests
                                                          │              → wf-usecase-design  (<1 s to start)
                                                          └──────────► usecase-notifier → submitter webhook
 … conformance → investment → authorisation → provisioning, the same way …
 agent → _status / _result / _runs   (pull, whenever the person asks)
```

**Retries are safe.** `_submit` takes an `idempotency_key`. The same key returns the same
`request_id` with `duplicate: true` for 24 h (`SET NX EX` on `workflow:idem:<process>:<key>`, taken
atomically with the write), so a connector or orchestrator retry never queues a second 10-minute run.
A submit **without** a key is never de-duplicated by content, deliberately: re-running a use case is
legitimate work.

**Approvals end runs; they never pause them.** A workload stages its question and finishes. Nothing
waits in a container for a human, which is why a deploy mid-chain loses nothing.

**Continuation is declared by the asker.** The approval payload carries a `continuation`
(`process`, `inputs`, `answer_input`), validated when it is built (`contracts.Continuation`): an
unknown process or input fails at staging, not when someone approves days later and nothing happens.
`continuations` releases a run only on `approve` (`decline` releases nothing; `update` keeps the
request open), exactly one run per approval, and uses the **approval id as the idempotency key**, so a
redelivered decision starts nothing new.

### 6.4 How outcomes reach people

| Path | Mechanism | Production state |
|---|---|---|
| **Pull, in the chat** | the agent calls `_status`, `_result`, `_runs` or `approvals_list` when asked | works (verified 4 Oct) |
| **Push to reviewers** | `teams` posts an Adaptive Card per **open** approval to the "Approvals" channel via a Power Automate Workflows webhook; buttons are `Action.OpenUrl` to the review app and the trace | configured |
| **Push to the submitter** | `usecase-notifier` reads **decisions**, so a rejection reaches the submitter only after an architect has decided; it carries outcome, reference and link, never the reviewer's comment | `USECASE_WEBHOOK_URL` **empty**: logs only |

The ordering rule ("an architect sees every rejection before the submitter is told", FR-12) is
structural: the notifier consumes `approvals:decisions`, so no code path can send the message before
a decision exists.

## 7. Deciding through the agent

`approvals_decide(request_id, decision, actor, comment, answer, channel)`:

- **`actor` is required and never defaulted**: the signed-in human, as the channel authenticated them.
  A blank actor is refused.
- **`channel` is recorded as `mcp:<channel>`**, so a relayed decision is never logged as one made in
  the review app.
- `approve` and `decline` are **final** and claimed atomically (`SREM` on `approvals:pending`), because
  several channels can race; `update` keeps the request open.
- Every channel (review app, agent, CLI) records through the same `approvals.human_decision`, so
  `approvals:decisions` is one audit log however the person answered.
- The tool's description forbids calling it on the agent's own initiative: it may only relay a
  decision a real person just made.

## 8. Governance at the gateway (APIM)

All rendered from the repo by `deploy/apim.py` (`apply mcp`, `apply products`, `apply models`); none
of it is hand-edited in the portal.

| Concern | Mechanism |
|---|---|
| Who the caller is | Subscription key → product = team (`grants.KEY_CALLERS`); an Entra token's `Grant.<team>` roles for agents |
| What it may reach | Per-server API policy rendered from `deploy/grants.py`: no grant → 403 at session open |
| What it may see | `tools/list` filtered to the union of the caller's grants on that server (`mcp-visible`) |
| What it may call | `tools/call` checked against the same grant → 403 "that tool is not granted" |
| What the server sees | The caller's key removed; the substrate's `MCP_SHARED_SECRET` injected from Key Vault (versionless reference, follows rotation) |
| Reachability | Servers' ingress is restricted to APIM's outbound IPs, still behind the shared secret |

**A grant change has three homes, and CI sees none of them**: the dev LiteLLM team (the provisioning
scripts), the prod APIM MCP policy (`apim.py apply mcp`), and the image. A tool added to a grant after
the last `apply mcp` is reported in production as "not exposed by gateway".

## 9. Limits and open items

| # | Limit | Consequence | Direction |
|---|---|---|---|
| 1 | **The agent cannot upload a document.** Only the review app and the upload CLI write the upload store. `submission_handle` exists for a file shared in Teams, but the screening identity holds **no `collab_fetch` grant** (deliberately: "degrade to upload it first"). | A new use case cannot be submitted end to end from Teams; the handle path fails at its first step | Decide: grant `collab_fetch` to `usecase-intake`, or stop offering the handle to the agent |
| 2 | **Nothing pushes into the chat.** A Copilot Studio agent answers only when spoken to; the `conversation` input exists but nothing delivers into a Copilot conversation | The submitter learns the outcome by asking | A registered bot (the meeting-app bot is the first in the repo) can message proactively to the originating `conversation` |
| 3 | **The submitter notifier has no destination in production** | No submitter is told anything in prod | A Power Automate flow, as for meetings; set `USECASE_WEBHOOK_URL` in `.env.azure`, then `substrate up` |
| 4 | **The actor is asserted, not proven.** APIM authenticates the connector's team key; the person is an argument the agent fills | The audit log is as trustworthy as the agent | On-behalf-of: pass the user's token through to the server (blocked on identity propagation gateway→MCP) |
| 5 | **Approval cards are send-only.** A Workflows webhook cannot receive a button press | Deciding in Teams means asking the agent, or opening the review app | A bot registration would allow `Action.Submit` |
| 6 | **Teams publication** of the prod agent depends on Copilot Studio capacity (PAYG billing plan linked 24 Sep) | The test pane and API hub are verified; the Teams channel needs confirming | Check the agent's channels |

## 10. Verifying it

- **Every listing the agent sees.** Probe the connector through the API hub with its stored
  connection: `POST <primaryRuntimeUrl>/<connectionId>/mcp/workflow_mcp/mcp` with a token for
  `https://apihub.azure.com` (a Power Apps token fails as `IDX10214`, which reads like a broken
  connection and is not). Expect 11 tools.
- **The workflow is ready.** Each workload's own preflight, as its own identity, against APIM: zero
  tokens, refuses a run whose required tools or argument schemas are missing.
- **A run end to end.** Submit with the submitter key, follow `_status`, decide each gate with
  `approvals_decide` relaying a real person's answer (`channel` names the test), and read
  `continuations`' log line `apr-… approved -> <process> wfr-…` for each hand-off.
