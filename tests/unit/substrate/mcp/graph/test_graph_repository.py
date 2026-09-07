"""src/lab/substrate/mcp/graph/graph_repository.py — the adapter that satisfies the domain port.
It composes auth, transport, mapper and probe and adds only the Graph-shaped decisions: which URL a
verb is, which id needs resolving, and which refusals this deployment makes on its own (an
un-allow-listed notification URL, a tenant-wide feed).
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/graph/test_graph_repository.py"""
from datetime import datetime, timezone

import pytest

from fixtures.graph import FakeSleep, FakeTokens, FakeTransport
from lab.core.collab import (CAPABILITIES, ChangeType, CollabNotConfigured, CollabRepository,
                             CollabThrottled, CollabUnavailable, ContentHandle, MediaKind)
from lab.substrate.mcp.graph import graph_map, graph_repository
from lab.substrate.mcp.graph.graph_rest import GraphClient

BASE = "https://graph.microsoft.com/v1.0"
NOW = lambda: datetime(2026, 9, 4, 9, 0, tzinfo=timezone.utc)          # noqa: E731
ROLES = ("Sites.Read.All", "Files.Read.All", "Calendars.Read",
         "OnlineMeetingRecording.Read.All", "OnlineMeetingTranscript.Read.All")


CHAIR_OID = "5f48f64f-21d4-411a-afe7-72026aea94ed"      # what the directory answers for the UPN


def repo(transport=None, roles=ROLES, tokens=None, **kw):
    t = transport or FakeTransport()
    tokens = tokens or FakeTokens("tok", roles)
    client = GraphClient(tokens, transport=t, sleep=FakeSleep(), now=lambda: 0.0)
    kw.setdefault("meeting_user", "chair@lab.example")
    kw.setdefault("now", NOW)
    # Every onlineMeetings path resolves the UPN to an object id first, because Graph accepts only a
    # GUID there. Answered unconditionally: it is harness, not the thing any single test asserts —
    # except `test_online_meeting_paths_use_the_object_id`, which asserts it directly.
    if hasattr(t, "expect"):          # not every double is the rule-driven transport
        # appended LAST, and rules are tried in order, so a test's own /calendarView or
        # /onlineMeetings rule still wins over this prefix.
        t.expect(contains="/users/chair%40lab.example", body={"id": CHAIR_OID}, times=None)
    return graph_repository.GraphCollabRepository(client, tokens, **kw), t


def test_the_adapter_satisfies_the_domain_port():
    made, _ = repo()
    assert isinstance(made, CollabRepository)


# ------------------------------------------------------------------ capabilities
def test_the_shallow_probe_reads_the_tokens_own_roles_without_calling_graph():
    made, t = repo()
    table = made.capabilities()
    assert set(table) == set(CAPABILITIES)
    # `uploads` is absent from this token's roles on purpose — the read identity does not write.
    assert all(table[c] is None for c in CAPABILITIES if c != "uploads")
    assert t.calls == []


def test_a_capability_the_token_does_not_declare_is_reported_with_its_remedy():
    made, _ = repo(roles=("Sites.Read.All",))
    assert made.capabilities()["recordings"].remedy.startswith("grant the application permission")


def test_an_unconfigured_credential_reports_the_whole_table_rather_than_raising():
    """`capabilities()` is what an operator runs when nothing works yet — it must always answer."""
    made, _ = repo(tokens=FakeTokens(raises=CollabNotConfigured("GRAPH_CLIENT_SECRET")))
    table = made.capabilities()
    assert all(isinstance(v, CollabUnavailable) for v in table.values())
    assert "GRAPH_CLIENT_SECRET" in table["sites"].reason


def test_the_deep_probe_makes_one_cheap_call_per_area_and_reports_what_it_learns():
    t = FakeTransport()
    t.expect("/sites/root/drives", status=403, body={"error": {"code": "Authorization_RequestDenied",
                                                               "message": "Insufficient privileges"}})
    t.expect("", body={"value": []}, times=None)
    made, _ = repo(t)
    table = made.capabilities(deep=True)
    assert table["sites"] is None and table["drives"] is not None
    assert "not consented" in table["drives"].reason


def test_a_deep_probe_treats_absence_as_reaching_the_resource_because_it_got_past_authorisation():
    t = FakeTransport()
    t.expect("/recordings", status=404, body={"error": {"code": "itemNotFound"}})
    t.expect("", body={"value": []}, times=None)
    made, _ = repo(t)
    assert made.capabilities(deep=True)["recordings"] is None


def test_a_deep_probe_reports_the_teams_policy_when_that_is_what_the_tenant_says():
    t = FakeTransport()
    t.expect("/transcripts", status=403, body={"error": {
        "code": "Forbidden", "message": "No application access policy found for this app"}})
    t.expect("", body={"value": []}, times=None)
    made, _ = repo(t)
    assert "Grant-CsApplicationAccessPolicy" in made.capabilities(deep=True)["transcripts"].remedy


