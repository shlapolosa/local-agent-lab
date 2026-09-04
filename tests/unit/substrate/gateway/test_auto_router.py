"""Offline tests for src/lab/substrate/gateway/auto_router.py — `model: auto` LLM-classified routing with regex fallback.

The direct Ollama Cloud classifier call (`litellm.acompletion`) is a fake that returns each label,
nonsense, raises, or hangs past the timeout: `auto` must never fail because routing failed, the
caller hint `metadata.x-auto-route` wins outright, and `reasoning` degrades to `code` when no
Anthropic upstream key is configured. Env is set here — never read from the real .env.

Run: `.venv/bin/python tests/unit/substrate/gateway/test_auto_router.py`  (also pytest-compatible).
"""
import asyncio
import importlib.util
import os
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
GATEWAY = os.path.join(ROOT, "src", "lab", "substrate", "gateway")

import litellm                                     # noqa: E402


def _load_like_litellm():
    """Load the hook from its file path (as LiteLLM would for a config-relative module); its sibling
    import (lab.substrate.gateway.pii_guardrail.collect_texts) resolves through the installed package."""
    spec = importlib.util.spec_from_file_location("lab_auto_router", os.path.join(GATEWAY, "auto_router.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ar = _load_like_litellm()


class FakeCompletion:
    """Records the classifier call; answers per `mode`: a label string, 'raise', or 'hang'."""
    def __init__(self, mode):
        self.mode, self.calls = mode, []

    async def __call__(self, **kw):
        self.calls.append(kw)
        if self.mode == "raise":
            raise RuntimeError("ollama down")
        if self.mode == "hang":
            await asyncio.sleep(5)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.mode))])


def _router(fake=None, *, ollama_key="ok-fake", anthropic_key="an-fake", **kw):
    for name, val in (("OLLAMA_API_KEY", ollama_key), ("ANTHROPIC_UPSTREAM_API_KEY", anthropic_key)):
        if val is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = val
    if fake is not None:
        litellm.acompletion = fake
    return ar.AutoRouter(guardrail_name="auto", event_hook="pre_call", **kw)


def run(hook, body, call_type="completion"):
    return asyncio.run(hook.async_pre_call_hook(None, None, body, call_type))


_REAL_ACOMPLETION = litellm.acompletion


def _restore():
    litellm.acompletion = _REAL_ACOMPLETION


def test_llm_label_selects_route_and_is_recorded():
    try:
        for answer, label in (("code", "code"), ("Reasoning.", "reasoning"), ("  The answer: simple", "simple"),
                              ("CODE", "code")):
            fake = FakeCompletion(answer)
            hook = _router(fake, classifier={"timeout": 1.0})
            d = run(hook, {"model": "auto", "messages": [{"role": "user", "content": "hello world"}]})
            assert d["model"] == hook.routes[label], (answer, d)
            assert d["metadata"]["auto_route"] == {"model": hook.routes[label], "method": "llm"}
        # what the classifier is asked: the configured model/base, the caller's text, no leakage
        kw = fake.calls[0]
        assert kw["model"] == ar.DEFAULT_CLASSIFIER["model"] and kw["api_base"] == ar.DEFAULT_CLASSIFIER["api_base"]
        assert kw["api_key"] == "ok-fake" and kw["temperature"] == 0
        assert kw["messages"][0] == {"role": "system", "content": ar.CLASSIFIER_PROMPT}
        assert kw["messages"][1] == {"role": "user", "content": "hello world"}
    finally:
        _restore()


def test_classifier_failures_fall_back_to_rules_never_fail():
    try:
        code_text = "```python\ndef f(): pass\n```"
        for mode in ("raise", "hang", "banana", ""):            # error / timeout / nonsense / empty answer
            fake = FakeCompletion(mode)
            hook = _router(fake, classifier={"timeout": 0.05})
            d = run(hook, {"model": "auto", "messages": [{"role": "user", "content": code_text}]})
            assert d["model"] == hook.routes["code"], mode
            assert d["metadata"]["auto_route"]["method"] == "rules", mode
            assert len(fake.calls) == 1
            d = run(hook, {"model": "auto", "messages": [{"role": "user", "content": "prove the theorem step by step"}]})
            assert d["model"] == hook.routes["reasoning"] and d["metadata"]["auto_route"]["method"] == "rules"
    finally:
        _restore()


