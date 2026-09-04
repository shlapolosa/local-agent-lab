# Using the lab gateway from any client

Point any client at the gateway (`http://127.0.0.1:4000`, or your APIM URL in target state) with
an **Entra** credential. Two portable shapes, each a 1:1 APIM equivalent:

| Shape | now (LiteLLM) | target (APIM) | how to get it |
|---|---|---|---|
| Short-lived Entra JWT | validated by the gateway | `validate-jwt` policy | `az login` then `az account get-access-token` |
| Durable per-user key | virtual key | subscription key | self-serve from the gateway SSO (see below) |

Prereqs (once): `./lab.sh up` (gateway on :4000) and
`az login --tenant <LAB_TENANT_ID> --allow-no-subscriptions` (browser; az caches + refreshes).

## The two values that change per deployment — set once in `.env`, never in the templates
- **`GATEWAY_URL`**: `http://127.0.0.1:4000` for a local clone; your cloud host / APIM endpoint on
  deploy. Committed client files are `*.template.json` with `${GATEWAY_URL}` placeholders; the
  rendered `settings.json` (git-ignored) comes from `./lab.sh clients`.
- **`ENTRA_GATEWAY_AUDIENCE`** (JWT path): the lab-gateway app-id URI. A different Entra tenant
  substitutes its own in `.env` (run `scripts/entra_provision.py` + `scripts/entra_dev_provision.py`,
  then re-`az login`); the template picks it up on the next render.

## Claude Code
1. Render the settings for your environment: `./lab.sh clients` (interpolates `GATEWAY_URL`
   and `ENTRA_GATEWAY_AUDIENCE` from `.env` into `config/clients/claude-code/settings.json`). This runs
   automatically on `./lab.sh up`. Re-run it whenever the gateway moves (localhost → cloud/APIM)
   or the audience changes — the only edit is `.env`, never the committed template.
2. Copy the rendered `config/clients/claude-code/settings.json` to your project's `.claude/settings.json`
   (or `~/.claude/settings.json` for every project), then run `claude`.
- `/status` shows base URL `127.0.0.1:4000` and auth via `apiKeyHelper` — that's the gateway.
- `/model` lists all gateway models "From gateway" (needs `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`, already in the template).
- Default model is `claude-sonnet-5` (first-class tool-use). Set `ANTHROPIC_MODEL` to `auto` to
  use the gateway's intent router, or any listed model. Non-Claude models (glm/kimi/gpt-oss) are
  best-effort for Claude Code's agentic tool-use — great for chat, pick `claude-sonnet-5` for
  heavy coding. `CLAUDE_CODE_MAX_CONTEXT_TOKENS=128000` sets a safe compaction window for `auto`.
- Durable-key alternative (no `az`, no refresh): `export ANTHROPIC_BASE_URL=http://127.0.0.1:4000
  ANTHROPIC_AUTH_TOKEN=<your durable key>` and drop the `apiKeyHelper`.

## OpenCode / Codex / other harnesses
Configure a custom provider: `base_url=http://127.0.0.1:4000/v1`, apiKey/bearer = the JWT
(`az account get-access-token --resource <audience> --query accessToken -o tsv`) or a durable key.

## OpenAI-standard tools (Cursor, Continue, SDKs)
`OPENAI_BASE_URL=http://127.0.0.1:4000/v1`, `OPENAI_API_KEY=<jwt-or-durable-key>`.

## curl / browser
`curl http://127.0.0.1:4000/v1/models -H "Authorization: Bearer <jwt-or-durable-key>"`.

On first use the gateway maps your Entra identity to a personal virtual key (team `developers`);
`/v1/models` shows your allowlist, spend attributes per developer, PII pseudonymization and the
auto-router apply to every request.