def test_a_deep_probe_of_meetings_without_a_configured_user_says_which_setting_is_missing():
    t = FakeTransport().expect("", body={"value": []}, times=None)
    made, _ = repo(t, meeting_user="")
    assert "GRAPH_MEETING_USER" in made.capabilities(deep=True)["meetings"].reason


def test_a_deep_probe_leaves_a_capability_the_roles_already_ruled_out_alone():
    t = FakeTransport().expect("", body={"value": []}, times=None)
    made, _ = repo(t, roles=("Sites.Read.All",))
    table = made.capabilities(deep=True)
    assert table["recordings"] is not None and "/recordings" not in " ".join(t.urls)


# ------------------------------------------------------------------ files
def test_sites_are_searched_because_graph_has_no_plain_list():
    t = FakeTransport().expect("/sites", body={"value": [{"id": "s1", "displayName": "Design"}]})
    made, _ = repo(t)
    page = made.sites("design")
    assert [s.name for s in page] == ["Design"] and page.cursor is None
    assert "search=design" in t.urls[0]


def test_an_empty_query_asks_for_everything_the_app_may_see():
    t = FakeTransport().expect("/sites", body={"value": []})
    made, _ = repo(t)
    made.sites()
    assert "search=%2A" in t.urls[0] or "search=*" in t.urls[0]


def test_a_page_carries_the_cursor_forward_untouched():
    t = FakeTransport().expect("/sites", body={"value": [{"id": "s1"}],
                                               "@odata.nextLink": f"{BASE}/sites?$skiptoken=Z"})
    made, _ = repo(t)
    assert made.sites().cursor == f"{BASE}/sites?$skiptoken=Z"


def test_drives_are_listed_under_the_site_they_belong_to():
    t = FakeTransport().expect("/drives", body={"value": [{"id": "b!abc", "name": "Documents"}]})
    made, _ = repo(t)
    drive = made.drives("lab.sharepoint.com,2c5,fa2").items[0]
    assert drive.site_id == "lab.sharepoint.com,2c5,fa2" and drive.name == "Documents"
    assert "/sites/lab.sharepoint.com%2C2c5%2Cfa2/drives" in t.urls[0]


def test_a_persons_own_drive_is_reached_through_the_person_not_a_site():
    """The gap live testing exposed: a meeting recorded ad hoc is stored in the ORGANISER's drive,
    which hangs off no site, so `drives(site_id)` could not reach it at all and the drive id had to
    be fetched by hand. `/users/{id}/drive` is the one route, and the person is url-quoted (a UPN
    carries an `@`) so a directory id and a principal name work the same way."""
    t = FakeTransport().expect("/drive", body={"id": "b!me", "name": "OneDrive",
                                               "owner": {"user": {"displayName": "Maria"}}})
    made, _ = repo(t)
    drive = made.user_drive("maria@lab.example")
    assert (drive.id, drive.owner, drive.site_id) == ("b!me", "maria@lab.example", "")
    assert t.urls[0] == f"{BASE}/users/maria%40lab.example/drive"


def test_a_persons_drive_needs_a_person_and_a_refusal_is_a_sentence():
    made, _ = repo(FakeTransport().expect("/drive", status=403, body={
        "error": {"code": "Authorization_RequestDenied", "message": "Insufficient privileges."}}))
    with pytest.raises(ValueError, match="whose drive"):
        made.user_drive("  ")
    with pytest.raises(CollabUnavailable) as e:
        made.user_drive("maria@lab.example")
    assert e.value.capability == "drives" and e.value.sentence.endswith(".")


def test_listing_the_root_of_a_drive_is_one_level_deep():
    t = FakeTransport().expect("/children", body={"value": [{"id": "01", "name": "a.txt"}]})
    made, _ = repo(t)
    made.items("b!abc")
    assert t.urls[0].startswith(f"{BASE}/drives/b%21abc/root/children")


def test_listing_a_folder_addresses_it_by_path_the_way_graph_wants():
    t = FakeTransport().expect("/children", body={"value": []})
    made, _ = repo(t)
    made.items("b!abc", "Reports/2026")
    assert "/root:/Reports/2026:/children" in t.urls[0]


def test_one_items_metadata_comes_back_by_its_handle():
    t = FakeTransport().expect("/items/01ITEM", body={"id": "01ITEM", "name": "report.docx", "size": 9})
    made, _ = repo(t)
    item = made.item(ContentHandle.item("b!abc", "01ITEM"))
    assert item.name == "report.docx" and item.drive_id == "b!abc" and item.size == 9


def test_asking_for_a_files_metadata_with_a_recordings_handle_is_a_caller_error():
    made, _ = repo()
    with pytest.raises(ValueError, match="file"):
        made.item(ContentHandle.recording("u~m", "rec-1"))


# ------------------------------------------------------------------ content
def test_a_files_content_streams_in_chunks_and_is_never_held_whole():
    t = FakeTransport().expect("/content", body=b"hello world", headers={"Content-Type": "text/plain"})
    made, _ = repo(t)
    assert b"".join(made.open(ContentHandle.item("b!abc", "01"))) == b"hello world"
    assert t.urls[0] == f"{BASE}/drives/b%21abc/items/01/content"


