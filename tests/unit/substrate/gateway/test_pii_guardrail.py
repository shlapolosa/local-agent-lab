"""Offline tests for the gateway security tier (review B wave-1a).

Pins: (1) reversible pseudonymisation round-trips and gives a repeated value ONE placeholder;
(2) chat-completions masking is unchanged; (3) Responses-API bodies (`input` as a string, as a
list of items, with `input_text` parts, `function_call_output` tool results, `instructions`)
are masked — the test that would have caught B-H1; (4) Responses output is restored;
(5) the auto-router sees Responses text and routes it; (6) mcpauth logs a fingerprint, never
the token. No gateway, LLM or network: the router's LLM classifier is stubbed.

Run: `.venv/bin/python tests/unit/substrate/gateway/test_pii_guardrail.py`  (also pytest-compatible).
"""
import asyncio
import contextlib
import copy
import hashlib
import io
import re
import sys
from types import SimpleNamespace


from lab.substrate.gateway import pii_guardrail as pg
from lab.substrate.gateway.pii_guardrail import (collect_texts, find_mapping, load_patterns, mask_request,  # noqa: E402
                           park_mapping, pseudonymize, restore, restore_response,
                           walk_request_texts)

PATTERNS = load_patterns(pg.DEFAULT_PATTERNS)
EMAIL, IBAN, CARD = "ali@example.ae", "GB82WEST12345698765432", "4111 1111 1111 1111"
SENTENCE = f"Contact {EMAIL} about IBAN {IBAN} or card {CARD}; again {EMAIL}."


def _mask(text, mapping):
    return pseudonymize(text, PATTERNS, mapping)


# ---------------------------------------------------------------- (1) round-trip
def test_roundtrip_and_stable_placeholders():
    mapping = {}
    masked = _mask(SENTENCE, mapping)
    assert EMAIL not in masked and IBAN not in masked and CARD not in masked, masked
    # numbering follows pattern order (credit_card < iban < email), not text order
    email_ph = [p for p in re.findall(r"\[[A-Z_]+#\d+\]", masked) if p.startswith("[EMAIL#")]
    assert len(email_ph) == 2 and len(set(email_ph)) == 1, masked   # repeated value -> ONE placeholder
    assert "[IBAN#" in masked and "[CREDIT_CARD#" in masked, masked
    assert len(mapping) == 3, mapping                        # 3 distinct values, 3 placeholders
    assert restore(masked, mapping) == SENTENCE
    # a second text in the same request reuses the placeholder from the first
    assert _mask(f"cc {EMAIL}", mapping) == f"cc {email_ph[0]}"
    assert len(mapping) == 3


def test_no_pii_means_no_mapping():
    body = {"messages": [{"role": "user", "content": "plain text, no secrets"}]}
    assert mask_request(body, PATTERNS) == {}
    assert body["messages"][0]["content"] == "plain text, no secrets"


# ---------------------------------------------------------------- (2) chat completions unchanged
def test_chat_completions_masked_as_before():
    body = {"model": "glm-flash",
            "messages": [{"role": "system", "content": "You help."},
                         {"role": "user", "content": f"mail {EMAIL}"},
                         {"role": "user", "content": [{"type": "text", "text": f"iban {IBAN}"},
                                                      {"type": "image_url", "image_url": {"url": "data:..."}}]}]}
    expect = copy.deepcopy(body)
    mapping = mask_request(body, PATTERNS)
    assert body["messages"][0]["content"] == "You help."
    assert body["messages"][1]["content"] == "mail [EMAIL#1]"
    assert body["messages"][2]["content"][0]["text"] == "iban [IBAN#2]"
    assert body["messages"][2]["content"][1] == expect["messages"][2]["content"][1]   # non-text part untouched
    assert mapping == {"[EMAIL#1]": EMAIL, "[IBAN#2]": IBAN}
    # the map is parked in every carrier the post hook can see (metadata vs litellm_metadata)
    park_mapping(body, mapping)
    assert body["metadata"][pg.MAP_KEY] is mapping and body["litellm_metadata"][pg.MAP_KEY] is mapping
    assert find_mapping({"litellm_metadata": {pg.MAP_KEY: mapping}}) is mapping
    assert find_mapping({"metadata": {pg.MAP_KEY: mapping}}) is mapping
    assert find_mapping({}) == {}


