"""The agent registry and the A2A card it renders — `contracts.AgentSpec` / `AGENTS`.

CLAUDE.md's registry claim is "one LiteLLM team per business process; one virtual key per agent. Each
key pairs 1:1 with an Entra app registration and an A2A agent card." Two of those three legs have
existed for months. Verified live 9 Sep 2026: `GET /v1/agents` returned `[]` — the card leg had never
been built, so the Agents tab was empty and the claim was one the deployment could not support.

`AgentSpec` is the declaration; `card()` renders it. Kept PURE — dicts in, dicts out, no tenant, no
gateway — so everything below runs offline, which is also what makes the publisher's job trivial
enough to be worth trusting.
"""
import json

import pytest

from lab.platform.contracts import AGENTS, PROCESSES, AgentSpec

GW = "https://gateway.example"
TENANT = "11111111-2222-3333-4444-555555555555"
AUDIENCE = "api://lab-gateway"

SPEC = AgentSpec(name="minutes-agent", prefix="MINUTES_AGENT",
                 description="Turns an attributed meeting transcript into gated minutes.",
                 skills=("minutes",), model="kimi-k3", processes=("transcript_to_minutes",))


# ------------------------------------------------------------------ the card
def test_the_card_is_the_a2a_shape_the_gateway_asked_for():
    card = SPEC.card(GW, TENANT, AUDIENCE)
    assert card["name"] == "minutes-agent"
    assert card["description"].startswith("Turns an attributed")
    assert card["version"] and card["protocolVersion"]
    assert [s["id"] for s in card["skills"]] == ["minutes"]
    assert card["provider"]["organization"]


def test_the_url_is_the_governed_front_door_not_an_a2a_endpoint_nothing_serves():
    """The lab's agents are in-process workflow nodes — the workflow mediates between them, so
    nothing is listening on `/a2a/<id>/message/send`. Advertising an address that would fail is worse
    than advertising none, and the MCP front door is the surface that IS real and governed.

    It is also what keeps a card honest for an agent serving SEVERAL workflows: one shared address,
    the same whichever process it is acting in. See the note in the plan — a per-workflow url would
    force one card per (agent x workflow), which is a different identity model to the one the key and
    the Entra app already have.
    """
    card = SPEC.card(GW, TENANT, AUDIENCE)
    assert card["url"].startswith(GW)
    assert "/a2a/" not in card["url"], "nothing serves that endpoint; do not advertise it"


def test_the_entra_identity_travels_in_a2as_own_vocabulary():
    """`securitySchemes` is the A2A spec's own field, and OAuth2 client-credentials is exactly how
    `identity.agent_headers` authenticates. It is also what APIM's validate-jwt checks, so this block
    migrates unchanged — which is the whole reason the identity is expressed here rather than in a
    LiteLLM-shaped extension."""
    card = SPEC.card(GW, TENANT, AUDIENCE, client_id="abc-123")
    scheme = card["securitySchemes"]["entra"]
    assert scheme["type"] == "oauth2"
    flow = scheme["flows"]["clientCredentials"]
    assert TENANT in flow["tokenUrl"] and flow["tokenUrl"].startswith("https://")
    assert f"{AUDIENCE}/.default" in flow["scopes"]
    assert card["security"] == [{"entra": [f"{AUDIENCE}/.default"]}]


def test_an_agent_with_no_entra_registration_still_renders_a_card():
    """Ten of these identities are provisioned only when an operator runs the script against a live
    tenant. A card must not require that to have happened — `identity.credential_for` already falls
    back to the workload's shared credential, and discovery degrades the same way."""
    card = SPEC.card(GW, TENANT, AUDIENCE)
    assert "securitySchemes" not in card and "security" not in card
    assert card["name"] == "minutes-agent"


# ------------------------------------------------------------------ what must NEVER be on a card
@pytest.mark.parametrize("secret", ["super-secret-value", "sk-litellm-abcdef"])
def test_no_credential_of_any_kind_reaches_the_rendered_card(secret):
    """These cards are published to a PUBLIC hub (`/public/agent_hub`, unauthenticated). The client
    id is an identifier and belongs there; the client SECRET and the virtual key are credentials and
    belong nowhere near it. The key associates server-side, in `litellm_params`."""
    card = SPEC.card(GW, TENANT, AUDIENCE, client_id="abc-123")
    assert secret not in json.dumps(card)


def test_the_description_is_declared_rather_than_taken_from_a_docstring():
    """Two audiences. This codebase's docstrings carry incident history — "Measured live 9 Sep 2026:
    two of three answers lost this way" — and the hub is public. fastmcp derives tool descriptions
    from docstrings because those are written for a MODEL to read; an agent's docstring is written for
    whoever maintains it."""
    for spec in AGENTS:
        assert spec.description and not spec.description.startswith('"""')
        assert "Measured live" not in spec.description
        assert len(spec.description) < 300, f"{spec.name}: a card description, not a docstring"


# ------------------------------------------------------------------ the registry
def test_every_agent_is_uniquely_named_and_uniquely_addressed():
    """The name IS the identity — it is what `POST /v1/agents` reconciles on, so two agents sharing
    one would silently overwrite each other on every deploy."""
    names = [s.name for s in AGENTS]
    prefixes = [s.prefix for s in AGENTS]
    assert len(set(names)) == len(names), f"duplicate agent name: {sorted(names)}"
    assert len(set(prefixes)) == len(prefixes), f"duplicate env prefix: {sorted(prefixes)}"


def test_every_process_an_agent_claims_to_serve_actually_exists():
    unknown = sorted({p for s in AGENTS for p in s.processes} - set(PROCESSES))
    assert not unknown, f"agents name processes that are not registered: {unknown}"


def test_an_agent_may_serve_several_processes():
    """Not hypothetical: `usecase-agent` serves screening AND design, `usecase-delivery-agent` serves
    investment AND provisioning. A singular field would have been wrong on the day it was written."""
    assert any(len(s.processes) > 1 for s in AGENTS), "the plural field has no plural user"


def test_a_tool_only_identity_needs_no_model():
    """`meeting-agent` authenticates the transcription workload's TOOL calls; every step of that
    process is deterministic, so it holds no model and its team grants none. A card must be able to
    say that rather than invent one."""
    assert any(s.model == "" for s in AGENTS), "no tool-only identity is declared"
    toolonly = next(s for s in AGENTS if s.model == "")
    assert toolonly.card(GW, TENANT, AUDIENCE)["name"]
