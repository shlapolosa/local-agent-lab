"""Additional offline tests for src/lab/substrate/gateway/pii_guardrail.py — the branches tests/unit/substrate/gateway/test_pii_guardrail.py
leaves open: the LiteLLM hook class itself (`ReversiblePII` pre/post hooks), `load_patterns`
failure modes, the no-LiteLLM import fallback, non-dict metadata carriers and response shapes
without text slots. No gateway, LLM or network.

Run: `.venv/bin/python tests/unit/substrate/gateway/test_pii_guardrail_more.py`  (also pytest-compatible).
"""
import asyncio
import importlib.util
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from lab.substrate.gateway import pii_guardrail as pg                      # noqa: E402

EMAIL, IBAN = "ali@example.ae", "GB82WEST12345698765432"
PG_PATH = os.path.join(ROOT, "src", "lab", "substrate", "gateway", "pii_guardrail.py")


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- load_patterns
def test_load_patterns_requires_litellm_and_ignores_unknown_names():
    real = importlib.util.find_spec
    try:
        importlib.util.find_spec = lambda name: None
        try:
            pg.load_patterns(["email"])
        except ImportError as e:
            assert "patterns.json" in str(e)
        else:
            raise AssertionError("expected ImportError without litellm")
        importlib.util.find_spec = lambda name: SimpleNamespace(origin=None)      # namespace pkg, no file
        try:
            pg.load_patterns(["email"])
        except ImportError:
            pass
        else:
            raise AssertionError("expected ImportError for a spec without origin")
    finally:
        importlib.util.find_spec = real
    pats = pg.load_patterns(["email", "no_such_pattern", "iban"])
    assert [n for n, _ in pats] == ["email", "iban"]                    # unknown names dropped, order kept
    assert all(hasattr(rx, "sub") for _, rx in pats)


def test_pure_helpers_importable_without_litellm():
    """The pure functions must load when LiteLLM is absent (portable to an APIM policy)."""
    key = "litellm.integrations.custom_guardrail"
    saved = sys.modules.get(key)
    sys.modules[key] = None                                             # None => ImportError on import
    try:
        spec = importlib.util.spec_from_file_location("pii_guardrail_nolitellm", PG_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = saved
    assert mod.CustomGuardrail is object
    m = {}
    assert mod.pseudonymize(f"mail {EMAIL}", pg.load_patterns(["email"]), m) == "mail [EMAIL#1]"
    assert mod.restore("mail [EMAIL#1]", m) == f"mail {EMAIL}"


# ---------------------------------------------------------------- carriers + response shapes
def test_park_mapping_skips_non_dict_carrier():
    mapping = {"[EMAIL#1]": EMAIL}
    body = {"metadata": "not-a-dict"}
    pg.park_mapping(body, mapping)
    assert body["metadata"] == "not-a-dict"                             # never clobbered
    assert body["litellm_metadata"] == {pg.MAP_KEY: mapping}            # absent carrier created
    assert body[pg.MAP_KEY] is mapping
    assert pg.find_mapping(body) is mapping
    assert pg.find_mapping({"metadata": None, "litellm_metadata": None}) == {}


def test_restore_response_tolerates_shapes_without_text():
    mapping = {"[EMAIL#1]": EMAIL}
    chat = SimpleNamespace(choices=[SimpleNamespace(message=None),
                                    SimpleNamespace(message=SimpleNamespace(content=None, reasoning_content="[EMAIL#1]"))])
    assert pg.restore_response(chat, mapping) is chat
    assert chat.choices[1].message.reasoning_content == EMAIL and chat.choices[1].message.content is None
    empty = SimpleNamespace(choices=None)
    assert pg.restore_response(empty, mapping) is empty
    bare = {}
    assert pg.restore_response(bare, mapping) == {}
    resp = {"output": [{"type": "reasoning", "content": "not-a-list", "arguments": None}]}
    assert pg.restore_response(resp, mapping) == {"output": [{"type": "reasoning", "content": "not-a-list", "arguments": None}]}
    assert pg._map_content(42, lambda t: "X") == 42                     # non-text content untouched


# ---------------------------------------------------------------- the LiteLLM hook class
def test_reversible_pii_hook_masks_parks_and_restores():
    hook = pg.ReversiblePII(guardrail_name="pii", event_hook="pre_call", patterns=["ignored-litellm-key"],
                            pattern_names=["email", "iban"])
    assert [n for n, _ in hook.patterns] == ["email", "iban"]
    body = {"model": "glm-flash", "messages": [{"role": "user", "content": f"mail {EMAIL} iban {IBAN}"}]}
    out = _run(hook.async_pre_call_hook(None, None, body, "completion"))
    assert out is body
    assert body["messages"][0]["content"] == "mail [EMAIL#1] iban [IBAN#2]"
    assert EMAIL not in repr(body["messages"]) and IBAN not in repr(body["messages"])
    mapping = {"[EMAIL#1]": EMAIL, "[IBAN#2]": IBAN}
    assert body["metadata"][pg.MAP_KEY] == mapping and body["litellm_metadata"][pg.MAP_KEY] == mapping
    resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="use [IBAN#2] for [EMAIL#1]",
                                                                            reasoning_content=None))])
    got = _run(hook.async_post_call_success_hook(body, None, resp))
    assert got is resp and resp.choices[0].message.content == f"use {IBAN} for {EMAIL}"


def test_reversible_pii_hook_no_pii_parks_nothing_and_defaults():
    hook = pg.ReversiblePII(guardrail_name="pii", event_hook="pre_call")
    assert [n for n, _ in hook.patterns] == [n for n in pg.DEFAULT_PATTERNS
                                             if n in dict(pg.load_patterns(pg.DEFAULT_PATTERNS))]
    body = {"model": "glm-flash", "messages": [{"role": "user", "content": "nothing sensitive"}]}
    _run(hook.async_pre_call_hook(None, None, body, "completion"))
    assert "metadata" not in body and pg.MAP_KEY not in body
    resp = {"content": [{"type": "text", "text": "[EMAIL#1] stays"}]}
    assert _run(hook.async_post_call_success_hook(body, None, resp)) is resp
    assert resp["content"][0]["text"] == "[EMAIL#1] stays"              # no mapping -> untouched


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