# ---------------------------------------------------------------- (3) Responses API request (B-H1)
def test_responses_input_string_and_instructions():
    body = {"model": "kimi-k3", "instructions": f"The BA is {EMAIL}", "input": f"card {CARD}"}
    mapping = mask_request(body, PATTERNS)
    assert body["instructions"] == "The BA is [EMAIL#1]"
    assert body["input"] == "card [CREDIT_CARD#2]"
    assert mapping == {"[EMAIL#1]": EMAIL, "[CREDIT_CARD#2]": CARD}


def test_responses_input_items_parts_and_tool_results():
    body = {"model": "kimi-k3",
            "input": [{"role": "user", "content": f"plain {EMAIL}"},
                      {"type": "message", "role": "user",
                       "content": [{"type": "input_text", "text": f"parts {IBAN}"},
                                   {"type": "input_image", "image_url": "data:image/png;base64,AAAA"}]},
                      {"type": "function_call", "call_id": "c1", "name": "storage_get",
                       "arguments": '{"ref": "art://1/doc.md"}'},
                      {"type": "function_call_output", "call_id": "c1", "output": f"doc says {EMAIL} / {CARD}"}]}
    mapping = mask_request(body, PATTERNS)
    items = body["input"]
    assert items[0]["content"] == "plain [EMAIL#1]"
    assert items[1]["content"][0]["text"] == "parts [IBAN#2]"
    assert items[1]["content"][1] == {"type": "input_image", "image_url": "data:image/png;base64,AAAA"}
    assert items[2]["arguments"] == '{"ref": "art://1/doc.md"}'      # no PII -> untouched
    assert items[3]["output"] == "doc says [EMAIL#1] / [CREDIT_CARD#3]"   # tool result masked, email reused
    assert set(mapping) == {"[EMAIL#1]", "[IBAN#2]", "[CREDIT_CARD#3]"}
    # nothing else in the body is touched and no PII survives anywhere in it
    assert EMAIL not in repr(body) and IBAN not in repr(body) and CARD not in repr(body)


def test_walk_ignores_non_text_shapes():
    body = {"messages": [{"role": "user"}, "junk", {"role": "user", "content": None}],
            "input": [42, {"type": "function_call_output", "output": {"nested": "dict"}}],
            "instructions": None}
    walk_request_texts(body, lambda t: "X")
    assert body == {"messages": [{"role": "user"}, "junk", {"role": "user", "content": None}],
                    "input": [42, {"type": "function_call_output", "output": {"nested": "dict"}}],
                    "instructions": None}


# ---------------------------------------------------------------- (4) Responses output restored
def test_responses_output_restored_objects_and_dicts():
    mapping = {"[EMAIL#1]": EMAIL, "[IBAN#2]": IBAN}
    # pydantic-like objects (attribute access), as LiteLLM hands them to the post hook
    obj = SimpleNamespace(output=[
        SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text", text="write to [EMAIL#1]"),
                                                 SimpleNamespace(type="refusal", refusal="[EMAIL#1]")]),
        SimpleNamespace(type="function_call", name="lookup", arguments='{"iban": "[IBAN#2]"}'),
        SimpleNamespace(type="reasoning", content=None)])
    out = restore_response(obj, mapping)
    assert out is obj
    assert obj.output[0].content[0].text == f"write to {EMAIL}"
    assert obj.output[0].content[1].refusal == "[EMAIL#1]"          # only text fields are restored
    assert obj.output[1].arguments == f'{{"iban": "{IBAN}"}}'
    # plain-dict shape
    d = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "[IBAN#2] ok"}]}]}
    restore_response(d, mapping)
    assert d["output"][0]["content"][0]["text"] == f"{IBAN} ok"
    # chat-completions + anthropic shapes still restore
    chat = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="hi [EMAIL#1]",
                                                                             reasoning_content=None))])
    restore_response(chat, mapping)
    assert chat.choices[0].message.content == f"hi {EMAIL}"
    anth = {"content": [{"type": "text", "text": "[EMAIL#1]"}, {"type": "thinking", "thinking": "[IBAN#2]"}]}
    restore_response(anth, mapping)
    assert anth["content"] == [{"type": "text", "text": EMAIL}, {"type": "thinking", "thinking": IBAN}]
    assert restore_response(chat, {}) is chat


