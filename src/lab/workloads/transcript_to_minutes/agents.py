"""The minutes agent: OUR model, through OUR gateway, with this workload's own credential.

That is the point of the whole two-port design. The speech provider returns words and anonymous
speaker labels; what those words MEAN — what was decided, what anyone owes — is decided by a model
the lab governs, meters and traces. Keeping summarisation out of the speech port made that
structural rather than a promise.
"""
from __future__ import annotations

from pathlib import Path

from agent_framework import Agent, ChatOptions
from agent_framework.openai import OpenAIChatClient
from openai import AsyncOpenAI

HERE = Path(__file__).resolve().parent


def instructions() -> str:
    return (HERE / "prompts" / "minutes.md").read_text(encoding="utf-8")


def make_agent(*, credential: str, gateway_url: str, model: str, headers: dict | None = None,
               store: bool = False, timeout: float = 300.0, max_tokens: int = 32000) -> Agent:
    """The minutes agent. Every setting arrives as an ARGUMENT — the composition root reads
    configuration, nothing below it does, which is what keeps this workload off the env ratchet.

    `store=False` because the gateway's upstream implements only the non-stateful Responses flavour:
    a stateful turn comes back empty, so full context is resent each turn. `headers` carries the
    traceparent, so the gateway's own spans join this run's trace."""
    http = AsyncOpenAI(base_url=gateway_url.rstrip("/") + "/v1/", api_key=credential,
                       default_headers=dict(headers or {}), timeout=timeout, max_retries=3)
    client = OpenAIChatClient(model=model, api_key=credential, async_client=http)
    return Agent(client=client, name="minutes", instructions=instructions(),
                 default_options=ChatOptions(store=store, max_tokens=max_tokens))
