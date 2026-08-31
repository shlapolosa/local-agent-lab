"""`model: auto` — deterministic heuristic router (a pre-call hook, like the PII guardrail).

Why not LiteLLM's native auto-router: that one is EMBEDDING-based (semantic-router: you give
example utterances per target model, incoming prompts are embedded and matched by cosine
similarity) — and Ollama Cloud offers no embedding models, so its brain has nowhere to run.
This router is rules-based instead: transparent, free, and each decision is attached to the
request metadata so it shows up in logs/traces.

Rules (first match wins):
  1. explicit override        x-auto-route hint in metadata           -> honored
  2. code or long context     code fences / >6k chars total           -> gpt-oss-120b
  3. hard-reasoning markers   "prove", "step by step", "architect",
                              "design", "analyze deeply", math-ish    -> claude-sonnet-5 (if configured)
  4. everything else          short chat, summaries, quick answers    -> glm-flash
"""
import os
import re

from litellm.integrations.custom_guardrail import CustomGuardrail

HEAVY = re.compile(r"prove|step[- ]by[- ]step|architect|design a|analy[sz]e|theorem|derive|refactor|trade-?offs", re.I)


class AutoRouter(CustomGuardrail):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        if data.get("model") != "auto":
            return data
        text = " ".join(str(m.get("content", "")) for m in data.get("messages", []) if isinstance(m, dict))
        hint = (data.get("metadata") or {}).get("x-auto-route")
        if hint:
            choice, why = hint, "caller hint"
        elif "```" in text or len(text) > 6000:
            choice, why = "gpt-oss-120b", "code or long context"
        elif HEAVY.search(text) and os.environ.get("ANTHROPIC_UPSTREAM_API_KEY"):
            choice, why = "claude-sonnet-5", "reasoning-heavy markers"
        else:
            choice, why = "glm-flash", "default: short/simple"
        data["model"] = choice
        data.setdefault("metadata", {})["auto_route"] = {"model": choice, "reason": why}
        return data
