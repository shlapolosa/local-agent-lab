"""Offline tests for src/lab/substrate/apipolicy.py — which app role each /api operation requires.

The point of this table is that it is the ONLY statement of REST authorisation, read today by the
gateway hook and tomorrow by an APIM policy. So what is pinned here is what any reader must be able
to rely on: the patterns are disjoint (no precedence to reason about), EVERY route the front door
actually generates matches exactly one of them (a new route cannot slip in unpoliced), an unknown
path under the prefix denies rather than allows, and reading and deciding are separate powers.
"""
import pytest
from starlette.routing import Route

from lab.platform.contracts import PROCESSES, ApiRoles
from lab.substrate import apipolicy
from lab.substrate.mcp.workflow import rest


def _paths():
    """Every (method, concrete path) the front door serves, with path params filled in — the real
    surface, not a list re-typed here that could drift from it."""
    class _Server:                                    # routes() only stores it in closures
        container = None

    for route in rest.routes(_Server()):
        assert isinstance(route, Route)
        path = (route.path.replace("{request_id}", "wfr-abc123")
                          .replace("{approval_id}", "apr-abc123"))
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            yield method, path


def test_every_generated_route_is_governed_by_exactly_one_operation():
    """The whole surface is policed. A route added without a policy entry fails here rather than
    silently becoming reachable by any caller that holds any role."""
    for method, path in _paths():
        matched = [o for o in apipolicy.OPERATIONS if o.matches(method, path)]
        assert len(matched) == 1, f"{method} {path} matched {[o.name for o in matched]}"
        assert apipolicy.governs(path), f"{path} is outside the policy prefix"


def test_patterns_are_disjoint_so_order_is_documentation_not_precedence():
    for method, path in _paths():
        assert sum(o.matches(method, path) for o in apipolicy.OPERATIONS) == 1


def test_unknown_path_under_the_prefix_denies():
    """Default deny: governed, but no operation — the caller must treat None as refusal, so a typo'd
    or newly added path is never allowed by omission."""
    for path in ("/api/processes/x/runs/y/z", "/api/nope", "/api", "/api/approvals/a/decide/extra"):
        assert apipolicy.governs(path)
    assert apipolicy.role_for("GET", "/api/nope") is None
    assert apipolicy.operation("GET", "/api/nope") is None
    # right path, wrong verb is also unknown — deciding is a POST and nothing else
    assert apipolicy.role_for("GET", "/api/approvals/apr-1/decide") is None
    assert apipolicy.role_for("DELETE", "/api/processes/visio_to_archimate/runs") is None


def test_paths_outside_the_prefix_are_not_this_policy_s_business():
    """/v1 and /mcp are governed by LiteLLM's own key auth and per-tool ACLs; this table must not
    claim them, or every model call would need an app role."""
    for path in ("/v1/chat/completions", "/mcp/", "/health", "", "/apifoo", "/apifoo/bar"):
        assert not apipolicy.governs(path), path


def test_reading_and_deciding_are_different_powers():
    """Mirrors ApprovalTools.READ / .WRITE: a relay that may show a human what is waiting must not
    thereby be able to answer for them."""
    read = apipolicy.role_for("GET", "/api/approvals/apr-1")
    decide = apipolicy.role_for("POST", "/api/approvals/apr-1/decide")
    assert read == ApiRoles.READ and decide == ApiRoles.DECIDE and read != decide


def test_starting_a_run_and_reading_it_use_the_submit_role():
    for name, spec in PROCESSES.items():
        assert apipolicy.role_for("GET", f"/api/processes/{name}/runs/wfr-1") == ApiRoles.SUBMIT
        if spec.external:
            assert apipolicy.role_for("POST", f"/api/processes/{name}/runs") == ApiRoles.SUBMIT


def test_every_role_used_is_declared_in_the_contract_vocabulary():
    """The provisioning script creates ApiRoles.ALL; a role used here but absent there would be a
    role no app registration could ever be granted."""
    assert {o.role for o in apipolicy.OPERATIONS} <= set(ApiRoles.ALL)
    assert set(ApiRoles.ALL) == {o.role for o in apipolicy.OPERATIONS}   # and none is dead


def test_operation_names_are_unique_and_described():
    names = [o.name for o in apipolicy.OPERATIONS]
    assert len(names) == len(set(names))
    for o in apipolicy.OPERATIONS:
        assert o.description and o.method == o.method.upper()


@pytest.mark.parametrize("path", ["/api/approvals/", "/api/processes/"])
def test_a_trailing_slash_does_not_change_the_operation(path):
    """A client that appends a slash must not fall into the deny-by-no-match branch and get a
    confusing 401 instead of the operation it asked for."""
    assert apipolicy.role_for("GET", path) is not None