def test_the_streamed_content_also_comes_back_as_a_file_like_for_the_store():
    t = FakeTransport().expect("/content", body=b"xyz",
                               headers={"Content-Type": "video/mp4", "Content-Length": "3"})
    made, _ = repo(t)
    content = made.content(ContentHandle.item("b!abc", "01"))
    assert content.content_type == "video/mp4" and content.size == 3
    assert content.fileobj.read() == b"xyz"


def test_a_recordings_content_is_addressed_under_the_user_whose_meeting_it_was():
    t = FakeTransport().expect("/content", body=b"video")
    made, _ = repo(t)
    ref = graph_map.meeting_ref("chair@lab.example", "MSp/abc==")
    made.content(ContentHandle.recording(ref, "rec-1"))
    # Searched, not indexed: resolving the UPN to an object id adds a directory call before this
    # one, and an assertion pinned to urls[0] says more about call ORDER than about the path.
    got = next(u for u in t.urls if u.endswith("/recordings/rec-1/content"))
    assert f"/users/{CHAIR_OID}/onlineMeetings/" in got, "onlineMeetings takes the object id"
    assert "MSp%2Fabc%3D%3D" in got                             # the encoded id, decoded and re-quoted


def test_a_transcript_is_asked_for_in_the_format_a_reader_can_use():
    t = FakeTransport().expect("/content", body=b"WEBVTT")
    made, _ = repo(t)
    made.content(ContentHandle.transcript(graph_map.meeting_ref("chair@lab.example", "m1"), "tr-1"))
    got = next(u for u in t.urls if "/transcripts/tr-1/content" in u)
    assert "text%2Fvtt" in got


def test_online_meeting_paths_use_the_object_id_because_graph_refuses_a_upn():
    """MEASURED against the live tenant, and it cost a working feature to find.

    `/users/{id}/calendarView` accepts a UPN or a GUID. `/users/{id}/onlineMeetings` accepts ONLY a
    GUID and answers a UPN with `400 The userId in request URL is not a valid GUID`. So LISTING
    meetings worked while every per-meeting lookup failed — and because the caller resolves the
    owning meeting on a best-effort path, the failure surfaced as an empty speaker picker rather
    than as an error. Every meeting, scheduled or ad-hoc, for the life of the feature.

    A UPN is what a person configures; a GUID is what this endpoint needs. The adapter resolves once
    and remembers, and that resolution is what this test pins."""
    t = FakeTransport().expect("/recordings", body={"value": [{"id": "rec-1"}]}, times=None)
    made, _ = repo(t)
    made.recordings(graph_map.meeting_ref("chair@lab.example", "MSp-1"))
    online = [u for u in t.urls if "/onlineMeetings" in u]
    assert online, "the recordings lookup went through onlineMeetings"
    for u in online:
        assert f"/users/{CHAIR_OID}/" in u, f"a UPN reached onlineMeetings: {u}"
        assert "chair%40lab.example/onlineMeetings" not in u


def test_the_directory_lookup_happens_once_per_user_not_once_per_call():
    """It is a second network round trip in front of every meeting call, so it is remembered. The
    set of mailboxes a deployment reads is configured and fixed, so the cache cannot grow."""
    t = FakeTransport().expect("/recordings", body={"value": []}, times=None)
    t.expect("/transcripts", body={"value": []}, times=None)
    made, _ = repo(t)
    ref = graph_map.meeting_ref("chair@lab.example", "MSp-1")
    made.recordings(ref)
    made.recordings(ref)
    made.transcripts(ref)
    lookups = [u for u in t.urls if u.endswith("/users/chair%40lab.example")]
    assert len(lookups) == 1, f"resolved {len(lookups)} times: {lookups}"


def test_a_meeting_known_only_by_its_join_url_is_resolved_once_and_remembered():
    join = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc/0"
    t = FakeTransport().expect("/onlineMeetings?", body={"value": [{"id": "MSp-real"}]}, times=None)
    t.expect("/content", body=b"video", times=None)
    made, _ = repo(t)
    ref = graph_map.meeting_ref("chair@lab.example", join)
    made.content(ContentHandle.recording(ref, "r1"))
    made.content(ContentHandle.recording(ref, "r2"))
    assert len([u for u in t.urls if "$filter" in u or "%24filter" in u]) == 1
    assert any("joinWebUrl" in u for u in t.urls)
    assert "/onlineMeetings/MSp-real/recordings/r2/" in t.urls[-1]


def test_a_join_url_that_matches_no_meeting_says_so_instead_of_calling_a_nonsense_path():
    t = FakeTransport().expect("/onlineMeetings?", body={"value": []})
    made, _ = repo(t)
    ref = graph_map.meeting_ref("chair@lab.example", "https://teams.microsoft.com/l/meetup-join/x")
    with pytest.raises(CollabUnavailable, match="no online meeting"):
        made.content(ContentHandle.recording(ref, "r1"))


def test_meeting_content_without_a_user_in_the_reference_names_the_missing_setting():
    made, _ = repo(meeting_user="")
    with pytest.raises(CollabNotConfigured, match="GRAPH_MEETING_USER"):
        made.content(ContentHandle.recording(graph_map.meeting_ref("", "m1"), "r1"))


