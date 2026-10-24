"""The modelling agent: our model, through our gateway, with this workload's own credential.

Its instructions and schema are the domain's (`lab.core.modelling.agent_schema`); this module only
builds the client, which is orchestration.
"""
from __future__ import annotations

import json

from agent_framework import Agent, ChatOptions
from agent_framework.openai import OpenAIChatClient
from openai import AsyncOpenAI

from lab.core.modelling import agent_schema


def instructions() -> str:
    """The prompt WITH the schema the gate validates against: one contract, shown to the model that
    must satisfy it."""
    return (f"{agent_schema.prompt()}\n\n## The schema\n\nEmit an object matching EXACTLY this JSON "
            f"Schema, using its property names verbatim.\n\n```json\n"
            f"{json.dumps(agent_schema.schema(), indent=2)}\n```\n")


def make_agent(*, credential: str, gateway_url: str, model: str, headers: dict | None = None,
               store: bool = False, timeout: float = 300.0, max_tokens: int = 32000) -> Agent:
    """Every setting arrives as an argument: the composition root reads configuration, nothing below
    it does. `store=False` because the gateway's upstream implements only the stateless Responses
    flavour. `headers` carries the traceparent, so the gateway's spans join this run's trace."""
    http = AsyncOpenAI(base_url=gateway_url.rstrip("/") + "/v1/", api_key=credential,
                       default_headers=dict(headers or {}), timeout=timeout, max_retries=3)
    client = OpenAIChatClient(model=model, api_key=credential, async_client=http)
    return Agent(client=client, name="architecture-modelling", instructions=instructions(),
                 default_options=ChatOptions(store=store, max_tokens=max_tokens))
