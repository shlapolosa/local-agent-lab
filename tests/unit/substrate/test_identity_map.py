"""Every Entra identity must map to a virtual key that EXISTS.

`ENTRA_CLIENT_TO_KEY` is what the gateway turns a validated JWT into a virtual key with. A mapping
pointing at a key that no longer exists is an identity that authenticates and then fails, and it is
invisible: nothing reads the map as a whole.

The card publisher already refuses a MISMATCH, but only for the agents it publishes. Measured
20 Sep 2026: after the registry was rebuilt onto a new database, the Power Automate connector's
client id still mapped to its old key. It publishes no card, so nothing checked it, and the
integration would have failed at its first call with an auth error naming neither end of the map.
"""
from lab.substrate import agentregistry


def test_a_mapping_to_a_key_that_no_longer_exists_is_named():
    dangling = agentregistry.dangling_identities(
        {"client-a": "sk-alive", "client-b": "sk-dead"}, {"sk-alive"})
    assert dangling == {"client-b": "sk-dead"}


def test_a_fully_live_map_is_empty():
    assert agentregistry.dangling_identities({"client-a": "sk-alive"}, {"sk-alive"}) == {}


def test_an_empty_map_is_not_an_error():
    assert agentregistry.dangling_identities({}, {"sk-alive"}) == {}
    assert agentregistry.dangling_identities(None, set()) == {}


def test_the_live_key_set_is_INJECTED_so_the_authority_is_the_registry_not_a_naming_rule():
    """The connector's key lives under a variable name no agent spec knows
    (`POWER_AUTOMATE_KEY`), so a check that discovered keys by naming convention would have missed
    the very case that motivated this. The caller passes the keys that actually exist — in
    production, the ones the gateway lists — and this compares against exactly those."""
    import inspect
    params = list(inspect.signature(agentregistry.dangling_identities).parameters)
    assert params == ["client_to_key", "live_keys"]
    # Nothing is discovered: a key absent from `live_keys` is dangling, whatever it is called.
    assert agentregistry.dangling_identities({"c": "POWER_AUTOMATE_KEY_VALUE"}, set()) == {
        "c": "POWER_AUTOMATE_KEY_VALUE"}