# ------------------------------------------------------------------ meetings
def test_meetings_are_read_from_the_calendar_view_because_that_is_the_only_listable_window():
    t = FakeTransport().expect("/calendarView", body={"value": [
        {"id": "e1", "subject": "Sync", "isOnlineMeeting": True,
         "onlineMeeting": {"joinUrl": "https://teams.microsoft.com/l/x"}}]})
    made, _ = repo(t)
    page = made.meetings(since="2026-09-01T00:00:00Z", until="2026-09-04T00:00:00Z")
    assert [m.subject for m in page] == ["Sync"]
    url = t.urls[0]
    assert "/users/chair%40lab.example/calendarView" in url
    assert "startDateTime=2026-09-01T00%3A00%3A00Z" in url and "endDateTime=2026-09-04T00%3A00%3A00Z" in url


def test_an_unstated_window_defaults_to_the_recent_past_rather_than_all_of_history():
    t = FakeTransport().expect("/calendarView", body={"value": []})
    made, _ = repo(t)
    made.meetings()
    assert "startDateTime=2026-08-05T09%3A00%3A00Z" in t.urls[0]     # 30 days back from the clock
    assert "endDateTime=2026-09-05T09%3A00%3A00Z" in t.urls[0]       # a day ahead


def test_an_organizer_selects_whose_calendar_is_read_because_app_only_reads_per_user():
    t = FakeTransport().expect("/calendarView", body={"value": []})
    made, _ = repo(t, meeting_users=("chair@lab.example", "other@lab.example"))
    made.meetings(organizer="other@lab.example")
    assert "/users/other%40lab.example/calendarView" in t.urls[0]


def test_an_organizer_this_deployment_does_not_read_is_refused_before_any_call():
    """App-only reaches every mailbox the Teams policy covers, so the configured user is a BOUND on
    `organizer`, not just its default — otherwise one argument reads the whole tenant."""
    made, t = repo()
    with pytest.raises(CollabUnavailable) as e:
        made.meetings(organizer="ceo@lab.example")
    assert "GRAPH_MEETING_USERS" in e.value.remedy and t.calls == []


def test_a_meeting_reference_naming_an_unread_mailbox_is_refused_too():
    made, t = repo()
    with pytest.raises(CollabUnavailable):
        made.recordings(graph_map.meeting_ref("ceo@lab.example", "m1"))
    assert t.calls == []


def test_an_event_that_is_not_an_online_meeting_is_left_out_because_it_has_nothing_to_fetch():
    t = FakeTransport().expect("/calendarView", body={"value": [
        {"id": "e1", "subject": "Room booking"},
        {"id": "e2", "subject": "Sync", "isOnlineMeeting": True,
         "onlineMeeting": {"joinUrl": "https://teams.microsoft.com/l/x"}}]})
    made, _ = repo(t)
    assert [m.subject for m in made.meetings()] == ["Sync"]


def test_listing_meetings_with_no_user_anywhere_is_a_configuration_error_not_a_403():
    made, _ = repo(meeting_user="")
    with pytest.raises(CollabNotConfigured, match="GRAPH_MEETING_USER"):
        made.meetings()


def test_recordings_and_transcripts_are_listed_per_meeting_the_non_metered_path():
    t = FakeTransport().expect("/recordings", body={"value": [
        {"id": "rec1", "createdDateTime": "2026-09-01T11:00:00Z"}]})
    t.expect("/transcripts", body={"value": [{"id": "tr1"}]})
    made, _ = repo(t)
    ref = graph_map.meeting_ref("chair@lab.example", "MSp-1")
    rec = made.recordings(ref).items[0]
    tr = made.transcripts(ref).items[0]
    assert rec.kind is MediaKind.RECORDING and rec.meeting_id == ref
    assert str(rec.handle) == f"collab://recording/{ref}/rec1"
    assert tr.kind is MediaKind.TRANSCRIPT and str(tr.handle) == f"collab://transcript/{ref}/tr1"
    assert f"/users/{CHAIR_OID}/onlineMeetings/MSp-1/recordings" in t.urls[1]


def test_a_meeting_reference_that_is_not_one_is_a_caller_error():
    made, _ = repo()
    with pytest.raises(ValueError, match="meeting reference"):
        made.recordings("just-an-id")


# ------------------------------------------------------------------ watches (the write side)
def test_a_subscription_is_refused_when_no_destination_is_allow_listed_because_empty_means_refuse():
    made, t = repo()
    with pytest.raises(CollabUnavailable) as e:
        made.watch("/drives/d/root", "https://flow.example/hook", (ChangeType.CREATED,))
    assert "GRAPH_NOTIFICATION_ALLOWLIST" in e.value.remedy and t.calls == []


def test_a_destination_outside_the_allowlist_is_refused_and_the_url_is_named():
    made, _ = repo(notification_allowlist=("https://flow.example/",))
    with pytest.raises(CollabUnavailable, match="evil.example"):
        made.watch("/drives/d/root", "https://evil.example/hook", (ChangeType.CREATED,))


