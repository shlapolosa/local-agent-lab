#!/usr/bin/env bash
# Register (or re-register) the archimate-adoit skill in the LiteLLM LOCAL skill store and
# scope it to a team. Usage: set -a && source .env && set +a && gateway/register_skill.sh <team_id>
# Why each step: custom_llm_provider=litellm_proxy keeps the upload local (default forwards to
# Anthropic's cloud store); ownership is 'team:<id>' because the injection hook only serves a
# skill to callers whose scopes include its created_by — team scope = every key in the process.
set -euo pipefail
TEAM="${1:?team_id required}"; ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ZIP=/tmp/archimate-adoit.zip; rm -f "$ZIP"
(cd "$ROOT/.claude/skills" && zip -qr "$ZIP" archimate-adoit -x "*/__pycache__/*" "*.pyc")
PREV=$(sed -n 's/^ARCHIMATE_SKILL_ID=//p' "$ROOT/.env")
ID=$(curl -sf -X POST "http://127.0.0.1:4000/v1/skills?beta=true" -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -F "custom_llm_provider=litellm_proxy" -F "display_title=archimate-adoit" -F "files[]=@$ZIP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
PATH="/opt/homebrew/opt/libpq/bin:$PATH" psql "$DATABASE_URL" -qtAc "update \"LiteLLM_SkillsTable\" set created_by='team:$TEAM' where skill_id='$ID';"
sed -i '' "s/^ARCHIMATE_SKILL_ID=.*/ARCHIMATE_SKILL_ID=$ID/" "$ROOT/.env"
[ -n "$PREV" ] && [ "$PREV" != "$ID" ] && curl -sf -o /dev/null -X DELETE "http://127.0.0.1:4000/v1/skills/$PREV?beta=true&custom_llm_provider=litellm_proxy" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" && echo "removed previous skill $PREV"
echo "registered $ID (owner team:$TEAM) — restart the gateway to clear the skill cache"

# --- Skill Hub (Claude Code marketplace) entry: discoverable on the UI Skills page and by
# Claude Code clients via /claude-code/marketplace.json. Path must not start with a dot,
# hence the skills/ symlink -> .claude/skills. Re-runs update in place (PUT).
HUB='{"name":"archimate-adoit","version":"0.1.0","category":"architecture",
 "source":{"source":"git-subdir","url":"file://'"$ROOT"'","path":"skills/archimate-adoit"},
 "description":"ArchiMate 3.1 architecture views as ADOIT-importable Model Exchange XML, with a deterministic layout engine (orthogonal parallel routing, layer bands, interfaces as icons) and the ADOIT:CE import procedure.",
 "author":{"name":"DOH Abu Dhabi Enterprise Architecture"},
 "keywords":["archimate","adoit","enterprise-architecture","views","model-exchange"]}'
curl -sf -X PUT "http://127.0.0.1:4000/claude-code/plugins/archimate-adoit" -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" -d "$HUB" >/dev/null \
  || curl -sf -X POST "http://127.0.0.1:4000/claude-code/plugins" -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" -d "$HUB" >/dev/null
echo "skill hub entry archimate-adoit up to date"
