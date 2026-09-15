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
| `use_case_design_runs` / `_status` / `_result` | The same three for the design half, which a person follows but cannot start — approving the criticality question is what starts it. |
| `approvals_list` / `approvals_get` | "What is waiting on me?" |
| `approvals_decide` | The person's answer, recorded with THEIR name as the actor. |

Two refusals are deliberate and worth knowing before you design the conversation:

- **The agent cannot start a design, an investment or a provisioning run.** Those are continuations:
  the only correct way to start one is for a human to approve the question before it. The submit tool
  for them is not generated at all, so no prompt can talk the agent into it.
- **`approvals_decide` requires the signed-in person as `actor`.** Pass the Copilot Studio user's
  identity; a blank actor is refused, because "who approved this" is the audit trail's whole point.

## Setting it up

1. **Render the template.** `./lab.sh clients` writes `usecase-connector.json` beside this file with
   your gateway's host in it.
2. **Import it.** Power Apps → *Custom connectors* → *New* → *Import an OpenAPI file*, and choose the
   rendered `usecase-connector.json`.
3. **Create the connection** with the `usecase-submitter` virtual key, typed as `Bearer sk-…`. Mint
   or rotate that key with `scripts/provision_usecase_agents.py`; it is `USECASE_SUBMITTER_KEY` in
   `.env`. Give the connector its own key rather than sharing an agent's: the spend, the rate limit
   and the grants are then this surface's own, and revoking it costs nobody else anything.
4. **Add it to the agent.** Copilot Studio → your agent → *Tools* → *Add a tool* → *Model Context
   Protocol* → the connector. Every granted tool appears; the agent picks by description.
5. **Say what the agent is for** in its instructions. Something close to:
   > You help colleagues submit AI use cases for assessment and find ones already submitted. Before
   > submitting, make sure the document says what the problem is, who has it, and what changes if it
   > works — those three are what the assessment's first step needs. Never guess an accountable
   > owner: if the submission names nobody, say so and ask. When you report an outcome, give the
   > verdict, the criticality class and the review link, and say plainly what is still open.

## What it costs and what it cannot do

The key carries its own budget and rate limit, and every call is metered against the
`usecase-submitter` team, so this surface cannot quietly spend an assessment agent's budget. It
holds no store credential: a submission reaches the lab as an `art://` reference, and the lab fetches
the bytes itself through its own governed store.

Uploading the document is not part of this connector. A person uploads on the review app's Submit
page, or a Power Automate flow stages the file and passes the reference — the same split the meeting
flow uses, and for the same reason: a connector that could read the tenant's files would be a much
larger thing to trust than one that can start a run.