def test_an_insecure_destination_is_refused_even_if_someone_allow_listed_it():
    made, _ = repo(notification_allowlist=("http://flow.example/",))
    with pytest.raises(CollabUnavailable, match="https"):
        made.watch("/drives/d/root", "http://flow.example/hook", (ChangeType.CREATED,))


def test_an_allow_listed_subscription_is_created_with_a_clamped_expiry():
    t = FakeTransport().expect("/subscriptions", method="POST", body={
        "id": "sub-1", "resource": "/drives/d/root", "changeType": "created",
        "notificationUrl": "https://flow.example/hook", "expirationDateTime": "2026-10-03T17:50:00Z"})
    made, _ = repo(t, notification_allowlist=("https://flow.example/",))
    watch = made.watch("/drives/d/root", "https://flow.example/hook", (ChangeType.CREATED,),
                       expires="2027-01-01T00:00:00Z")
    assert watch.id == "sub-1" and watch.events == (ChangeType.CREATED,)
    import json
    sent = json.loads(t.calls[0]["body"])
    assert sent["expirationDateTime"] == "2026-10-03T17:50:00Z"   # driveItem maximum, less clock margin
    assert sent["changeType"] == "created"


def test_a_tenant_wide_feed_is_gated_and_the_gate_names_its_switch():
    made, t = repo(notification_allowlist=("https://flow.example/",))
    with pytest.raises(CollabUnavailable) as e:
        made.watch("/communications/onlineMeetings/getAllRecordings", "https://flow.example/hook",
                   (ChangeType.CREATED,))
    assert "GRAPH_ALLOW_METERED" in e.value.remedy and t.calls == []


def test_the_gate_opens_when_the_deployment_says_it_may():
    t = FakeTransport().expect("/subscriptions", method="POST", body={
        "id": "sub-2", "resource": "/communications/onlineMeetings/getAllRecordings",
        "changeType": "created", "notificationUrl": "https://flow.example/hook"})
    made, _ = repo(t, notification_allowlist=("https://flow.example/",), allow_metered=True)
    assert made.watch("/communications/onlineMeetings/getAllRecordings", "https://flow.example/hook",
                      (ChangeType.CREATED,)).id == "sub-2"


def test_the_watches_this_identity_owns_are_listable_because_they_outlive_the_run():
    t = FakeTransport().expect("/subscriptions", body={"value": [
        {"id": "sub-1", "resource": "/drives/d/root", "changeType": "created",
         "notificationUrl": "https://flow.example/hook"}]})
    made, _ = repo(t)
    assert [w.id for w in made.watches()] == ["sub-1"]


def test_a_renewal_reads_the_subscription_first_so_the_new_expiry_can_be_clamped_to_its_resource():
    t = FakeTransport().expect("/subscriptions/sub-1", method="GET",
                               body={"id": "sub-1", "resource": "/chats/c/messages",
                                     "changeType": "created", "notificationUrl": "https://f/x"})
    t.expect("/subscriptions/sub-1", method="PATCH",
             body={"id": "sub-1", "resource": "/chats/c/messages", "changeType": "created",
                   "notificationUrl": "https://f/x", "expirationDateTime": "2026-09-07T08:50:00Z"})
    made, _ = repo(t)
    renewed = made.renew("sub-1", "2027-01-01T00:00:00Z")
    assert renewed.expires == "2026-09-07T08:50:00Z"
    import json
    assert json.loads(t.calls[1]["body"]) == {"expirationDateTime": "2026-09-07T08:50:00Z"}


def test_cancelling_a_subscription_that_is_already_gone_is_not_an_error():
    t = FakeTransport().expect("/subscriptions/sub-1", status=404, body={"error": {"code": "ResourceNotFound"}})
    made, _ = repo(t)
    assert made.unwatch("sub-1") is None


def test_cancelling_reaches_graph_with_the_delete_verb():
    t = FakeTransport().expect("/subscriptions/sub-1", method="DELETE", status=204)
    made, _ = repo(t)
    made.unwatch("sub-1")
    assert t.calls[0]["method"] == "DELETE"


def test_a_refusal_that_is_not_absence_still_travels_out_of_unwatch():
    t = FakeTransport().expect("/subscriptions/sub-1", status=403,
                               body={"error": {"code": "Authorization_RequestDenied"}})
    made, _ = repo(t)
    with pytest.raises(CollabUnavailable):
        made.unwatch("sub-1")


# ------------------------------------------------------------------ every failure becomes a sentence
def test_a_forbidden_listing_becomes_a_sentence_naming_the_grant_and_the_capability():
    t = FakeTransport().expect("/sites", status=403, body={"error": {
        "code": "Authorization_RequestDenied", "message": "Insufficient privileges"}})
    made, _ = repo(t)
    with pytest.raises(CollabUnavailable) as e:
        made.sites()
    assert e.value.capability == "sites" and "Sites.Read.All" in e.value.remedy
    assert e.value.sentence.endswith(".")


