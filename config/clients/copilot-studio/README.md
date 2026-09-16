# Copilot Studio: an agent that submits and finds AI use cases

This folder holds a Power Platform **custom connector** that gives a Copilot Studio agent the lab's
use-case tools. A person in Teams or in the Copilot Studio test pane can then say "submit this as an
AI use case", "what happened to the referral triage one", "what is waiting on me" — and the agent
calls the governed gateway for each.

Read `../README.md` first for the client convention: committed templates carry `${…}` placeholders,
`./lab.sh clients` renders them, and the rendered file is never sensitive because the credential is
typed into the connection rather than written here.

## What the agent can do

Everything comes from ONE endpoint — the gateway's MCP surface — so there is no per-action plumbing
to maintain. The tools the `usecase-submitter` key is granted are:

| Tool | What a person asks for |
|---|---|
| `use_case_screening_submit` | "Submit this as an AI use case." Takes the uploaded document by reference plus the intake fields. |
| `use_case_screening_runs` | "Has anyone submitted something about referral triage?" Newest first, filtered by `q` over what each run says about itself. |
| `use_case_screening_status` | "Where has my submission got to?" |
| `use_case_screening_result` | "What did the screening find?" |
| `use_case_design_runs`, `use_case_design_status`, `use_case_design_result` | The same three for the design half, which a person follows but cannot start — approving the criticality question is what starts it. |
| `approvals_list` / `approvals_get` | "What is waiting on me?" |
| `approvals_decide` | The person's answer, recorded with THEIR name as the actor. |

Two refusals are deliberate and worth knowing before you design the conversation:

- **The agent cannot start a design, an investment or a provisioning run.** Those are continuations:
  the only correct way to start one is for a human to approve the question before it. The submit tool
  for them is not generated at all, so no prompt can talk the agent into it.
- **`approvals_decide` requires the signed-in person as `actor`.** Pass the Copilot Studio user's
  identity; a blank actor is refused, because "who approved this" is the audit trail's whole point.

## Setting it up, step by step

You need: the Power Apps maker portal and Copilot Studio in the same environment, and the submitter
key from `.env`. Fifteen minutes, and nothing here touches the lab.

### 1 · Render the connector file

```bash
./lab.sh clients          # writes config/clients/copilot-studio/usecase-connector.json
grep '"host"' config/clients/copilot-studio/usecase-connector.json
```

The host must be your gateway's PUBLIC hostname — Microsoft's cloud cannot reach `127.0.0.1`. Ignore
the `GATEWAY_URL=http://127.0.0.1:4000` the render prints: that is the local address the Claude Code
client uses, while this connector deliberately takes `PUBLIC_GATEWAY_URL`. An empty host means `.env`
has no `PUBLIC_GATEWAY_URL` and the connector would point at nothing.

### 2 · Mint the key the connection uses

```bash
set -a && source .env && set +a
GATEWAY_URL="$PUBLIC_GATEWAY_URL" .venv/bin/python scripts/provision_usecase_agents.py
grep '^USECASE_SUBMITTER_KEY=' .env
```

`GATEWAY_URL` is overridden on purpose: the script talks to the gateway it is provisioning, which is
the cloud one. **In a git worktree there is no `.venv`** — it lives in the canonical checkout, so use
`../local-agent-lab/.venv/bin/python` there (`ls -d .venv || ls -d ../local-agent-lab/.venv` settles
it). Idempotent: it keeps a key that already exists and mints one that does not. The key belongs to the
`usecase-submitter` team, is allowed no model at all, and carries its own budget and rate limit.

### 3 · Import the connector

The template declares only what the portal cannot infer: the host, the path, the protocol
annotation, the security scheme and the `Accept` header. The portal adds the rest of an agentic
operation itself — the `connectionId` path parameter, `Mcp-Session-Id`, its own `queryRequest` body,
and a `GetInvokeMCP` companion for the protocol's stream. **Do not add a body parameter**: Swagger
2.0 allows one, the portal supplies it, and a second makes the deployed definition invalid (read back
from the tenant on 16 Sep 2026, on a connector Copilot Studio could not connect to).


Power Apps maker portal → the right environment → **More** → **Discover all** → **Custom connectors**
→ **New custom connector** → **Import an OpenAPI file**.

- Name it `AI use case assessment`.
- Choose the rendered `usecase-connector.json`.
- **Continue**, then **Create connector** on the toolbar. Nothing else needs editing: the file
  carries the host, the path, the protocol annotation and the security scheme.

If the importer refuses the file, it is the file rather than the portal — say what it said, because
a valid one imports without edits.

### 4 · Create the connection

Still on the connector → the **Test** tab → **+ New connection**. It asks for one value, the API key.
Type it as:

```
Bearer sk-…            ← the whole USECASE_SUBMITTER_KEY, with the word Bearer in front
```

The word `Bearer` matters: the value is sent as the `Authorization` header verbatim.

### 5 · Prove the connection before building anything on it

First click **Update connector** — the banner means the definition you imported is not yet the one
the Test tab calls.

Then run **`InvokeMCP`** (the POST). The portal also generates a `GetInvokeMCP` for the protocol's
server-to-client stream; that one needs a session id it cannot have yet, so it is not a smoke test.

**How to fill the form.** Leave `Mcp-Session-Id` empty — the handshake is what creates one. Turn
**Raw Body** on and paste exactly this:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"power-platform-test","version":"1.0"}}}
```

(Raw Body off works too: `jsonrpc` = `2.0`, `id` = `1`, `method` = `initialize`, `params` = the
object above. Leave `result` and `error` blank — the portal offers them because they are part of the
JSON-RPC envelope, and they belong to the ANSWER, never the request.)

A healthy response is a `200` whose body is an event stream:

```
event: message
data: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18","capabilities":{…},
       "serverInfo":{"name":"litellm-mcp-server","version":"1.0.0"}}}
