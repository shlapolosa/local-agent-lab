"""Reversible pseudonymization guardrail (regex tier) — the agreed PII policy.

pre_call:  every match of the configured prebuilt patterns (LiteLLM's own patterns.json —
           same library the content filter uses) is replaced by a stable placeholder
           [TYPE#n] BEFORE the prompt leaves the machine; the placeholder -> original
           mapping rides in request metadata (never sent upstream).
post_call: placeholders in the model's response are swapped back, so the caller sees real
           values while the cloud model never did. Streaming responses currently keep the
           placeholders (still safe — restoration only, no leak); buffer-based streaming
           restore is a later refinement.

Why reversible everywhere (no BLOCK): the requester already possesses the value they typed;
masking outbound + restoring inbound protects the egress boundary without breaking the
conversation ("what's wrong with card X?" still works).
"""
import json
import os
import re
from typing import Any

from litellm.integrations.custom_guardrail import CustomGuardrail

PATTERNS_JSON = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", ".venv", "lib", "python3.12",
    "site-packages", "litellm", "proxy", "guardrails", "guardrail_hooks",
    "litellm_content_filter", "patterns.json")

DEFAULT_PATTERNS = ["uae_emirates_id", "uae_phone", "street_address", "credit_card", "visa",
                    "mastercard", "amex", "iban", "email", "us_ssn", "ipv4",
                    "aws_access_key", "aws_secret_key", "github_token", "slack_token",
                    "generic_api_key"]
MAP_KEY = "pii_restore_map"


def _load_patterns(names):
    import litellm.proxy.guardrails.guardrail_hooks.litellm_content_filter as cf
    path = os.path.join(os.path.dirname(cf.__file__), "patterns.json")
    all_p = {p["name"]: p["pattern"] for p in json.load(open(path))["patterns"]}
    out = []
    for n in names:
        if n in all_p:
            out.append((n, re.compile(all_p[n])))
    return out




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

class ReversiblePII(CustomGuardrail):
    def __init__(self, pattern_names=None, **kwargs):
        kwargs.pop("patterns", None)
        super().__init__(**kwargs)
        self.patterns = _load_patterns(pattern_names or DEFAULT_PATTERNS)

    # ---- outbound: pseudonymize ----
    def _pseudo(self, text: str, mapping: dict) -> str:
        for name, rx in self.patterns:
            def repl(m):
                val = m.group(0)
                for ph, orig in mapping.items():          # stable placeholder per distinct value
                    if orig == val:
                        return ph
                ph = f"[{name.upper()}#{len(mapping) + 1}]"
                mapping[ph] = val
                return ph
            text = rx.sub(repl, text)
        return text

    def _walk(self, content, mapping):
        if isinstance(content, str):
            return self._pseudo(content, mapping)
        if isinstance(content, list):                      # anthropic/openai content parts
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    part["text"] = self._pseudo(part["text"], mapping)
            return content
        return content

    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        mapping: dict[str, str] = {}
        for msg in data.get("messages", []) or []:
            if isinstance(msg, dict) and "content" in msg:
                msg["content"] = self._walk(msg["content"], mapping)
        if mapping:
            types = {}
            for ph in mapping:
                t = ph.split("#")[0].strip("[")
                types[t] = types.get(t, 0) + 1
            _emit_event("pii", {"masked": types, "model": data.get("model")})
            # metadata key differs per route (/v1/chat uses `metadata`, /v1/messages
            # `litellm_metadata`); park the map in every carrier the post hook can see.
            data[MAP_KEY] = mapping
            for holder in ("metadata", "litellm_metadata"):
                if isinstance(data.get(holder), dict) or holder not in data:
                    data.setdefault(holder, {})[MAP_KEY] = mapping
        return data

    # ---- inbound: restore ----
    async def async_post_call_success_hook(self, data: dict, user_api_key_dict, response: Any):
        mapping = (data.get(MAP_KEY)
                   or (data.get("metadata") or {}).get(MAP_KEY)
                   or (data.get("litellm_metadata") or {}).get(MAP_KEY) or {})
        if not mapping:
            return response
        def restore(text):
            for ph, orig in mapping.items():
                text = text.replace(ph, orig)
            return text
        for choice in getattr(response, "choices", []) or []:
            msg = getattr(choice, "message", None)
            if msg is not None:
                for attr in ("content", "reasoning_content"):
                    v = getattr(msg, attr, None)
                    if isinstance(v, str):
                        setattr(msg, attr, restore(v))
        # anthropic-shaped responses: content blocks may be pydantic objects OR plain dicts,
        # and the response itself may be a dict
        blocks = getattr(response, "content", None)
        if blocks is None and isinstance(response, dict):
            blocks = response.get("content")
        for block in blocks or []:
            if isinstance(block, dict):
                if isinstance(block.get("text"), str):
                    block["text"] = restore(block["text"])
                if isinstance(block.get("thinking"), str):
                    block["thinking"] = restore(block["thinking"])
            elif isinstance(getattr(block, "text", None), str):
                block.text = restore(block.text)
        return response