def test_a_throttled_call_becomes_the_typed_throttling_error_with_the_hint():
    t = FakeTransport().expect("/sites", status=429, headers={"Retry-After": "30"}, times=None)
    tokens = FakeTokens("tok", ROLES)
    client = GraphClient(tokens, transport=t, sleep=FakeSleep(), now=lambda: 0.0, max_retries=0)
    made = graph_repository.GraphCollabRepository(client, tokens, now=NOW)
    with pytest.raises(CollabThrottled) as e:
        made.sites()
    assert e.value.retry_after == 30.0 and e.value.capability == "sites"


def test_a_missing_credential_surfaces_as_the_configuration_refusal_it_is():
    made, _ = repo(tokens=FakeTokens(raises=CollabNotConfigured("GRAPH_CLIENT_SECRET")))
    with pytest.raises(CollabNotConfigured):
        made.sites()


# ------------------------------------------------------------------ the factory
def test_build_wires_the_adapter_from_configuration_and_nothing_else_names_it():
    made = graph_repository.build(auth_mode="static", static_token="tok",
                                  meeting_user="chair@lab.example", transport=FakeTransport())
    assert isinstance(made, CollabRepository)
    assert made.client.base_url.startswith("https://graph.microsoft.com")


def test_build_passes_the_deployments_policy_through():
    made = graph_repository.build(auth_mode="none", allow_metered=True,
                                  notification_allowlist=("https://flow.example/",),
                                  base_url="https://graph.microsoft.com/beta",
                                  transport=FakeTransport())
    assert made.allow_metered and made.notification_allowlist == ("https://flow.example/",)
    assert made.client.base_url.endswith("/beta")


def test_a_repository_built_without_a_credential_still_constructs_and_refuses_only_when_called():
    made = graph_repository.build(auth_mode="none", transport=FakeTransport())
    with pytest.raises(CollabNotConfigured):
        made.sites()


# ------------------------------------------------------------------ the offline double
def test_the_fake_provider_satisfies_the_same_port_so_callers_can_swap_it_in():
    from fixtures.graph import FakeGraph
    fake = FakeGraph()
    assert isinstance(fake, CollabRepository)
    assert fake.sites().items[0].name == "Lab"
    assert fake.drives("site-1").items[0].id == "drive-1"
    assert fake.items("drive-1").items[0].name == "notes.docx"
    assert fake.item(ContentHandle.item("drive-1", "item-1")).size == 12
    assert b"".join(fake.open(ContentHandle.item("drive-1", "item-1"))) == b"content"
    assert fake.meetings().items[0].subject == "Design review"
    assert fake.recordings("meeting-1").items[0].kind is MediaKind.RECORDING
    assert fake.transcripts("meeting-1").items[0].kind is MediaKind.TRANSCRIPT
    assert fake.capabilities() == {c: None for c in CAPABILITIES}


def test_the_fake_provider_can_have_one_capability_switched_off():
    from fixtures.graph import FakeGraph
    fake = FakeGraph(capabilities={"recordings": False})
    assert fake.capabilities()["recordings"] is not None and fake.capabilities()["sites"] is None
    with pytest.raises(CollabUnavailable):
        fake.recordings("meeting-1")


def test_the_fake_provider_can_fail_every_call_the_same_way():
    from fixtures.graph import FakeGraph
    fake = FakeGraph(raises=CollabNotConfigured("GRAPH_CLIENT_SECRET"))
    with pytest.raises(CollabNotConfigured):
        fake.sites()


def test_the_fakes_watch_lifecycle_is_the_ports_lifecycle():
    from fixtures.graph import FakeGraph
    fake = FakeGraph()
    made = fake.watch("/drives/d/root", "https://flow.example/hook", (ChangeType.CREATED,))
    assert [w.id for w in fake.watches()] == [made.id]
    assert fake.renew(made.id, "2026-09-07T09:00:00Z").expires == "2026-09-07T09:00:00Z"
    fake.unwatch(made.id)
    assert list(fake.watches()) == []


# ------------------------------------------------------------------ the allow-list, exactly
def test_a_lookalike_host_does_not_pass_an_allowlist_entry_it_merely_starts_with():
    """`https://flow.example` is exactly what an operator types in .env — a prefix match would then
    accept `https://flow.example.evil.com/`, which is the whole attack this control exists to stop."""
    made, t = repo(notification_allowlist=("https://flow.example",))
    with pytest.raises(CollabUnavailable, match=r"flow\.example\.evil\.com"):
        made.watch("/drives/d/root", "https://flow.example.evil.com/hook", (ChangeType.CREATED,))
    assert t.calls == []


def test_an_allowlist_entry_without_a_trailing_slash_still_admits_its_own_host():
    t = FakeTransport().expect("/subscriptions", method="POST", body={
        "id": "sub-1", "resource": "/drives/d/root", "changeType": "created",
        "notificationUrl": "https://flow.example/hook"})
    made, _ = repo(t, notification_allowlist=("https://flow.example",))
    assert made.watch("/drives/d/root", "https://flow.example/hook", (ChangeType.CREATED,)).id == "sub-1"


