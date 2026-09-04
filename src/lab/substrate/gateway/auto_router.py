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

The prompt text is read through the guardrail's `collect_texts` walk, so chat completions,
Anthropic messages and Responses bodies (`input` / `instructions`) are all classified.
`routes` / `classifier` can be overridden under the guardrail's `litellm_params` in the YAML
(LiteLLM passes extra keys to the constructor); the defaults are today's values — B-M3
(moving them into `litellm-config.yaml` for good) is deferred.
"""
import asyncio
import os
import re

from litellm.integrations.custom_guardrail import CustomGuardrail

from lab.substrate.gateway.pii_guardrail import collect_texts

HEAVY = re.compile(r"prove|step[- ]by[- ]step|architect|design a|analy[sz]e|theorem|derive|trade-?offs", re.I)
CODEY = re.compile(r"```|def |class |import |SELECT |function\s*\(|#!/|Traceback|error:|stack ?trace", re.I)

DEFAULT_ROUTES = {"code": "kimi-k2.7-code", "reasoning": "claude-sonnet-5", "simple": "glm-flash"}
DEFAULT_CLASSIFIER = {"model": "openai/glm-5.3-flash", "api_base": "https://ollama.com/v1", "timeout": 2.5}
CLASSIFIER_PROMPT = (
    "Classify the user request into exactly one word: code (writing, fixing, reviewing or "
    "explaining code, shell commands, configs), reasoning (architecture, deep analysis, "
    "math, multi-step planning), or simple (everything else: chat, lookups, short answers, "
    "summaries). Answer with only the single word.")


def _metadata_holder(data: dict) -> dict:
    """The metadata dict LiteLLM carries for this route: `litellm_metadata` when the proxy
    already parked one (/v1/messages, /v1/responses), else `metadata` (/v1/chat/completions)."""
    if isinstance(data.get("litellm_metadata"), dict):
        return data["litellm_metadata"]
    return data.setdefault("metadata", {})


class AutoRouter(CustomGuardrail):
    def __init__(self, routes: dict | None = None, classifier: dict | None = None, **kwargs):
        super().__init__(**kwargs)
        self.routes = {**DEFAULT_ROUTES, **(routes or {})}
        self.classifier = {**DEFAULT_CLASSIFIER, **(classifier or {})}
        self._api_key = os.environ.get("OLLAMA_API_KEY")
        self._reasoning_available = bool(os.environ.get("ANTHROPIC_UPSTREAM_API_KEY"))

    async def _classify_llm(self, text: str) -> str | None:
        if not self._api_key:
            return None
        import litellm
        try:
            r = await asyncio.wait_for(litellm.acompletion(
                model=self.classifier["model"], api_base=self.classifier["api_base"],
                api_key=self._api_key, temperature=0, max_tokens=200,
                messages=[{"role": "system", "content": CLASSIFIER_PROMPT},
                          {"role": "user", "content": text[:1500]}]),
                timeout=self.classifier["timeout"])
            word = (r.choices[0].message.content or "").strip().lower().split()[-1].strip(".")
            return word if word in self.routes else None
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
        meta = _metadata_holder(data)
        hint = meta.get("x-auto-route")
        if hint:
            choice, how = hint, "caller hint"
        else:
            text = " ".join(collect_texts(data))
            label = await self._classify_llm(text)
            how = "llm" if label else "rules"
            label = label or self._classify_rules(text)
            if label == "reasoning" and not self._reasoning_available:
                label = "code"
            choice = self.routes[label]
        data["model"] = choice
        meta["auto_route"] = {"model": choice, "method": how}
        return data
