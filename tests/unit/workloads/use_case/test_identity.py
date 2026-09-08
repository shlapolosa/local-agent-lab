"""One identity per bounded context — and what happens for the ones nobody has provisioned yet.

Ten CAFÉ services, ten app registrations. The point of separating them is not tidiness: spend
attributes per identity, the gateway's per-tool ACL can differ per identity, and a wrong answer is
attributable to the context that gave it. But provisioning ten registrations is an operator action
against a live tenant, so the code must work correctly with two, or ten, or any number in between —
and must never fail a run because a registration it would have preferred does not exist.
"""
import pytest

from lab.workloads.usecase import identity
from lab.workloads.usecase.steps import STEPS


def test_every_service_that_owns_a_step_has_a_prefix():
    """A service with no prefix would silently share another one's spend, and the spend ledger is
    the only place that would ever show it."""
    assert {s.service for s in STEPS} <= set(identity.PREFIX_FOR)


def test_no_two_services_share_a_prefix():
    assert len(set(identity.PREFIX_FOR.values())) == len(identity.PREFIX_FOR)


def test_every_prefix_is_a_legal_environment_variable_stem():
    for prefix in identity.PREFIX_FOR.values():
        assert prefix.isupper() and prefix.replace("_", "").isalnum()


def test_a_provisioned_service_authenticates_as_itself(monkeypatch):
    monkeypatch.setenv("USECASE_RISK_KEY", "sk-risk")
    monkeypatch.setenv("USECASE_KEY", "sk-shared")
    assert identity.credential_for("Risk Officer", fallback="sk-shared") == "sk-risk"


def test_an_unprovisioned_service_falls_back_to_the_workloads_own_credential(monkeypatch):
    """Ten registrations are an operator action against a live tenant. A run must not fail because
    one of them has not happened yet — it shares the workload's identity and the spend rolls up to
    the team, which is exactly where it rolled up before."""
    monkeypatch.delenv("USECASE_COST_KEY", raising=False)
    monkeypatch.delenv("USECASE_COST_CLIENT_ID", raising=False)
    assert identity.credential_for("Cost Engineer", fallback="sk-shared") == "sk-shared"


def test_a_service_nobody_declared_falls_back_rather_than_raising(monkeypatch):
    """A new CAFÉ service added to the step table before its prefix is declared must not take a
    run down. The parity test above is what catches the omission, at build time."""
    assert identity.credential_for("Chief Vibes Officer", fallback="sk-shared") == "sk-shared"


def test_a_fallback_that_is_itself_missing_refuses_rather_than_running_unauthenticated(monkeypatch):
    monkeypatch.delenv("USECASE_RISK_KEY", raising=False)
    with pytest.raises(identity.NoCredential):
        identity.credential_for("Risk Officer", fallback="")
