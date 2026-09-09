"""Publishing an agent's card — the registry PORT, its adapters, and the choice between them.

CLAUDE.md's identity claim is "one virtual key per agent; each key pairs 1:1 with an Entra app
registration and an A2A agent card". The key and the registration have existed for months; the card
never did. Measured 9 Sep 2026, `GET /v1/agents` returned `[]` — so the registry pane was empty and
the third leg was a claim the deployment could not support.

WHY THIS IS A PORT. Publication is the one part of the identity story that is genuinely
platform-specific: LiteLLM has an agent registry, APIM does not, and a deployment may reasonably want
none at all. The card itself is portable — `AgentSpec.card` renders the A2A spec, and its Entra
`securitySchemes` block is exactly what APIM's `validate-jwt` checks — so what changes between
targets is only where the card is PUT. Adding a target is one class and one line in
`AGENT_PUBLISHERS`; a deployment that configures nothing gets `NullPublisher` and is untouched.

WHY THE SUBSTRATE. `POST /v1/agents` is an ADMIN write. Verified live: an agent's own virtual key
gets `403 "Only proxy admins can create, update, or delete agents. Your role=internal_user"`. So an
agent cannot register itself — self-registration would mean handing every workload the master key,
and an agent that can register agents can register a more privileged one. Publication is therefore a
CD step (`scripts/register_agents.py`), running where the master key already lives, and this module
lives beside the other credential-holding adapters rather than in `lab.platform`.

WHAT THE LITELLM ADAPTER DOES NOT PRESERVE — measured 9 Sep 2026, after publishing five cards.
LiteLLM NORMALISES the card it serves. It keeps `name`, `description`, `version`, `skills`,
`provider` and the input/output modes, and it REPLACES three fields with its own:

  * `url` becomes `<gateway>/a2a/<agent_id>` — the endpoint this lab deliberately does not advertise,
    because its agents are in-process workflow nodes and nothing is listening there;
  * `securitySchemes` becomes `{"LiteLLMKey": http bearer}`, so the Entra `clientCredentials` block
    does not reach discovery at all;
  * `capabilities` is emptied.

So the identity a card CARRIES and the identity this registry SERVES are not the same thing today.
`AgentSpec.card` is still the portable artifact — it is the A2A spec, and its Entra block is what
APIM's `validate-jwt` checks — which is precisely why the destination is a port: a `file` adapter
writing `.well-known/agent-card.json` for a static host would serve the card unaltered, and is one
class and one line away. Recorded rather than worked around: nothing here can stop a server rewriting
what it stores, and pretending otherwise would make the next reader trust a field that is not there.

VERIFIED SAFE: no virtual key and no client secret appears on the PUBLIC hub. The key travels in
`litellm_params`, which is admin-only; the client id is an identifier and is the only identity value
that would ever have been public.

Unlike `SPEECH_PROVIDERS`, the adapters are named to a CALLABLE here rather than to a module path:
that indirection exists so a speech role never imports four vendor SDKs, and both adapters here are
stdlib `urllib`. An adapter that needs a heavy dependency should move to the lazy-module form.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Callable, Protocol, runtime_checkable

from lab.platform import config
from lab.platform.contracts import AgentSpec

__all__ = ["AgentPublisher", "LiteLLMPublisher", "NullPublisher", "AGENT_PUBLISHERS", "publisher"]

SETTING = "AGENT_REGISTRY"          # named in every refusal, so a reader knows what to set


@runtime_checkable
class AgentPublisher(Protocol):
    """Put one agent's card where discovery can find it. Returns the id it was published under, or
    "" when nothing was published."""

    def publish(self, spec: AgentSpec, card: dict, *, key: str = "",
                client_id: str = "") -> str: ...


class NullPublisher:
    """The default: publish nothing, and SAY what would have been published.

    Silence would be indistinguishable from a publisher that ran and did nothing, which is the same
    reason `meeting_notifier` logs the message it would have posted when no webhook is configured.
    """

    def publish(self, spec: AgentSpec, card: dict, *, key: str = "", client_id: str = "") -> str:
        skills = ",".join(s["id"] for s in card.get("skills") or [])
        print(f"[{SETTING} unset] would publish {spec.name} ({spec.prefix}) skills=[{skills}]",
              flush=True)
        return ""


def _http(gateway_url: str, master_key: str, timeout: float = 30.0):
    """The one transport, injected everywhere else so tests never open a socket."""
    base = gateway_url.rstrip("/")

    def request(method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            base + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {master_key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
        return json.loads(raw) if raw else {}

    return request


class LiteLLMPublisher:
    """The gateway's own agent registry: `POST /v1/agents`, reconciled by `agent_name`.

    RECONCILED, not merely created. CD runs on every push, so creating unconditionally would multiply
    agents on every deploy — and "declared once at creation and never reconciled" is the defect the
    image tag had, where a table was only the truth until the day something changed underneath it.
    """

    def __init__(self, gateway_url: str, master_key: str, *, tenant_id: str = "",
                 audience: str = "", public: bool = False, request: Callable | None = None,
                 client_to_key: dict[str, str] | None = None):
        self.tenant_id, self.audience, self.public = tenant_id, audience, public
        self._request = request or _http(gateway_url, master_key)
        self._client_to_key = dict(client_to_key or {})

    def _existing(self) -> dict[str, str]:
        rows = self._request("GET", "/v1/agents") or {}
        rows = rows if isinstance(rows, list) else (rows.get("agents") or rows.get("data") or [])
        return {r.get("agent_name", ""): (r.get("agent_id") or r.get("id") or "") for r in rows}

    def publish(self, spec: AgentSpec, card: dict, *, key: str = "", client_id: str = "") -> str:
        # BEFORE any write. `ENTRA_CLIENT_TO_KEY` is what the gateway maps a validated JWT onto a
        # virtual key with; a card claiming a different pairing would advertise an identity the
        # gateway would not honour. This is the first thing that CHECKS the lab's central identity
        # claim rather than asserting it — and an agent with no registration has nothing to
        # contradict, because ten of these are provisioned only against a live tenant.
        mapped = self._client_to_key.get(client_id) if client_id else None
        if mapped and key and mapped != key:
            raise ValueError(
                f"{spec.name}: ENTRA_CLIENT_TO_KEY maps {client_id} to a different virtual key than "
                f"{spec.prefix}_KEY holds — publishing this card would advertise an identity the "
                "gateway will not honour. Re-run the agent's provisioning script.")

        body: dict = {"agent_name": spec.name, "agent_card_params": card}
        if key:
            # SERVER-side association. The card is published to a public hub; a key is a credential.
            body["litellm_params"] = {"api_key": key, **({"model": spec.model} if spec.model else {})}
        existing = self._existing()
        agent_id = existing.get(spec.name, "")
        if agent_id:
            self._request("PATCH", f"/v1/agents/{agent_id}", body)
        else:
            created = self._request("POST", "/v1/agents", body) or {}
            agent_id = created.get("agent_id") or created.get("id") or ""
        if self.public and agent_id:
            self._request("POST", f"/v1/agents/{agent_id}/make_public", {})
        return agent_id


def _litellm(**overrides) -> AgentPublisher:
    """The ONE place this adapter is assembled; every value defaults to `lab.platform.config`."""
    def pick(name, default):
        return default if overrides.get(name) is None else overrides[name]
    return LiteLLMPublisher(
        pick("gateway_url", config.PUBLIC_GATEWAY_URL or config.GATEWAY_URL),
        pick("master_key", config.LITELLM_MASTER_KEY),
        tenant_id=pick("tenant_id", config.ENTRA_TENANT_ID),
        audience=pick("audience", config.ENTRA_GATEWAY_AUDIENCE),
        public=bool(pick("public", False)),
        request=overrides.get("request"),
        client_to_key=pick("client_to_key", config.ENTRA_CLIENT_TO_KEY))


def _null(**_overrides) -> AgentPublisher:
    return NullPublisher()


#: Where an agent card may be published. One line per target — an APIM/Foundry adapter, or a `file`
#: adapter writing `.well-known/agent-card.json` for any static host, joins here and nothing else
#: changes.
AGENT_PUBLISHERS: dict[str, Callable[..., AgentPublisher]] = {"litellm": _litellm, "none": _null}


def publisher(provider: str | None = None, **overrides) -> AgentPublisher:
    """The publisher named by `AGENT_REGISTRY`, or the null one when nothing is configured.

    No default is invented here: `lab.platform.config` owns it, because a second fallback would be a
    second home for one decision.
    """
    name = str(config.AGENT_REGISTRY if provider is None else provider or "").strip().lower()
    if not name:
        return NullPublisher()
    if name not in AGENT_PUBLISHERS:
        raise ValueError(f"unknown agent registry {name!r} — {SETTING} must be one of "
                         f"{sorted(AGENT_PUBLISHERS)}, or unset to publish nothing")
    return AGENT_PUBLISHERS[name](**overrides)