```

and whose headers carry an `mcp-session-id`. That is the whole point of the test: the key
authenticated, the gateway spoke MCP back.

Measured working through the API hub on 16 Sep 2026: `200`, `content-type: text/event-stream`, the
`protocolVersion` result and an `mcp-session-id` header. If you instead get `-32602 Validation error
… Field required: method`, the transport is fine and the BODY is empty — that error is the MCP server
parsing what you sent, which means everything before it worked.

**If the Test tab keeps answering 406, go to step 7 anyway.** That tab is a generic HTTP harness: it
does not speak MCP, and what it puts in `Accept` is its own business — measured 15 Sep 2026, the API
hub forwarded a request the gateway refused even with the header declared as a parameter. Copilot
Studio's MCP runtime performs the handshake itself and sets its own headers, so the tool list in step
7 is the test that decides whether this works. (For the record, the gateway accepts
`application/json, text/event-stream` in either order and with a `q=` weight, and refuses `*/*` —
both types must be named.)

**Do not try `tools/list` here.** It needs the session id from this response AND an
`initialized` notification first; the Test tab has no way to keep a session between calls. Copilot
Studio does that handshake itself, which is why step 7 shows the tools and this tab never will.

The three failures worth recognising:

| What you see | What it means |
|---|---|
| **406 — "Client must accept both application/json and text/event-stream"** | The `Accept` header is not being sent. `produces` alone is NOT enough — the runtime does not derive the header from it — so the definition declares `Accept` as an internal header parameter defaulting to both types. Re-render, re-import, **Update connector**. If the response headers say `x-ms-apihub-cached-response: true`, you are being served the previous failure: change the `id` in the body and test again. |
| **401** | The key is wrong, or the connection value is missing the word `Bearer`. |
| **404** | The host is wrong — check step 1. |

### 6 · Create the agent

Copilot Studio → **Create** → **New agent** → name it *Use case desk* (or your own), and give it
instructions. A starting point that matches what the tools actually do:

> You help colleagues submit AI use cases for assessment and find ones already submitted.
>
> Before submitting, check the document says three things: what the problem is, who has it, and what
> changes if it works. Those are what the assessment's first step needs; without them it will ask
> anyway and the run is wasted.
>
> Never invent an accountable owner. If the submission names nobody, say so and ask who it is.
>
> When someone asks about a use case they cannot name precisely, search by a word they remember
> rather than asking them for an id — they will not have one.
>
> When you report an outcome, give the verdict, the criticality class and the review link, and then
> say plainly what is still open. A design that reads well is not a design that is complete.

### 7 · Add the connector as a tool

Agent → **Tools** → **Add a tool** → **Model Context Protocol** → your connector → the connection
from step 4 → **Add to agent**.

Every tool the key is granted appears at once; the agent picks by description. You should see ten:
three for screening plus its search, three for the design half, and the three approval tools.

### 8 · Test it in the pane

Ask, in order:

1. *"What AI use cases have been submitted?"* — exercises `use_case_screening_runs` with no filter.
2. *"Anything about referral triage?"* — the same tool with `q`, which is the search a person
   actually performs.
3. *"What is waiting on me?"* — `approvals_list`.

Submitting needs a document in the upload store first, so test that last and with a real reference
(see *What it cannot do* below).

### 9 · Publish

Agent → **Publish**, then **Channels** → **Teams + Microsoft 365** to put it in front of colleagues.
Publishing to Teams requires Copilot Studio capacity in the tenant; without it the agent still works
in the test pane and through any channel the licence does allow.

### Reading back what is actually deployed

The portal shows you what you typed; this shows what the tenant has. Useful when a connector works in
one place and not another, because the deployed definition is the one both of them use:

```bash
TOK=$(az account get-access-token --resource https://service.powerapps.com/ --query accessToken -o tsv)
ENV=Default-<your tenant id>          # the environment id from the maker portal URL
API=shared_<your connector id>        # likewise
curl -s -H "Authorization: Bearer $TOK" \
  "https://api.powerapps.com/providers/Microsoft.PowerApps/apis/$API?api-version=2016-11-01&\$filter=environment%20eq%20'$ENV'&\$expand=properties.swagger" \
  | python3 -c "import json,sys; d=json.load(sys.stdin)['properties']; print(json.dumps(d['swagger'], indent=1))"
```

`az login` against the same tenant first. What to look at: `produces`, the operation's `parameters`
(how many are `in: body` — more than one is invalid), and `securityDefinitions`.

### Rotating or revoking

Re-run step 2 after deleting `USECASE_SUBMITTER_KEY` from `.env` to mint a fresh key, then update the
connection in Power Apps. Revoking the key stops this surface and nothing else, which is the reason
it has its own.

## What it costs and what it cannot do

The key carries its own budget and rate limit, and every call is metered against the
`usecase-submitter` team, so this surface cannot quietly spend an assessment agent's budget. It
holds no store credential: a submission reaches the lab as an `art://` reference, and the lab fetches
the bytes itself through its own governed store.

Uploading the document is not part of this connector. A person uploads on the review app's Submit
page, or a Power Automate flow stages the file and passes the reference — the same split the meeting
flow uses, and for the same reason: a connector that could read the tenant's files would be a much
larger thing to trust than one that can start a run.
