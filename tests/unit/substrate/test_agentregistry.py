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


# ------------------------------------------------------------------ a gateway that is still starting
class Flaky:
    """A gateway that 502s while it boots, then answers. Exactly what CD saw."""

    def __init__(self, fails: int):
        self.fails, self.seen = fails, 0

    def __call__(self, method, path, body=None):
        import urllib.error
        self.seen += 1
        if self.seen <= self.fails:
            raise urllib.error.HTTPError(path, 502, "Bad Gateway", {}, None)  # type: ignore[arg-type]
        return {"agents": []} if method == "GET" else {"agent_id": "ag-1"}


def test_a_gateway_that_is_still_booting_is_waited_for_not_failed_on():
    """Measured in CI 9 Sep 2026: the publish step ran straight after `substrate up`, which deploys
    and RETURNS — so all seventeen cards hit a gateway mid-restart and every one reported 502. A
    deploy that ships code correctly must not go red because discovery metadata raced the rollout.

    Bounded, and only for transient statuses: `railway.py`'s own `gql()` retries transport failures
    for the same reason, and refuses to retry a real error reply.
    """
    fake = Flaky(fails=2)
    pub = R.LiteLLMPublisher(GW, "sk-master", request=R.retrying(fake, attempts=4, backoff=0.0))
    assert pub.publish(SPEC, SPEC.card(GW, TENANT, AUD)) == "ag-1"
    assert fake.seen > 2, "it gave up before the gateway came back"


def test_a_real_refusal_is_not_retried():
    """A 400 is the gateway saying the request is WRONG. Retrying it burns the window a 502 needs and
    delays the message that would explain it."""
    import urllib.error

    calls = []

    def refuses(method, path, body=None):
        calls.append(path)
        raise urllib.error.HTTPError(path, 400, "Bad Request", {}, None)  # type: ignore[arg-type]

    with pytest.raises(urllib.error.HTTPError):
        R.retrying(refuses, attempts=4, backoff=0.0)("GET", "/v1/agents")
    assert len(calls) == 1, "a 400 must fail immediately"


def test_giving_up_reports_the_last_failure_rather_than_a_shrug():
    fake = Flaky(fails=99)
    with pytest.raises(Exception) as e:
        R.retrying(fake, attempts=2, backoff=0.0)("GET", "/v1/agents")
    assert "502" in str(e.value)


# --------------------------------------- an agent the registry has forgotten but the DB still holds
def test_an_agent_the_list_cannot_see_but_the_database_still_holds_is_not_a_failure():
    """The defect this survives, root-caused live 9 Sep 2026 against LiteLLM v1.98.0.

    `GET /v1/agents` is served from an IN-MEMORY registry populated on write, and it is not reloaded
    from Postgres when the gateway restarts. So after every redeploy the list answers `200 []` while
    the rows are still there — proven by `POST` then failing with
    `500 "Unique constraint failed on the fields: (agent_name)"`, and by the row count in
    `LiteLLM_AgentsTable`.

    Reconcile-by-name reads that list, so it decides to CREATE and hits the constraint. The agent IS
    registered under the name we wanted; what is broken is the gateway's view of it. Failing the
    deploy for that would make every push red for a condition CD cannot fix and did not cause — so it
    is reported and carried, and `publish` says which agents were in that state.
    """
    import urllib.error

    def conflicts(method, path, body=None):
        if method == "GET":
            return {"agents": []}                      # the empty view a restart leaves behind
        raise urllib.error.HTTPError(
            path, 500, "Internal Server Error", {},                      # type: ignore[arg-type]
            __import__("io").BytesIO(
                b'{"detail":"Error adding agent to DB: Unique constraint failed on the fields: '
                b'(`agent_name`)"}'))

    pub = R.LiteLLMPublisher(GW, "sk-master", request=conflicts)
    assert pub.publish(SPEC, SPEC.card(GW, TENANT, AUD)) == ""
    assert SPEC.name in pub.already, "it must say which agents it could not refresh"


def test_a_500_that_is_not_a_name_conflict_still_fails():
    """Carrying the conflict must not become swallowing every server error — a gateway that is
    genuinely broken has to reach the deploy log."""
    import urllib.error

    def broken(method, path, body=None):
        if method == "GET":
            return {"agents": []}
        raise urllib.error.HTTPError(path, 500, "Internal Server Error", {},   # type: ignore[arg-type]
                                     __import__("io").BytesIO(b'{"detail":"database is on fire"}'))

    pub = R.LiteLLMPublisher(GW, "sk-master", request=broken)
    with pytest.raises(urllib.error.HTTPError):
        pub.publish(SPEC, SPEC.card(GW, TENANT, AUD))


# ------------------------------------------------------------------ agent <-> key, the third link
def test_publishing_links_the_agents_virtual_key_to_it():
    """Without this every agent shows "Needs setup", and the claim that spend attributes per AGENT is
    not true — it attributes per key, with nothing joining the two.

    The association is a FOREIGN KEY on the key table, not a field on the card: `endpoints.py`
    populates an agent's `keys` from `litellm_verificationtoken.agent_id`. So the key row has to
    point at the agent, and `/key/update` takes `agent_id` for exactly that. Read from LiteLLM's
    source rather than guessed, after the UI showed twelve agents with `"keys": null`.
    """
    fake = FakeGateway()
    litellm(fake).publish(SPEC, SPEC.card(GW, TENANT, AUD), key=KEY)
    linked = [c for c in fake.calls if c[1] == "/key/update"]
    assert linked, "the agent's key was never pointed at it — the UI will say Needs setup"
    (_, _, body), = linked
    assert body["key"] == KEY and body["agent_id"] == "ag-0"


def test_an_agent_with_no_key_links_nothing_rather_than_sending_a_null():
    """Ten identities are provisioned only against a live tenant. An agent with no key has nothing to
    link, and sending `agent_id` for a key that does not exist would fail a deploy over an identity
    nobody has created yet."""
    fake = FakeGateway()
    litellm(fake).publish(SPEC, SPEC.card(GW, TENANT, AUD))
    assert not [c for c in fake.calls if c[1] == "/key/update"]


def test_a_failed_link_does_not_lose_the_published_agent():
    """The card is the thing being published; the key link is the association that makes it useful.
    If the link fails the agent is still registered, so the failure is reported without pretending
    the publish did not happen."""
    import urllib.error

    class LinkFails(FakeGateway):
        def __call__(self, method, path, body=None):
            if path == "/key/update":
                raise urllib.error.HTTPError(path, 400, "Bad Request", {}, None)  # type: ignore[arg-type]
            return super().__call__(method, path, body)

    fake = LinkFails()
    assert litellm(fake).publish(SPEC, SPEC.card(GW, TENANT, AUD), key=KEY) == "ag-0"
