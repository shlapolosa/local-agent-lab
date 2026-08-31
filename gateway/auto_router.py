"""`model: auto` — LLM-classified routing with deterministic fallback.

How it knows: a small, fast model (glm-flash on Ollama Cloud, called directly — not through
the proxy, so no recursion) reads the prompt and answers with one route label. That replaces
the embedding-based semantic router LiteLLM ships (unusable here: Ollama Cloud serves no
embedding models yet). If the classifier errors, times out (2.5 s) or answers nonsense, the
regex heuristics below decide instead — `auto` never fails because routing failed.

Routes:
  code       writing/fixing/reviewing code, shell, configs        -> kimi-k2.7-code
  reasoning  architecture, analysis, proofs, multi-step planning  -> claude-sonnet-5 (if key set)
  simple     everything else: chat, lookups, summaries            -> glm-flash
Caller override: metadata.x-auto-route = <model_name> wins outright. The decision + method
("llm" or "rules") is recorded in request metadata (visible in logs/traces).
"""
import asyncio
import os
import re

from litellm.integrations.custom_guardrail import CustomGuardrail

HEAVY = re.compile(r"prove|step[- ]by[- ]step|architect|design a|analy[sz]e|theorem|derive|trade-?offs", re.I)
CODEY = re.compile(r"```|def |class |import |SELECT |function\s*\(|#!/|Traceback|error:|stack ?trace", re.I)

ROUTES = {"code": "kimi-k2.7-code", "reasoning": "claude-sonnet-5", "simple": "glm-flash"}
CLASSIFIER_PROMPT = (
    "Classify the user request into exactly one word: code (writing, fixing, reviewing or "
    "explaining code, shell commands, configs), reasoning (architecture, deep analysis, "
    "math, multi-step planning), or simple (everything else: chat, lookups, short answers, "
    "summaries). Answer with only the single word.")




def _emit_event(kind: str, payload: dict):
    """Fail-silent event feed for the Claude Code statusline (gateway-events.jsonl)."""
    try:
        import json as _json, os as _os, time as _time
        path = _os.environ.get("GATEWAY_EVENTS_FILE") or _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "logs", "gateway-events.jsonl")
        with open(path, "a") as f:
            f.write(_json.dumps({"ts": _time.time(), "kind": kind, **payload}) + "\n")
    except Exception:
        pass

class AutoRouter(CustomGuardrail):
    async def _classify_llm(self, text: str) -> str | None:
        import litellm
        try:
            r = await asyncio.wait_for(litellm.acompletion(
                model="openai/glm-5.3-flash", api_base="https://ollama.com/v1",
                api_key=os.environ["OLLAMA_API_KEY"], temperature=0, max_tokens=200,
                messages=[{"role": "system", "content": CLASSIFIER_PROMPT},
                          {"role": "user", "content": text[:1500]}]), timeout=2.5)
            word = (r.choices[0].message.content or "").strip().lower().split()[-1].strip(".")
            return word if word in ROUTES else None
        except Exception:
            return None

    @staticmethod
    def _classify_rules(text: str) -> str:
        if CODEY.search(text) or len(text) > 6000:
            return "code"
        if HEAVY.search(text):
            return "reasoning"
        return "simple"

    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        if data.get("model") != "auto":
            return data
        hint = (data.get("metadata") or {}).get("x-auto-route")
        text = " ".join(str(m.get("content", "")) for m in data.get("messages", []) if isinstance(m, dict))
        if hint:
            choice, how = hint, "caller hint"
        else:
            label = await self._classify_llm(text)
            how = "llm" if label else "rules"
            label = label or self._classify_rules(text)
            if label == "reasoning" and not os.environ.get("ANTHROPIC_UPSTREAM_API_KEY"):
                label = "code"
            choice = ROUTES[label]
        data["model"] = choice
        data.setdefault("metadata", {})["auto_route"] = {"model": choice, "method": how}
        _emit_event("route", {"model": choice, "method": how})
        return data
