"""Reversible pseudonymization guardrail (regex tier) — the agreed PII policy.

pre_call:  every match of the configured prebuilt patterns (LiteLLM's own patterns.json —
           same library the content filter uses) is replaced by a stable placeholder
           [TYPE#n] BEFORE the prompt leaves the machine; the placeholder -> original
           mapping rides in request metadata (never sent upstream).
post_call: placeholders in the model's response are swapped back, so the caller sees real
           values while the cloud model never did. Streaming responses currently keep the
           placeholders (still safe — restoration only, no leak); buffer-based streaming
           restore is a later refinement.

Covers all three API shapes on the gateway — chat completions and Anthropic messages
(`messages[*].content`) and the Responses API the agents use (`instructions`, `input` as a
string / message items / `input_text` parts / `function_call_output` tool results; output
restored in `output[*].content[*].text` and `function_call` `arguments`). `walk_request_texts`
is the ONE enumeration of where prompt text lives in a body; the auto-router reads through it too.

Why reversible everywhere (no BLOCK): the requester already possesses the value they typed;
masking outbound + restoring inbound protects the egress boundary without breaking the
conversation ("what's wrong with card X?" still works).

The pure functions below need no LiteLLM (unit-testable; portable to an APIM policy); only the
`ReversiblePII` hook class binds them to LiteLLM.
"""
import importlib.util
import json
import os
import re
from typing import Any, Callable

try:
    from litellm.integrations.custom_guardrail import CustomGuardrail
except ImportError:                       # pure helpers stay importable without LiteLLM
    CustomGuardrail = object              # type: ignore[assignment,misc]

DEFAULT_PATTERNS = ["uae_emirates_id", "uae_phone", "street_address", "credit_card", "visa",
                    "mastercard", "amex", "iban", "email", "us_ssn", "ipv4",
                    "aws_access_key", "aws_secret_key", "github_token", "slack_token",
                    "generic_api_key"]
MAP_KEY = "pii_restore_map"
Patterns = list[tuple[str, re.Pattern]]
TextFn = Callable[[str], str]


def load_patterns(names) -> Patterns:
    """The named entries of LiteLLM's prebuilt pattern library, located via the package spec
    (no import of litellm, no hardcoded site-packages path)."""
    spec = importlib.util.find_spec("litellm")
    if spec is None or not spec.origin:
        raise ImportError("litellm is not installed: its patterns.json is the PII pattern library")
    path = os.path.join(os.path.dirname(spec.origin), "proxy", "guardrails", "guardrail_hooks",
                        "litellm_content_filter", "patterns.json")
    with open(path) as f:
        all_p = {p["name"]: p["pattern"] for p in json.load(f)["patterns"]}
    return [(n, re.compile(all_p[n])) for n in names if n in all_p]


# ---- outbound: pseudonymize ----
def pseudonymize(text: str, patterns: Patterns, mapping: dict[str, str]) -> str:
    """Replace every match with a placeholder, recording placeholder -> original in `mapping`.
    A value seen before (in this text or an earlier one sharing the mapping) reuses its placeholder."""
    for name, rx in patterns:
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


def _map_content(content, fn: TextFn):
    """A message's `content`: a string, or a list of parts whose `text` carries the text."""
    if isinstance(content, str):
        return fn(content)
    if isinstance(content, list):                      # anthropic/openai content parts
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                part["text"] = fn(part["text"])
    return content


def walk_request_texts(data: dict, fn: TextFn) -> None:
    """Apply `fn` to every prompt text in a request body, writing results back in place.
    Slots: `messages[*].content` (chat completions / Anthropic messages); `instructions`,
    `input` as a string, or as a list of items whose `content` is a string or parts, or whose
    `output` is a tool result (Responses API)."""
    for msg in data.get("messages") or []:
        if isinstance(msg, dict) and "content" in msg:
            msg["content"] = _map_content(msg["content"], fn)
    if isinstance(data.get("instructions"), str):
        data["instructions"] = fn(data["instructions"])
    items = data.get("input")
    if isinstance(items, str):
        data["input"] = fn(items)
    elif isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            if "content" in item:
                item["content"] = _map_content(item["content"], fn)
            if isinstance(item.get("output"), str):     # function_call_output = tool result
                item["output"] = fn(item["output"])


def collect_texts(data: dict) -> list[str]:
    """Every prompt text in a request body, in walk order (read-only use of the same walk)."""
    out: list[str] = []

    def keep(t: str) -> str:
        out.append(t)
        return t
    walk_request_texts(data, keep)
    return out


def mask_request(data: dict, patterns: Patterns) -> dict[str, str]:
    """Pseudonymize every prompt text in `data` in place; returns the placeholder map."""
    mapping: dict[str, str] = {}
    walk_request_texts(data, lambda t: pseudonymize(t, patterns, mapping))
    return mapping


def park_mapping(data: dict, mapping: dict[str, str]) -> None:
    # metadata key differs per route (/v1/chat uses `metadata`, /v1/messages and /v1/responses
    # `litellm_metadata`); park the map in every carrier the post hook can see.
    data[MAP_KEY] = mapping
    for holder in ("metadata", "litellm_metadata"):
        if isinstance(data.get(holder), dict) or holder not in data:
            data.setdefault(holder, {})[MAP_KEY] = mapping


def find_mapping(data: dict) -> dict[str, str]:
    return (data.get(MAP_KEY)
            or (data.get("metadata") or {}).get(MAP_KEY)
            or (data.get("litellm_metadata") or {}).get(MAP_KEY) or {})


# ---- inbound: restore ----
def restore(text: str, mapping: dict[str, str]) -> str:
    for ph, orig in mapping.items():
        text = text.replace(ph, orig)
    return text


def _get(obj, key):
    """Field of a plain dict OR a pydantic object (LiteLLM hands the post hook either)."""
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def _restore_field(obj, key, mapping) -> None:
    v = _get(obj, key)
    if not isinstance(v, str):
        return
    if isinstance(obj, dict):
        obj[key] = restore(v, mapping)
    else:
        setattr(obj, key, restore(v, mapping))


def restore_response(response: Any, mapping: dict[str, str]) -> Any:
    """Swap placeholders back in every text slot of a response, whatever its API shape."""
    if not mapping:
        return response
    # chat completions
    for choice in getattr(response, "choices", []) or []:
        msg = getattr(choice, "message", None)
        if msg is not None:
            for attr in ("content", "reasoning_content"):
                _restore_field(msg, attr, mapping)
    # anthropic messages: content blocks (dicts or objects; the response itself may be a dict)
    for block in _get(response, "content") or []:
        for key in ("text", "thinking"):
            _restore_field(block, key, mapping)
    # responses API: output message parts (`output_text`) and function_call arguments
    for item in _get(response, "output") or []:
        _restore_field(item, "arguments", mapping)
        parts = _get(item, "content")
        if isinstance(parts, list):
            for part in parts:
                _restore_field(part, "text", mapping)
    return response


class ReversiblePII(CustomGuardrail):
    def __init__(self, pattern_names=None, **kwargs):
        kwargs.pop("patterns", None)
        super().__init__(**kwargs)
        self.patterns = load_patterns(pattern_names or DEFAULT_PATTERNS)

    async def async_pre_call_hook(self, user_api_key_dict, cache, data: dict, call_type):
        mapping = mask_request(data, self.patterns)
        if mapping:
            park_mapping(data, mapping)
        return data

    async def async_post_call_success_hook(self, data: dict, user_api_key_dict, response: Any):
        return restore_response(response, find_mapping(data))
