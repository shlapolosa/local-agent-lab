"""The intake's two agents — OUR models, through OUR gateway, each with its OWN credential.

Two identities on purpose (`contracts.AGENTS`): the classifier SUGGESTS (rung S, writes nothing but a
suggestion), the synthesiser WRITES tagged drafts — different powers, so different keys, so a draft is
attributable to the identity that wrote it. Both compose a registered skill's SKILL.md into their
instructions (one source of truth) and are told the JSON Schema the gate will hold them to.

Every setting is an argument. The composition root reads configuration; nothing here does.
"""
from __future__ import annotations

import json
from pathlib import Path

from agent_framework import Agent, ChatOptions
from agent_framework.openai import OpenAIChatClient
from openai import AsyncOpenAI

from lab.workloads import skills

HERE = Path(__file__).resolve().parent
SKILL = {"classifier": "fabric-classification", "synthesis": "fabric-decision-record"}


def schema(kind: str) -> dict:
    name = {"classifier": "classification", "synthesis": "decision_records"}[kind]
    return json.loads((HERE / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))


def instructions(kind: str, schema_: dict | None = None) -> str:
    """The skill's text, WITH the schema it keeps telling the model to obey — a contract the model
    cannot read is not a contract (learned on the minutes agent)."""
    text = skills.text(SKILL[kind])
    if not schema_:
        return text
    return (f"{text}\n\n## The schema\n\nEmit an object matching EXACTLY this JSON Schema, property "
            f"names verbatim.\n\n```json\n{json.dumps(schema_, indent=2)}\n```\n")


def make_agent(kind: str, *, credential: str, gateway_url: str, model: str, headers: dict | None = None,
               store: bool = False, timeout: float = 300.0, max_tokens: int = 16000) -> Agent:
    """One of the two agents. `store=False`: the gateway's upstream implements only the non-stateful
    Responses flavour, so full context is resent each turn. `headers` carries the traceparent."""
    if kind not in SKILL:
        raise ValueError(f"kind must be one of {sorted(SKILL)}, not {kind!r}")
    http = AsyncOpenAI(base_url=gateway_url.rstrip("/") + "/v1/", api_key=credential,
                       default_headers=dict(headers or {}), timeout=timeout, max_retries=3)
    client = OpenAIChatClient(model=model, api_key=credential, async_client=http)
    return Agent(client=client, name=f"fabric-{kind}", instructions=instructions(kind, schema(kind)),
                 default_options=ChatOptions(store=store, max_tokens=max_tokens))


__all__ = ["make_agent", "instructions", "schema", "SKILL"]
