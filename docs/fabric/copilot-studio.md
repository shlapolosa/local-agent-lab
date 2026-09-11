# The fabric's Teams agent (Copilot Studio) — connector recipe

The agent is the human surface the BRS asked for: a person asks the fabric what it knows and decides the
questions the fabric raised, from Teams. It holds no logic of its own: every answer is a governed tool call
through the gateway's MCP door under the agent's own identity, and every decision is recorded with the
signed-in person as the actor. This page is the click-through; the identity, grants and tools already exist.

## What is already provisioned (`scripts/provision_fabric_agents.py`)

| | |
|---|---|
| Identity | LiteLLM team `fabric-bot`, virtual key `FABRIC_BOT_KEY` in `.env` (no model: it calls tools, the fabric's agents do the reasoning) |
| Grant | `semantic_mcp` READ (search, similar, impact, catalog get, SPARQL, schemes) + `workflow_mcp` `approvals_list`, `approvals_get`, `approvals_decide` |
| Never | a pipeline write, `semantic_promote`, `approvals_ask` — the curator applies what the bot relays |
| Door | `https://gateway-production-120b.up.railway.app/mcp/` (streamable HTTP MCP), header `Authorization: Bearer <FABRIC_BOT_KEY>` |

The tenant holds a Copilot Studio trial (`CCIBOTS_PRIVPREV_VIRAL`, one seat in use) beside the Business
Premium seats, so the maker portal is available at https://copilotstudio.microsoft.com.

## Steps in the maker portal (about twenty minutes)

1. **Create an agent** — "Documentation Fabric". Instructions:
   > You answer questions about the organisation's architecture documentation by calling the fabric's tools,
   > and you help the signed-in person decide the review questions the fabric raised. Never invent a
   > document or a decision: if a tool returns nothing, say so. When the person decides a question, pass
   > their own identity as the actor and their words as the comment.
2. **Add the MCP server as a tool** — Tools → Add a tool → Model Context Protocol:
   - Server URL: `https://gateway-production-120b.up.railway.app/mcp/`
   - Authentication: API key, header `Authorization`, value `Bearer <FABRIC_BOT_KEY>`
   The tool list arrives from the gateway's registry, filtered by the team's grant: `semantic_search`,
   `semantic_similar`, `semantic_impact`, `semantic_catalog_get`, `semantic_query`, `approvals_list`,
   `approvals_get`, `approvals_decide` and the rest of READ.
3. **Three topics** (generative orchestration handles the rest):
   - *What do we know about …* → `semantic_search(text, limit=5)`; answer with title, type, state and the
     source link (`pointer`), never content.
   - *What is waiting for me* → `approvals_list(kind="draft-review")` and `kind="association"`, then
     `approvals_get` for the one the person picks; show the question's items and samples.
   - *Approve / decline / send back* → `approvals_decide(request_id, decision, actor=<signed-in UPN>,
     channel="teams", comment, answer={label: {"value": …}})`. The actor is the person's UPN from the
     Teams conversation — the gate refuses a blank one, and the audit log names them.
4. **Publish to Teams** (Channels → Microsoft Teams). The existing incoming-webhook cards keep arriving; the
   bot is where a person answers them.

## What happens after a decision

`approvals_decide` records the decision on the shared stream; the continuation runner sees it, the curator
applies the answer at rung H with the curator key, `artifact_publish` baselines the record, and the projector
writes the wiki page. The bot never touches any of that — which is why its grant can stay this small.

## What the POC does not do

- On-behalf-of: the bot authenticates as `fabric-bot` at the gateway; the person's identity travels as the
  `actor` argument, not as a token. Identity propagation gateway → MCP is the same open item as everywhere
  else in this lab (CLAUDE.md, provider identity).
- The bot cannot ask questions or promote; a person who wants a record re-reviewed re-runs intake.
