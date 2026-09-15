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
```

Open it and check the `host` line is your gateway's public hostname. If it is empty, `.env` has no
`PUBLIC_GATEWAY_URL` and the connector would point at nothing.

### 2 · Mint the key the connection uses

```bash
set -a && source .env && set +a
GATEWAY_URL="$PUBLIC_GATEWAY_URL" .venv/bin/python scripts/provision_usecase_agents.py
grep '^USECASE_SUBMITTER_KEY=' .env
```

Idempotent: it keeps a key that already exists and mints one that does not. The key belongs to the
`usecase-submitter` team, is allowed no model at all, and carries its own budget and rate limit.

### 3 · Import the connector

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

On the **Test** tab, with the connection selected, run the `InvokeMCP` operation. A healthy answer is
the MCP handshake; an unhealthy one is a 401 (the key is wrong or has the `Bearer` missing) or a 404
(the host is wrong). Fix it here, where there is one moving part.

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