# ---------------------------------------------------------------- (5) auto-router text walk
def test_collect_texts_covers_every_shape():
    body = {"messages": [{"role": "user", "content": "m1"},
                         {"role": "user", "content": [{"type": "text", "text": "m2"}]}],
            "instructions": "i", "input": [{"role": "user", "content": "r1"},
                                           {"type": "function_call_output", "output": "t1"}]}
    assert collect_texts(body) == ["m1", "m2", "i", "r1", "t1"]
    assert collect_texts({"input": "just a string"}) == ["just a string"]


def test_auto_router_routes_responses_body():
    from lab.substrate.gateway import auto_router

    class Rules(auto_router.AutoRouter):          # LLM classifier stubbed: no network
        async def _classify_llm(self, text):
            return None

    class Llm(auto_router.AutoRouter):
        async def _classify_llm(self, text):
            self.seen = text
            return "code"

    hook = Rules(guardrail_name="t", event_hook="pre_call")
    run = lambda h, d: asyncio.run(h.async_pre_call_hook(None, None, d, "aresponses"))   # noqa: E731
    # Responses body with code-shaped text: the walker must feed it to the rules
    d = run(hook, {"model": "auto", "input": [{"role": "user", "content": [
        {"type": "input_text", "text": "```python\ndef f(): pass\n```"}]}]})
    assert d["model"] == hook.routes["code"], d
    assert d["metadata"]["auto_route"] == {"model": hook.routes["code"], "method": "rules"}
    # Responses body where LiteLLM already parked litellm_metadata: decision lands there
    d = run(hook, {"model": "auto", "litellm_metadata": {}, "input": "hello there"})
    assert d["model"] == hook.routes["simple"] and d["litellm_metadata"]["auto_route"]["method"] == "rules"
    assert "metadata" not in d
    # caller hint wins; non-auto untouched
    d = run(hook, {"model": "auto", "metadata": {"x-auto-route": "glm-flash"}, "input": "```code```"})
    assert d["model"] == "glm-flash" and d["metadata"]["auto_route"]["method"] == "caller hint"
    assert run(hook, {"model": "kimi-k3", "input": "x"})["model"] == "kimi-k3"
    # LLM label path, and the walker's text is what the classifier sees
    llm = Llm(guardrail_name="t", event_hook="pre_call")
    d = run(llm, {"model": "auto", "instructions": "sys", "input": "user"})
    assert llm.seen == "sys user" and d["model"] == llm.routes["code"]
    assert d["metadata"]["auto_route"]["method"] == "llm"
    # litellm_params overrides (B-M3 seam) with the hardcoded values as defaults
    custom = Rules(guardrail_name="t", event_hook="pre_call", routes={"simple": "other"},
                   classifier={"timeout": 1.0})
    assert custom.routes == {**auto_router.DEFAULT_ROUTES, "simple": "other"}
    assert custom.classifier == {**auto_router.DEFAULT_CLASSIFIER, "timeout": 1.0}
    assert auto_router.AutoRouter._classify_rules("prove the theorem step by step") == "reasoning"
    assert auto_router.AutoRouter._classify_rules("what time is it") == "simple"


# ---------------------------------------------------------------- (6) mcpauth fingerprint
def test_mcpauth_logs_fingerprint_not_token():
    from lab.substrate.mcpauth import BearerAuthMiddleware, fingerprint
    token = "Bearer super-secret-token-value-1234567890"
    assert fingerprint(token) == hashlib.sha256(token.encode()).hexdigest()[:8]
    assert len(fingerprint("")) == 8

    calls = []

    async def app(scope, receive, send):
        calls.append("app")

    async def send(msg):
        calls.append(msg)

    mw = BearerAuthMiddleware(app, secret="right")
    scope = lambda auth: {"type": "http", "method": "POST", "path": "/mcp",   # noqa: E731
                          "headers": [(b"authorization", auth.encode())]}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        asyncio.run(mw(scope(token), None, send))
    assert calls[0]["status"] == 401 and "app" not in calls
    log = buf.getvalue()
    assert "super-secret" not in log and "Bearer" not in log, log
    assert f"auth=sha256:{fingerprint(token)}" in log and f"len={len(token)}" in log, log
    calls.clear()
    asyncio.run(mw(scope("Bearer right"), None, send))
    assert calls == ["app"]
    open_mw = BearerAuthMiddleware(app, secret="x")
    open_mw.secret = None                               # `secret=None` would fall back to the env
    asyncio.run(open_mw({"type": "http", "headers": []}, None, send))
    assert calls == ["app", "app"]                      # no secret configured -> open


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
