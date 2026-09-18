"""Who may see what, and who the ledger records.

The app had one shared password and a free-text "Reviewer" box, so every page was open to anyone
holding the password and every decision was self-asserted. These tests pin the replacement: a page
is offered only to a principal holding one of its roles, and the actor recorded is the signed-in
identity rather than a string somebody typed.
"""
import pytest

from fixtures.streamlit import APP, FakeSt, Stop, install
from lab.substrate.review import identity


def _p(*roles, upn="sme@doh.gov.ae"):
    return identity.Principal(oid="oid-1", upn=upn, name="A Reviewer", roles=tuple(roles))


# ---------------------------------------------------------------- the dispatch table


def test_every_page_declares_the_roles_that_may_reach_it():
    """The table is still the only dispatch; it now carries the authorisation beside the function,
    so a page cannot be added without someone deciding who it is for."""
    assert set(APP.PAGES) == {"Review", "Submit", "Runs", "Artifacts"}
    for name, (fn, roles) in APP.PAGES.items():
        assert callable(fn), name
        assert isinstance(roles, tuple), name
        assert set(roles) <= set(identity.ROLES), name


def test_the_two_sme_gates_are_separate_roles():
    """A conformant design can still be declined on value, so confirming conformance and
    authorising spend are different powers held by different people."""
    assert identity.ARCHITECT != identity.BUSINESS
    assert APP.PAGES["Artifacts"][1] == (identity.ADMIN,)


@pytest.mark.parametrize("roles,visible", [
    ((identity.ADMIN,), {"Runs", "Artifacts"}),
    ((identity.ARCHITECT,), {"Review", "Submit", "Runs"}),
    ((identity.BUSINESS,), {"Review", "Submit", "Runs"}),
    ((identity.ADMIN, identity.ARCHITECT), {"Review", "Submit", "Runs", "Artifacts"}),
    ((), set()),
])
def test_a_person_is_offered_only_the_pages_their_roles_reach(roles, visible):
    assert set(APP.pages_for(_p(*roles))) == visible


def test_a_signed_in_person_with_no_role_is_told_rather_than_shown_a_failure(monkeypatch):
    """Authenticating and holding nothing is a real state — the fix is an Entra assignment, and
    naming it is how they find out. A login error would send them to the wrong place."""
    st = FakeSt()
    install(st)
    monkeypatch.setattr(APP, "_principal", lambda: _p())
    with pytest.raises(Stop):
        APP.main()
    assert st.said("warning", "hold no role"), [c for c in st.calls if c[0] == "warning"]


# ---------------------------------------------------------------- the ledger


def test_the_actor_recorded_is_the_signed_in_identity_not_a_typed_string():
    """The whole point. `human_decision` refuses a blank actor and cannot check a present one, so
    until the app supplies a verified one the audit log names whoever was at the keyboard."""
    assert _p(identity.ARCHITECT).actor == "sme@doh.gov.ae"


def test_a_page_a_principal_cannot_reach_is_refused_not_merely_hidden():
    """A hidden button is not an authorisation control. Anyone can set `?mode=Artifacts`."""
    assert APP.may_open(_p(identity.BUSINESS), "Artifacts") is False
    assert APP.may_open(_p(identity.ADMIN), "Artifacts") is True
