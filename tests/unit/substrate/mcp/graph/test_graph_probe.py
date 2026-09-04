"""src/lab/substrate/mcp/graph/graph_probe.py — turning a status code into a sentence someone can act
on. Pure, and the reason an operator can provision this integration at all: a bare 403 hides three
completely different administrative problems.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/graph/test_graph_probe.py"""
from lab.core.collab import CAPABILITIES, CollabThrottled, CollabUnavailable
from lab.substrate.mcp.graph import graph_probe

READ_ALL = ("Sites.Read.All", "Files.Read.All", "Calendars.Read",
            "OnlineMeetingRecording.Read.All", "OnlineMeetingTranscript.Read.All")


def explain(status, code="", message="", capability="items"):
    return graph_probe.explain(status, code, message, capability)


# ------------------------------------------------------------------ the roles table
def test_a_token_declaring_every_read_permission_reports_every_capability_available():
    table = graph_probe.capabilities_from_roles(READ_ALL)
    assert set(table) == set(CAPABILITIES)
    assert all(v is None for v in table.values())


def test_a_missing_grant_is_reported_per_capability_naming_what_would_fix_it():
    table = graph_probe.capabilities_from_roles(("Sites.Read.All", "Files.Read.All"))
    assert table["sites"] is None and table["items"] is None
    unavailable = table["recordings"]
    assert isinstance(unavailable, CollabUnavailable) and unavailable.capability == "recordings"
    assert "OnlineMeetingRecording.Read.All" in unavailable.remedy
    assert "admin consent" in unavailable.remedy.lower()


def test_a_token_with_no_roles_at_all_says_so_rather_than_listing_eight_identical_failures():
    table = graph_probe.capabilities_from_roles(())
    assert all(isinstance(v, CollabUnavailable) for v in table.values())
    assert "no Microsoft Graph application permissions" in table["sites"].reason


def test_site_selected_counts_because_least_privilege_must_not_read_as_unavailable():
    assert graph_probe.capabilities_from_roles(("Sites.Selected",))["sites"] is None


def test_subscribing_needs_the_permission_of_whatever_is_watched_not_a_permission_of_its_own():
    assert graph_probe.capabilities_from_roles(("Files.Read.All",))["watches"] is None
    assert graph_probe.capabilities_from_roles(())["watches"] is not None


def test_the_declared_roles_are_reported_so_an_operator_sees_what_the_tenant_actually_consented():
    reason = graph_probe.capabilities_from_roles(("Sites.Read.All",))["recordings"].reason
    assert "Sites.Read.All" in reason


def test_a_role_table_covers_every_capability_the_port_declares():
    assert set(graph_probe.PERMISSIONS) == set(CAPABILITIES)


# ------------------------------------------------------------------ explain()
def test_a_success_is_not_a_refusal():
    assert explain(200) == (True, "", "")
    assert graph_probe.refusal(204, "", "", "items") is None


def test_a_401_is_the_labs_own_credential_not_the_tenants_grant():
    available, reason, remedy = explain(401, "InvalidAuthenticationToken", "Access token has expired")
    assert available is False and "credential" in reason
    assert "GRAPH_CLIENT_SECRET" in remedy and "clock" in remedy


def test_a_403_naming_the_authorization_code_is_a_grant_that_was_never_consented():
    available, reason, remedy = explain(403, "Authorization_RequestDenied",
                                        "Insufficient privileges to complete the operation.",
                                        capability="sites")
    assert available is False and "not consented" in reason
    assert "Sites.Read.All" in remedy and "admin consent" in remedy.lower()


def test_a_403_on_a_recording_is_the_teams_application_access_policy_a_separate_requirement():
    """The usual cause of a confusing 403: the Graph permission IS consented, and Teams still refuses
    because no application access policy grants the app access to that user's meetings."""
    available, reason, remedy = explain(403, "Forbidden",
                                        "No application access policy found for this app",
                                        capability="recordings")
    assert available is False and "application access policy" in reason
    assert "Grant-CsApplicationAccessPolicy" in remedy and "New-CsApplicationAccessPolicy" in remedy
    assert "PowerShell" in remedy and "30 minutes" in remedy


def test_a_bare_403_on_a_meeting_capability_still_reaches_for_the_policy_because_that_is_the_usual_cause():
    _, reason, remedy = explain(403, "Forbidden", "Forbidden", capability="transcripts")
    assert "application access policy" in reason and "Grant-CsApplicationAccessPolicy" in remedy


