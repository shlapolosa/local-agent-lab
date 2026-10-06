"""lab.substrate.entra — ONE Entra access-token check, shared by the gateway and the meeting app.

Signed with a key generated here, so the whole path runs offline: signature, audience, issuer, tenant.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/test_entra.py"""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from lab.substrate import entra

TENANT = "b911f4d4-de30-405f-96e9-bb1c773fe2ff"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = {**jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True), "kid": "k1"}


def token(**claims):
    body = {"aud": "app-id", "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "tid": TENANT,
            "oid": "user-oid", "exp": int(time.time()) + 600, "nbf": int(time.time()) - 5} | claims
    return jwt.encode(body, KEY, algorithm="RS256", headers={"kid": "k1"})


def check(tok, audiences=("app-id",)):
    return entra.validate(tok, tenant=TENANT, audiences=audiences, keys=lambda: [JWK])


def test_a_good_token_yields_its_claims():
    assert check(token())["oid"] == "user-oid"


@pytest.mark.parametrize("bad", [{"aud": "someone-else"}, {"tid": "other-tenant"},
                                 {"iss": "https://evil.example/v2.0"}, {"exp": int(time.time()) - 60}])
def test_a_token_for_another_audience_tenant_or_issuer_or_expired_is_refused(bad):
    with pytest.raises(Exception):
        check(token(**bad))


def test_a_v1_token_from_sts_is_accepted_as_the_gateway_has_always_done():
    assert check(token(iss=f"https://sts.windows.net/{TENANT}/"))["tid"] == TENANT


def test_an_unsigned_or_foreign_signed_token_is_refused():
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode({"aud": "app-id", "tid": TENANT}, other, algorithm="RS256", headers={"kid": "k1"})
    with pytest.raises(Exception):
        check(forged)
