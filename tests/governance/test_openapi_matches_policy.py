"""The generated OpenAPI document and the gateway's `/api` policy table describe the SAME surface.

A two-way PARITY test, so exactness is the contract: an operation the gateway authorises but the
document omits is a capability no connector can reach, and a documented path the policy does not
match is a connector action the gateway refuses (default deny) — both are defects, in either direction.
"""
import re

from lab.platform.openapi import openapi
from lab.substrate import apipolicy


def _documented():
    doc = openapi("https://gateway.example.test", apipolicy.OPERATIONS)
    for path, item in doc["paths"].items():
        for method in item:
            # a concrete path the policy can match: each {param} becomes a sample segment
            yield method.upper(), doc["basePath"] + re.sub(r"{\w+}", "sample", path)


def test_every_documented_operation_matches_exactly_one_policy_row():
    for method, path in _documented():
        hits = [o.name for o in apipolicy.OPERATIONS if o.matches(method, path)]
        assert len(hits) == 1, f"{method} {path} matches {hits} — the gateway would refuse or be ambiguous"


def test_every_policy_row_is_documented():
    reached = {apipolicy.operation(m, p).name for m, p in _documented()}
    missing = {o.name for o in apipolicy.OPERATIONS} - reached
    assert not missing, f"authorised at the gateway but absent from the connector document: {missing}"