def test_the_scheme_is_part_of_the_origin_so_an_http_lookalike_cannot_slip_through():
    made, _ = repo(notification_allowlist=("https://flow.example",))
    with pytest.raises(CollabUnavailable, match="https"):
        made.watch("/drives/d/root", "http://flow.example/hook", (ChangeType.CREATED,))


# ------------------------------------------------------------------ malformed caller input
def test_a_malformed_encoded_id_is_a_caller_error_not_a_base64_traceback():
    made, t = repo()
    with pytest.raises(ValueError, match="malformed provider id"):
        made.items("b64.zzz!")
    assert t.calls == []


def test_a_two_hundred_that_is_not_json_becomes_a_sentence_like_any_other_refusal():
    t = FakeTransport().expect("/sites", body="<html>blocked by a proxy</html>")
    made, _ = repo(t)
    with pytest.raises(CollabUnavailable) as e:
        made.sites()
    assert e.value.capability == "sites" and "not JSON" in e.value.reason


# ------------------------------------------------------------------ the deep probe under load
def test_a_throttled_deep_probe_still_renders_a_table_of_remedies():
    """Eight calls in a burst make throttling likely, and the table is what an operator reads — so
    every value in it must expose a reason and a remedy, never just a retry hint."""
    t = FakeTransport().expect("", status=429, headers={"Retry-After": "5"}, times=None)
    tokens = FakeTokens("tok", ROLES)
    client = GraphClient(tokens, transport=t, sleep=FakeSleep(), now=lambda: 0.0, max_retries=0)
    made = graph_repository.GraphCollabRepository(client, tokens, meeting_user="chair@lab.example",
                                                  now=NOW)
    table = made.capabilities(deep=True)
    assert all(isinstance(v, CollabUnavailable) for v in table.values())
    assert "throttled" in table["sites"].reason and "re-run" in table["sites"].remedy


# ------------------------------------------------------------------ the size ceiling
def test_an_over_large_recording_is_refused_as_a_recording_not_as_a_generic_content_failure():
    t = FakeTransport().expect("/content", body=b"x", headers={"Content-Length": "9999999999"})
    made, _ = repo(t, max_fetch_bytes=1024)
    with pytest.raises(CollabUnavailable) as e:
        made.content(ContentHandle.recording(graph_map.meeting_ref("chair@lab.example", "m1"), "r1"))
    assert e.value.capability == "recordings" and "GRAPH_MAX_FETCH_BYTES" in e.value.remedy
    assert t.bodies[-1].closed                      # the refused stream is not left open


def test_an_abandoned_stream_is_closed_so_a_long_lived_server_does_not_leak_sockets():
    t = FakeTransport().expect("/content", body=b"abc")
    made, _ = repo(t)
    chunks = made.open(ContentHandle.item("b!abc", "01")).chunks
    next(chunks)
    chunks.close()                                   # the caller walks away mid-recording
    assert t.bodies[-1].closed


def test_a_fully_read_stream_is_closed_too():
    t = FakeTransport().expect("/content", body=b"abc")
    made, _ = repo(t)
    assert b"".join(made.open(ContentHandle.item("b!abc", "01"))) == b"abc"
    assert t.bodies[-1].closed


def test_a_stream_carries_what_graph_said_about_it_so_a_store_can_refuse_it_early():
    """The size and type Graph declares are knowable ONLY at this moment. Without them a store must
    pay for the whole download before discovering the object is too big, and the caller has to guess
    a media type from the handle — which is exactly what a listing exists to avoid."""
    t = FakeTransport().expect("/content", body=b"abc",
                               headers={"Content-Type": "video/mp4", "Content-Length": "3"})
    made, _ = repo(t)
    stream = made.open(ContentHandle.item("b!abc", "01"))
    assert stream.media_type == "video/mp4" and stream.size == 3
    assert b"".join(stream) == b"abc"


class _Unreachable:
    """A transport that cannot reach Graph at all — the commonest real failure, and the one that had
    no typed shape until `GraphError(0, "Unreachable", …)` existed."""

    def __call__(self, method, url, headers, body=None, timeout=30.0):
        raise graph_repository.GraphError(0, "Unreachable",
                                          "Microsoft Graph could not be reached: connection refused")


def test_a_provider_that_cannot_be_reached_refuses_with_a_sentence_not_a_traceback():
    made, _ = repo(_Unreachable())
    with pytest.raises(CollabUnavailable) as e:
        made.sites()
    assert e.value.capability == "sites" and "could not be reached" in e.value.reason
    assert e.value.sentence.endswith(".") and e.value.remedy


def test_a_deep_probe_never_reports_a_capability_available_because_the_network_is_down():
    """The dangerous direction: `explain()` once read "not >= 400" as success, so an unreachable
    tenant produced a table of green ticks — the exact opposite of what an operator needs."""
    made, _ = repo(_Unreachable())
    table = made.capabilities(deep=True)
    assert set(table) == set(CAPABILITIES)
    assert all(isinstance(v, CollabUnavailable) for v in table.values()), "nothing may look available"
    # Every capability this token's ROLES cover is unavailable because the tenant is unreachable.
    # `uploads` is unavailable for a better reason — the read identity has no write permission, which
    # the role table already knows — and reporting the permission rather than the network is the more
    # useful answer, so it is asserted separately rather than lumped in.
    reachable = [c for c in CAPABILITIES if c != "uploads"]
    assert all("could not be reached" in table[c].reason for c in reachable)
    assert "permission" in table["uploads"].remedy.lower()


