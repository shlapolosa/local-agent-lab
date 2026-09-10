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
import time
import urllib.error
import urllib.request
from typing import Callable, Protocol, runtime_checkable

from lab.platform import config
from lab.platform.contracts import AgentSpec

__all__ = ["AgentPublisher", "LiteLLMPublisher", "NullPublisher", "AGENT_PUBLISHERS",
           "publisher", "retrying"]

SETTING = "AGENT_REGISTRY"          # named in every refusal, so a reader knows what to set


@runtime_checkable
class AgentPublisher(Protocol):
    """Put one agent's card where discovery can find it. Returns the id it was published under, or
    "" when nothing was published."""

    def publish(self, spec: AgentSpec, card: dict, *, key: str = "",
                client_id: str = "") -> str: ...

    def make_public(self, agent_ids: "list[str]") -> int:
        """Publish these to the unauthenticated hub, in ONE write. Returns how many."""
        ...


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

    def make_public(self, agent_ids: list[str]) -> int:
        if agent_ids:
            print(f"[{SETTING} unset] would make {len(agent_ids)} agent(s) public", flush=True)
        return 0


#: Statuses that mean "not yet", not "no". A gateway that has just been redeployed answers 502/503
#: from the edge until its container is listening, and CD publishes seconds after `substrate up`
#: returns — which deploys and does NOT wait.
TRANSIENT = (502, 503, 504)
ATTEMPTS, BACKOFF_S = 5, 4.0

#: How LiteLLM reports "that name is taken" — as a 500, not a 409. Matched on the body because the
#: status code cannot distinguish it from a gateway that is genuinely broken.
NAME_TAKEN = "unique constraint failed"


def retrying(request: Callable, *, attempts: int = ATTEMPTS, backoff: float = BACKOFF_S) -> Callable:
    """Wrap a transport so a gateway that is still starting is WAITED for, not failed on.

    Measured in CI 9 Sep 2026: the publish step ran immediately after `substrate up`, and all
    seventeen cards came back 502 because the gateway was mid-restart. A deploy that shipped the code
    correctly went red over discovery metadata that raced the rollout.

    Bounded and narrow, the same shape `deploy/railway.py:gql()` uses and for the same stated reason:
    a TRANSPORT failure is worth another try, a real error reply never is. A 400 fails immediately —
    retrying it would burn the window a 502 needs and delay the message that explains it.
    """
    def attempt(method: str, path: str, body: dict | None = None) -> dict:
        last: Exception | None = None
        for n in range(attempts):
            try:
                return request(method, path, body)
            except urllib.error.HTTPError as e:
                if e.code not in TRANSIENT:
                    raise
                last = e
            except urllib.error.URLError as e:          # connection refused while it boots
                last = e
            if n + 1 < attempts:
                print(f"  gateway not ready ({last}); retrying in {backoff:.0f}s", flush=True)
                time.sleep(backoff)
        raise last if last else RuntimeError("no attempt was made")
    return attempt


def _body_of(e: urllib.error.HTTPError) -> str:
    """The error body, once — an HTTPError's stream can only be read a single time."""
    try:
        return (e.read() or b"").decode(errors="replace")
    except Exception:                                  # noqa: BLE001 — already handling an error
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
        self._request = request or retrying(_http(gateway_url, master_key))
        self._client_to_key = dict(client_to_key or {})
        #: Agents whose row exists but which this gateway cannot see or refresh — see `publish`.
        self.already: list[str] = []

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
            try:
                created = self._request("POST", "/v1/agents", body) or {}
            except urllib.error.HTTPError as e:
                # THE ROW EXISTS AND THE GATEWAY CANNOT SEE IT. The cause was a gateway that never
                # loads agents back out of its own store, and it is FIXED in configuration —
                # `general_settings.store_model_in_db: true`, guarded by
                # tests/governance/test_agent_registry_parity.py, which is what makes
                # `_init_agents_in_db` run at all (see the note there and in litellm-config.yaml).
                #
                # This path survives as the guard for the day that setting is removed or a gateway
                # runs without it: the agent IS registered under the name we asked for, and what is
                # stale is only that gateway's view of it. Failing a deploy for that would make
                # every push red over something the push neither caused nor could fix, so it is
                # CARRIED and named. Once the reload is on, the list is truthful and this branch is
                # unreachable — a republish reconciles the existing row instead.
                if NAME_TAKEN not in (_body_of(e)).lower():
                    raise
                self.already.append(spec.name)
                print(f"  {spec.name}: already registered; this gateway cannot see it "
                      "(LiteLLM does not reload agents after a restart)", flush=True)
                return ""
            agent_id = created.get("agent_id") or created.get("id") or ""
        if agent_id and key:
            self._link_key(spec, agent_id, key)
        return agent_id

    def make_public(self, agent_ids: list[str]) -> int:
        """Put the whole registry on the public hub in ONE write.

        NOT once per agent, which is what the per-agent route would be. `make_agent_public` appends
        to `litellm.public_agent_groups` — a MODULE-LEVEL list — and then saves the entire config;
        seventeen calls are seventeen read-modify-writes of one shared value, and with
        `store_model_in_db` on, the periodic config reload overlays it from the database in between.
        Measured 9 Sep 2026: seventeen calls all returned 200 and exactly one agent ended up public.

        The bulk endpoint takes every id at once, so there is one read, one list and one save. It is
        also the reason this is a separate verb rather than a flag on `publish`: "make these public"
        is a statement about the SET, and doing it per item is what broke it.
        """
        if not (self.public and agent_ids):
            return 0
        self._request("POST", "/v1/agents/make_public", {"agent_ids": list(agent_ids)})
        return len(agent_ids)

    def _link_key(self, spec: AgentSpec, agent_id: str, key: str) -> None:
        """Point this agent's virtual key AT the agent — the third link in the identity claim.

        Not a field on the card and not `litellm_params`: an agent's `keys` are joined from a FOREIGN
        KEY on the key table (`litellm_verificationtoken.agent_id`, see LiteLLM's
        `agent_endpoints/endpoints.py`), which is why twelve freshly published agents all showed
        "Needs setup" — the card was right and nothing associated it with the key that spends.

        `litellm_params.api_key` is the credential the agent calls OUT with; this is what makes the
        agent the thing spend and grants attribute to, rather than an opaque key beside it.

        Best effort. The card is what is being published; the link is what makes it useful, and an
        agent registered but unlinked is worth strictly more than a failed deploy — so a refusal is
        reported and carried, exactly as the name conflict is.
        """
        try:
            self._request("POST", "/key/update", {"key": key, "agent_id": agent_id})
        except Exception as e:                    # noqa: BLE001 — see the docstring
            print(f"  {spec.name}: published, but its key could not be linked ({e}); "
                  "the registry will show it as needing setup", flush=True)


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