def test_no_ollama_key_means_rules_only_without_calling_the_classifier():
    try:
        fake = FakeCompletion("code")
        hook = _router(fake, ollama_key=None)
        d = run(hook, {"model": "auto", "messages": [{"role": "user", "content": "what time is it"}]})
        assert d["model"] == hook.routes["simple"] and d["metadata"]["auto_route"]["method"] == "rules"
        assert fake.calls == []
        assert asyncio.run(hook._classify_llm("anything")) is None
    finally:
        _restore()


def test_reasoning_degrades_to_code_without_anthropic_upstream():
    try:
        fake = FakeCompletion("reasoning")
        hook = _router(fake, anthropic_key=None)
        d = run(hook, {"model": "auto", "messages": [{"role": "user", "content": "analyze the trade-offs"}]})
        assert d["model"] == hook.routes["code"]
        assert d["metadata"]["auto_route"] == {"model": hook.routes["code"], "method": "llm"}
        # with the key present the same answer routes to the reasoning model
        hook = _router(FakeCompletion("reasoning"))
        d = run(hook, {"model": "auto", "messages": [{"role": "user", "content": "analyze the trade-offs"}]})
        assert d["model"] == hook.routes["reasoning"] == "claude-sonnet-5"
        # rules path degrades too
        hook = _router(FakeCompletion("raise"), anthropic_key=None, classifier={"timeout": 0.05})
        d = run(hook, {"model": "auto", "messages": [{"role": "user", "content": "design a system"}]})
        assert d["model"] == hook.routes["code"] and d["metadata"]["auto_route"]["method"] == "rules"
    finally:
        _restore()


def test_caller_hint_wins_and_non_auto_untouched():
    try:
        fake = FakeCompletion("code")
        hook = _router(fake)
        d = run(hook, {"model": "auto", "metadata": {"x-auto-route": "gpt-oss-120b"},
                       "messages": [{"role": "user", "content": "```code```"}]})
        assert d["model"] == "gpt-oss-120b"
        assert d["metadata"]["auto_route"] == {"model": "gpt-oss-120b", "method": "caller hint"}
        assert fake.calls == []                                         # hint short-circuits the classifier
        # litellm_metadata carrier (/v1/messages, /v1/responses)
        d = run(hook, {"model": "auto", "litellm_metadata": {"x-auto-route": "glm-flash"}, "input": "x"})
        assert d["model"] == "glm-flash" and d["litellm_metadata"]["auto_route"]["method"] == "caller hint"
        assert "metadata" not in d
        # a non-auto model is passed through untouched, classifier never consulted
        body = {"model": "kimi-k3", "messages": [{"role": "user", "content": "```code```"}]}
        assert run(hook, body) is body and body["model"] == "kimi-k3" and "metadata" not in body
        assert fake.calls == []
    finally:
        _restore()


def test_long_prompt_is_code_by_rules_and_text_is_truncated_for_classifier():
    try:
        fake = FakeCompletion("simple")
        hook = _router(fake)
        text = "x" * 7000
        d = run(hook, {"model": "auto", "messages": [{"role": "user", "content": text}]})
        assert d["model"] == hook.routes["simple"] and d["metadata"]["auto_route"]["method"] == "llm"
        assert len(fake.calls[0]["messages"][1]["content"]) == 1500  # classifier sees a bounded prefix
        assert ar.AutoRouter._classify_rules(text) == "code"            # rules: > 6000 chars = code
        assert ar.AutoRouter._classify_rules("SELECT * FROM t") == "code"
        assert ar.AutoRouter._classify_rules("hi") == "simple"
    finally:
        _restore()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
