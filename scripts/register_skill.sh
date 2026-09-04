#!/usr/bin/env bash
# Register (or re-register) a lab skill in the LiteLLM LOCAL skill store, scope it to a team,
# and publish its Skill Hub (Claude Code marketplace) entry.
#   Usage: set -a && source .env && set +a && scripts/register_skill.sh <team_id> [skill] [env_var]
#   skill    directory under skills/  (default: archimate-adoit; .claude/skills/<name> is a symlink to it)
#   env_var  .env variable to hold the returned skill id (default: derived, see below)
# Why each step: custom_llm_provider=litellm_proxy keeps the upload local (default forwards to
# Anthropic's cloud store); ownership is 'team:<id>' because the injection hook only serves a
# skill to callers whose scopes include its created_by — team scope = every key in the process.
set -euo pipefail
TEAM="${1:?team_id required}"; SKILL="${2:-archimate-adoit}"; ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# env var: archimate-adoit keeps its historical ARCHIMATE_SKILL_ID; others -> <NAME>_SKILL_ID
if [ -n "${3:-}" ]; then ENVVAR="$3"
elif [ "$SKILL" = "archimate-adoit" ]; then ENVVAR="ARCHIMATE_SKILL_ID"
else ENVVAR="$(echo "$SKILL" | tr 'a-z-' 'A-Z_')_SKILL_ID"; fi

# per-skill Skill Hub metadata (category/description/keywords); default is generic.
case "$SKILL" in
  archimate-adoit)
    CATEGORY=architecture
    DESC="ArchiMate 3.1 architecture views as ADOIT-importable Model Exchange XML, with a deterministic layout engine (orthogonal parallel routing, layer bands, interfaces as icons) and the ADOIT:CE import procedure."
    KEYWORDS='["archimate","adoit","enterprise-architecture","views","model-exchange"]' ;;
  visio-reader)
    CATEGORY=analysis
    DESC="Read and interpret Microsoft Visio (.vsdx) diagrams into a structured, plain-language description of the system they depict (shapes with stencil hints and captions, directed connectors), ready to convert into ArchiMate."
    KEYWORDS='["visio","vsdx","business-analysis","reverse-engineering","archimate"]' ;;
  *)
    CATEGORY=general
    DESC="$SKILL skill for the local agent lab."
    KEYWORDS='["skill"]' ;;
esac

ZIP="/tmp/$SKILL.zip"; rm -f "$ZIP"
(cd "$ROOT/skills" && zip -qr "$ZIP" "$SKILL" -x "*/__pycache__/*" "*.pyc")
PREV=$(sed -n "s/^$ENVVAR=//p" "$ROOT/.env")
ID=$(curl -sf -X POST "${GATEWAY_URL:-http://127.0.0.1:4000}/v1/skills?beta=true" -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -F "custom_llm_provider=litellm_proxy" -F "display_title=$SKILL" -F "files[]=@$ZIP" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
PATH="/opt/homebrew/opt/libpq/bin:$PATH" psql "$DATABASE_URL" -qtAc "update \"LiteLLM_SkillsTable\" set created_by='team:$TEAM' where skill_id='$ID';"
if grep -q "^$ENVVAR=" "$ROOT/.env"; then sed -i '' "s/^$ENVVAR=.*/$ENVVAR=$ID/" "$ROOT/.env"; else echo "$ENVVAR=$ID" >> "$ROOT/.env"; fi
[ -n "$PREV" ] && [ "$PREV" != "$ID" ] && curl -sf -o /dev/null -X DELETE "${GATEWAY_URL:-http://127.0.0.1:4000}/v1/skills/$PREV?beta=true&custom_llm_provider=litellm_proxy" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" && echo "removed previous skill $PREV"
echo "registered $ID as $ENVVAR (owner team:$TEAM) — restart the gateway to clear the skill cache"

# --- Skill Hub (Claude Code marketplace) entry: discoverable on the UI Skills page and by
# Claude Code clients via /claude-code/marketplace.json. Path must not start with a dot —
# skills/ is the real directory (.claude/skills/<name> symlinks into it). Source = the GitHub remote when one exists
# (installable from any machine), else the local repo. Re-runs update in place (PUT).
REMOTE=$(git -C "$ROOT" remote get-url origin 2>/dev/null | sed -E 's#^git@github.com:#https://github.com/#')
SRC_URL=${REMOTE:-file://$ROOT}
HUB='{"name":"'"$SKILL"'","version":"0.1.0","category":"'"$CATEGORY"'",
 "source":{"source":"git-subdir","url":"'"$SRC_URL"'","path":"skills/'"$SKILL"'"},
 "description":"'"$DESC"'",
 "author":{"name":"DOH Abu Dhabi Enterprise Architecture"},
 "keywords":'"$KEYWORDS"'}'
curl -sf -X PUT "${GATEWAY_URL:-http://127.0.0.1:4000}/claude-code/plugins/$SKILL" -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" -d "$HUB" >/dev/null \
  || curl -sf -X POST "${GATEWAY_URL:-http://127.0.0.1:4000}/claude-code/plugins" -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" -d "$HUB" >/dev/null
echo "skill hub entry $SKILL up to date"
