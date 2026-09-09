"""Publishing agent cards — `lab.substrate.agentregistry`.

The port exists so that publication is one of three things without touching a caller: LiteLLM today,
an APIM/Foundry or static-file adapter tomorrow, or NOTHING at all. "Nothing" is the default and the
common case: a deployment that has not configured a registry must be completely unaffected, which is
the same contract `MEETING_WEBHOOK_URL` unset already has — it logs what it would have sent.

It lives in the substrate because the LiteLLM adapter holds the MASTER key. Verified live 9 Sep 2026:
`POST /v1/agents` with an agent's own virtual key returns
`403 "Only proxy admins can create, update, or delete agents. Your role=internal_user"`. That is why
an agent cannot register itself, and why publication is a CD step rather than a startup hook — an
agent that could register agents could register a more privileged one.

Offline: a fake transport, no gateway.
"""
import json

import pytest

from lab.platform.contracts import AgentSpec
from lab.substrate import agentregistry as R

SPEC = AgentSpec(name="minutes-agent", prefix="MINUTES_AGENT",
                 description="Turns an attributed transcript into gated minutes.",
                 skills=("minutes",), model="kimi-k3", processes=("transcript_to_minutes",))
GW, TENANT, AUD = "https://gw.example", "tenant-1", "api://lab-gateway"
KEY = "sk-agent-key"


class FakeGateway:
    """A LiteLLM that remembers what it was told, so a test can assert the SHAPE of the write."""

    def __init__(self, existing=()):
        self.agents = [dict(a) for a in existing]
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method: str, path: str, body: dict | None = None) -> dict:
        self.calls.append((method, path, body or {}))
        if method == "GET" and path == "/v1/agents":
            return {"agents": self.agents}
        if method == "POST" and path == "/v1/agents":
            row = {"agent_id": f"ag-{len(self.agents)}", **(body or {})}
            self.agents.append(row)
            return row
        if method in ("PATCH", "PUT") and path.startswith("/v1/agents/"):
            return {"agent_id": path.rsplit("/", 1)[-1], **(body or {})}
        if method == "POST" and path.endswith("/make_public"):
            return {"public": True}
        raise AssertionError(f"unexpected call {method} {path}")


def litellm(fake, **kw):
    return R.LiteLLMPublisher(GW, "sk-master", tenant_id=TENANT, audience=AUD, request=fake, **kw)


# ------------------------------------------------------------------ the dispatch
def test_an_unconfigured_registry_publishes_nothing_and_says_so(capsys):
    """Unset = disabled, and LOUD about it — the idiom `meeting_notifier` uses. Silence would be
    indistinguishable from a publisher that ran and did nothing."""
    pub = R.publisher("")
    assert isinstance(pub, R.NullPublisher)
    assert pub.publish(SPEC, SPEC.card(GW, TENANT, AUD)) == ""
    out = capsys.readouterr().out
    assert "minutes-agent" in out and "AGENT_REGISTRY" in out


def test_an_unknown_registry_name_is_refused_naming_the_setting_and_the_choices():
    with pytest.raises(ValueError) as e:
        R.publisher("foundry")
    assert "AGENT_REGISTRY" in str(e.value) and "litellm" in str(e.value)


def test_adding_an_adapter_is_one_registry_line():
    """The whole point of the port: APIM, Foundry or a static `.well-known` file is one class and one
    entry, and every caller is untouched."""
    assert set(R.AGENT_PUBLISHERS) >= {"litellm", "none"}
    for name in R.AGENT_PUBLISHERS:
        assert isinstance(R.publisher(name), R.AgentPublisher), name


# ------------------------------------------------------------------ the LiteLLM adapter
def test_a_new_agent_is_created_with_its_card():
    fake = FakeGateway()
    assert litellm(fake).publish(SPEC, SPEC.card(GW, TENANT, AUD)) == "ag-0"
    (method, path, body), = [c for c in fake.calls if c[0] == "POST"]
    assert (method, path) == ("POST", "/v1/agents")
    assert body["agent_name"] == "minutes-agent"
    assert body["agent_card_params"]["name"] == "minutes-agent"


def test_republishing_UPDATES_rather_than_creating_a_second_copy():
    """CD runs on every push. Declared once at creation and never reconciled is the defect the image
    tag had — and creating instead of updating would multiply agents on every deploy."""
    fake = FakeGateway(existing=[{"agent_id": "ag-9", "agent_name": "minutes-agent"}])
    assert litellm(fake).publish(SPEC, SPEC.card(GW, TENANT, AUD)) == "ag-9"
    assert not [c for c in fake.calls if c[0] == "POST" and c[1] == "/v1/agents"]
    assert [c for c in fake.calls if c[0] in ("PATCH", "PUT")], "it must reconcile the existing one"


def test_the_virtual_key_associates_SERVER_side_and_never_on_the_card():
    """The card goes to a public hub. A key is a credential; the client id is an identifier."""
    fake = FakeGateway()
    litellm(fake).publish(SPEC, SPEC.card(GW, TENANT, AUD, client_id="abc"), key=KEY)
    body = next(c[2] for c in fake.calls if c[0] == "POST" and c[1] == "/v1/agents")
    assert KEY in json.dumps(body.get("litellm_params") or {})
    assert KEY not in json.dumps(body["agent_card_params"]), "the key reached the published card"
    assert "abc" in json.dumps(body["agent_card_params"]), "the client id is what belongs there"


def test_a_card_is_made_public_only_when_asked():
    fake = FakeGateway()
    litellm(fake).publish(SPEC, SPEC.card(GW, TENANT, AUD))
    assert not [c for c in fake.calls if c[1].endswith("/make_public")]
    litellm(fake, public=True).publish(SPEC, SPEC.card(GW, TENANT, AUD))
    assert [c for c in fake.calls if c[1].endswith("/make_public")]


def test_an_identity_pair_that_contradicts_the_lab_s_own_map_is_refused():
    """`ENTRA_CLIENT_TO_KEY` is what the gateway maps a JWT onto a virtual key with. Publishing a card
    claiming a different pairing would advertise an identity the gateway would not honour — so this
    is the first thing that ever CHECKS the lab's central identity claim instead of asserting it."""
    fake = FakeGateway()
    pub = litellm(fake, client_to_key={"abc": "sk-a-different-key"})
    with pytest.raises(ValueError, match="ENTRA_CLIENT_TO_KEY"):
        pub.publish(SPEC, SPEC.card(GW, TENANT, AUD, client_id="abc"), key=KEY, client_id="abc")
    assert not fake.calls or all(c[0] == "GET" for c in fake.calls), "it wrote before checking"


def test_a_matching_pair_publishes_normally():
    fake = FakeGateway()
    pub = litellm(fake, client_to_key={"abc": KEY})
    assert pub.publish(SPEC, SPEC.card(GW, TENANT, AUD, client_id="abc"), key=KEY, client_id="abc")


def test_an_agent_with_no_registration_is_not_checked_against_the_map():
    """Ten identities are provisioned only when an operator runs the script. An agent with no client
    id has nothing to contradict, and must still publish."""
    fake = FakeGateway()
    pub = litellm(fake, client_to_key={"abc": "sk-other"})
    assert pub.publish(SPEC, SPEC.card(GW, TENANT, AUD), key=KEY)