def test_a_consent_failure_on_a_meeting_capability_also_warns_that_the_policy_is_still_required():
    _, _, remedy = explain(403, "Authorization_RequestDenied", "Insufficient privileges",
                           capability="recordings")
    assert "OnlineMeetingRecording.Read.All" in remedy and "application access policy" in remedy


def test_a_tenant_that_switched_transcript_access_off_is_its_own_story():
    _, reason, remedy = explain(403, "Forbidden", "denied (GraphAccessToTranscriptsDisabled)",
                                capability="transcripts")
    assert "transcript" in reason and "tenant" in reason
    assert "Teams admin" in remedy


def test_a_402_is_the_tenant_not_the_grant():
    _, reason, remedy = explain(402, "", "the app must be associated with an Azure subscription",
                                capability="recordings")
    assert "licen" in reason or "billing" in reason
    assert "Azure subscription" in remedy


def test_a_403_that_talks_about_a_licence_is_read_as_one_even_without_a_402():
    _, reason, _ = explain(403, "Forbidden", "The tenant does not have a valid license for this API",
                           capability="meetings")
    assert "licen" in reason


def test_a_404_is_absence_and_is_explicitly_not_a_permission_problem():
    _, reason, remedy = explain(404, "itemNotFound", "The resource could not be found.")
    assert "does not exist" in reason and "not a permission problem" in remedy


def test_a_429_becomes_the_throttled_error_carrying_the_providers_hint():
    err = graph_probe.refusal(429, "TooManyRequests", "Please retry again later.", "items",
                              retry_after=12.0)
    assert isinstance(err, CollabThrottled) and err.retry_after == 12.0


def test_a_server_error_is_the_providers_side_and_says_to_try_again():
    _, reason, remedy = explain(503, "", "Service Unavailable")
    assert "Microsoft Graph" in reason and "again" in remedy


def test_an_unclassified_status_still_produces_a_whole_sentence():
    err = graph_probe.refusal(418, "Teapot", "short and stout", "items")
    assert isinstance(err, CollabUnavailable) and "418" in err.reason and "Teapot" in err.reason
    assert err.sentence.endswith(".")


def test_every_refusal_names_the_capability_that_was_attempted():
    for status in (401, 402, 403, 404, 500, 418):
        assert graph_probe.refusal(status, "", "", "drives").capability == "drives"


# ------------------------------------------------------------------ the tenant-wide feeds
def test_the_tenant_wide_meeting_feeds_are_recognised_as_the_gated_ones():
    assert graph_probe.is_metered("/communications/onlineMeetings/getAllRecordings")
    assert graph_probe.is_metered("/communications/onlineMeetings/getAllTranscripts")
    assert graph_probe.is_metered("/drives/d/items/i/assignSensitivityLabel")


def test_a_per_meeting_read_is_not_gated_because_that_is_the_ordinary_path():
    assert not graph_probe.is_metered("/users/u/onlineMeetings/m/recordings")
    assert not graph_probe.is_metered("/drives/d/root/children")


def test_the_gate_explains_itself_and_names_the_switch():
    err = graph_probe.metered_refusal("recordings", "/communications/onlineMeetings/getAllRecordings")
    assert isinstance(err, CollabUnavailable) and err.capability == "recordings"
    assert "GRAPH_ALLOW_METERED" in err.remedy and "tenant-wide" in err.reason


def test_an_unreachable_provider_is_a_refusal_not_a_success():
    """Status 0 is what the transport reports when Graph could not be reached AT ALL — DNS, TLS, an
    outbound proxy, a timeout. `explain()` must not read "not >= 400" as "it worked": the deep probe
    reads exactly this answer, and reporting a capability AVAILABLE because the network is down is
    the worst possible failure of a capability table."""
    available, reason, remedy = graph_probe.explain(0, "Unreachable", "connection refused", "sites")
    assert available is False and "could not be reached" in reason and remedy
    refused = graph_probe.refusal(0, "Unreachable", "connection refused", "sites")
    assert isinstance(refused, CollabUnavailable) and refused.sentence.endswith(".")
    assert graph_probe.explain(0)[1] and graph_probe.explain(204)[0] is True   # a real success still is one
