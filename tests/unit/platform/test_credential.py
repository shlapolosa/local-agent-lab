"""A gateway credential as headers — one shape that both gateways read."""
from lab.platform import credential

JWT = "eyJhbGciOi.eyJzdWIiOi.c2lnbmF0dXJl"


def test_a_key_travels_as_a_bearer_and_as_an_api_key():
    """LiteLLM (dev) reads the Bearer and refuses `api-key` on /mcp; APIM (prod) reads a subscription key
    from `api-key` alone (measured 24 Sep 2026). Sending both is one client for both gateways."""
    assert credential.headers("sk-abc") == {"Authorization": "Bearer sk-abc", "api-key": "sk-abc"}


def test_a_token_travels_as_a_bearer_only():
    """APIM would validate an `api-key` holding a token as a subscription key, and refuse it."""
    assert credential.headers(JWT) == {"Authorization": f"Bearer {JWT}"}


def test_no_credential_is_no_headers():
    assert credential.headers("") == {}