def test_the_meeting_resolution_cache_is_bounded_because_the_server_outlives_every_call():
    """The container binds the repository as a SINGLETON in a long-lived server, so a cache keyed on
    every join URL ever seen would grow for the life of the process. Oldest out, newest kept — and a
    re-used entry is still a hit, so the saving it exists for survives."""
    t = FakeTransport().expect("/onlineMeetings", body={"value": [{"id": "m-real"}]}, times=None)
    made, _ = repo(t)
    made._resolve("chair@lab.example", "https://teams.example/keep")
    for n in range(graph_repository.RESOLVED_CACHE):
        made._resolve("chair@lab.example", f"https://teams.example/{n}")
        made._resolve("chair@lab.example", "https://teams.example/keep")     # kept warm
    assert len(made._resolved) <= graph_repository.RESOLVED_CACHE
    assert ("chair@lab.example", "https://teams.example/keep") in made._resolved
    before = len(t.calls)
    assert made._resolve("chair@lab.example", "https://teams.example/keep") == "m-real"
    assert len(t.calls) == before, "a cached meeting must not be looked up again"


# ---------------------------------------------------------------- uploads (WRITE)
def test_put_sends_the_bytes_as_content_not_as_json():
    """Every other verb json-encodes its body and forces application/json, which is right for a
    Graph resource and wrong for content: an upload's bytes ARE the body, with the caller's type."""
    t = FakeTransport()
    t.expect("/content", method="PUT", body={"id": "new-1", "name": "minutes.json", "size": 2})
    made, _ = repo(t)
    item = made.put("collab://item/drive-1/folder-9", "minutes.json", b"{}", "application/json")
    assert item.id == "new-1" and item.drive_id == "drive-1"
    sent = t.calls[-1]
    assert sent["body"] == b"{}", "the bytes travelled unaltered"
    assert sent["headers"]["Content-Type"] == "application/json"


def test_put_refuses_content_over_the_simple_upload_ceiling_before_a_byte_moves():
    """Above it an upload needs a resumable session — a lot of machinery for the documents this lab
    writes back — so it refuses with a sentence naming the ceiling and the setting instead."""
    t = FakeTransport()
    made, _ = repo(t, max_upload_bytes=8)
    with pytest.raises(CollabUnavailable) as e:
        made.put("collab://item/drive-1/folder-9", "big.json", b"x" * 9)
    assert e.value.capability == "uploads"
    assert "ceiling" in e.value.reason and "GRAPH_MAX_UPLOAD_BYTES" in e.value.remedy
    assert t.calls == [], "nothing was sent"


def test_put_replaces_rather_than_accumulating_copies():
    """A re-run of the same meeting should correct its own output, not leave `minutes 1.json`."""
    t = FakeTransport()
    t.expect("/content", method="PUT", body={"id": "n", "name": "m.json", "size": 2})
    made, _ = repo(t)
    made.put("collab://item/drive-1/folder-9", "m.json", b"{}")
    assert "conflictBehavior=replace" in t.calls[-1]["url"]


def test_put_writes_into_a_folder_named_by_an_id_never_a_path():
    """A folder is named the way everything else here is — by an id a listing minted."""
    t = FakeTransport()
    made, _ = repo(t)
    for bad, _why in (("collab://recording/m/r", "not a folder"), ("not-a-handle", "not a handle")):
        with pytest.raises(ValueError):
            made.put(bad, "m.json", b"{}")
    with pytest.raises(ValueError, match="name"):
        made.put("collab://item/drive-1/folder-9", "sub/dir/m.json", b"{}")


def test_writes_use_their_own_credential_when_one_is_configured():
    """The read app holds only read grants and its NAME says so. A credential that can overwrite
    anything it can see belongs to the one service that writes, not to every read path — so `put`
    goes through its own client while everything else keeps the reader's."""
    read_t, write_t = FakeTransport(), FakeTransport()
    write_t.expect("/content", method="PUT", body={"id": "n", "name": "m.json", "size": 2})
    read_t.expect("/drive/root", body={"id": "d", "name": "Documents"})
    writer = GraphClient(FakeTokens("writer-token"), transport=write_t, sleep=FakeSleep(), now=lambda: 0.0)
    made, _ = repo(read_t, write_client=writer)

    made.put("collab://item/drive-1/folder-9", "m.json", b"{}")
    assert write_t.calls and not read_t.calls, "the write went out on the write credential"
    assert write_t.calls[-1]["headers"]["Authorization"] == "Bearer writer-token"


def test_without_a_writer_the_upload_uses_the_reader_and_is_simply_refused():
    """Not a fallback so much as an honest default: no writer means the upload asks with a token
    that lacks the permission, and Graph's refusal names it. Better than a silent second path."""
    t = FakeTransport()
    made, _ = repo(t)
    assert made.write_client is made.client
