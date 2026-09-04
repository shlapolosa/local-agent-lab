"""src/lab/substrate/mcp/graph/graph_map.py — Graph JSON in, domain objects out, and nothing else.
Pure, so it is tested alone against captured Graph shapes: this is where a wrong field name becomes
a wrong model, long before a tenant is involved.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/graph/test_graph_map.py"""
from datetime import datetime

import pytest

from lab.core.collab import ChangeType, ContentHandle, MediaKind
from lab.substrate.mcp.graph import graph_map


def at(iso="2026-09-04T09:00:00+00:00"):
    return lambda: datetime.fromisoformat(iso)


# ------------------------------------------------------------------ handle-safe ids
def test_an_id_that_is_already_handle_safe_travels_unchanged_so_a_log_stays_readable():
    assert graph_map.encode_id("01BYE5RZ6QN3ZWBTUFOFD3GSPGOHDJD36K") == "01BYE5RZ6QN3ZWBTUFOFD3GSPGOHDJD36K"
    assert graph_map.decode_id("01BYE5RZ6QN3ZWBTUFOFD3GSPGOHDJD36K") == "01BYE5RZ6QN3ZWBTUFOFD3GSPGOHDJD36K"


def test_an_id_carrying_a_separator_is_encoded_because_a_content_handle_refuses_one():
    """A Teams onlineMeeting id is base64 and may contain `/`; a `collab://` handle refuses that, so
    the adapter hands out an encoded id and decodes it before it touches a URL."""
    raw = "MSp/kYzE3+Njc0Yy04MWQ5="
    safe = graph_map.encode_id(raw)
    assert "/" not in safe and safe.startswith(graph_map.ENCODED_PREFIX)
    assert graph_map.decode_id(safe) == raw
    ContentHandle.recording(safe, "rec-1")                    # the point of the exercise


def test_encoding_round_trips_an_id_that_already_looks_encoded():
    raw = graph_map.ENCODED_PREFIX + "not-really"
    assert graph_map.decode_id(graph_map.encode_id(raw)) == raw


def test_the_separator_the_meeting_reference_uses_is_itself_encoded_away():
    assert graph_map.decode_id(graph_map.encode_id("a~b")) == "a~b"
    assert "~" not in graph_map.encode_id("a~b")


def test_a_meeting_reference_carries_the_user_because_graph_reads_meetings_per_user():
    ref = graph_map.meeting_ref("user@lab.example", "MSp/abc")
    assert graph_map.split_meeting_ref(ref) == ("user@lab.example", "MSp/abc")
    ContentHandle.transcript(ref, "tr-1")                     # still a legal handle scope


def test_a_meeting_reference_without_a_user_is_legal_and_says_so():
    assert graph_map.split_meeting_ref(graph_map.meeting_ref("", "m1")) == ("", "m1")


def test_a_malformed_meeting_reference_is_refused_rather_than_half_read():
    with pytest.raises(ValueError, match="meeting reference"):
        graph_map.split_meeting_ref("no-separator-here")


# ------------------------------------------------------------------ files
def test_a_site_prefers_its_display_name_because_that_is_what_a_person_recognises():
    site = graph_map.site({"id": "lab.sharepoint.com,2c5ea4c0,fa2e1e0f", "name": "design",
                           "displayName": "Design Team", "description": "Where design lives"})
    assert site.id == "lab.sharepoint.com,2c5ea4c0,fa2e1e0f"
    assert site.name == "Design Team" and site.description == "Where design lives"


def test_a_site_without_a_display_name_falls_back_and_never_ends_up_nameless():
    assert graph_map.site({"id": "s1", "name": "design"}).name == "design"
    assert graph_map.site({"id": "s1"}).name == "s1"


def test_a_drive_remembers_the_site_it_was_listed_under():
    drive = graph_map.drive({"id": "b!abc", "name": "Documents", "driveType": "documentLibrary"},
                            site_id="s1")
    assert (drive.id, drive.name, drive.site_id) == ("b!abc", "Documents", "s1")


def test_a_personal_drive_records_whose_it_is_as_an_identifier_never_a_label():
    """A drive reached through a person carries that person as its owner and no site. The owner is
    passed BACK to `user_drive()`, so it must be addressable: a display name would look like an
    answer and then fail every call made with it, so a payload offering only one reports no owner."""
    payload = {"id": "b!me", "name": "OneDrive", "driveType": "business",
               "owner": {"user": {"displayName": "Maria N", "email": "maria@lab.example"}}}
    asked = graph_map.drive(payload, owner="maria@lab.example")
    assert (asked.id, asked.site_id, asked.owner) == ("b!me", "", "maria@lab.example")
    assert graph_map.drive(payload).owner == "maria@lab.example"        # the address, not the label
    assert graph_map.drive({"id": "b!x", "name": "D"}).owner == ""      # a library reports none
    label_only = {"id": "b!y", "name": "D", "owner": {"user": {"displayName": "Maria N"}}}
    assert graph_map.drive(label_only).owner == ""                      # a name nobody can address
    upn = {"id": "b!z", "name": "D", "owner": {"user": {"userPrincipalName": "m@lab.example",
                                                        "email": "other@lab.example"}}}
    assert graph_map.drive(upn).owner == "m@lab.example"                # the UPN wins over a mail alias
    by_id = {"id": "b!q", "name": "D", "owner": {"user": {"id": "8f2c", "displayName": "Maria N"}}}
    assert graph_map.drive(by_id).owner == "8f2c"                       # a directory id addresses too


def test_a_drive_item_carries_everything_a_caller_needs_to_decide_whether_to_fetch_it():
    item = graph_map.drive_item({
        "id": "01ITEM", "name": "report.docx", "size": 12345,
        "lastModifiedDateTime": "2026-09-01T10:00:00Z",
        "file": {"mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        "parentReference": {"driveId": "b!abc", "path": "/drives/b!abc/root:/Reports/2026"}})
    assert (item.id, item.name, item.drive_id) == ("01ITEM", "report.docx", "b!abc")
    assert item.size == 12345 and item.modified == "2026-09-01T10:00:00Z"
    assert item.folder is False and item.path == "Reports/2026"
    assert str(item.handle) == "collab://item/b!abc/01ITEM"


def test_a_folder_is_marked_as_one_so_a_caller_does_not_try_to_fetch_it():
    folder = graph_map.drive_item({"id": "01F", "name": "Reports", "folder": {"childCount": 3},
                                   "parentReference": {"driveId": "b!abc", "path": "/drive/root:"}})
    assert folder.folder is True and folder.path == ""
    with pytest.raises(ValueError):
        folder.handle


def test_the_drive_a_listing_came_from_wins_when_the_payload_omits_the_parent():
    item = graph_map.drive_item({"id": "01", "name": "a.txt"}, drive_id="b!fallback")
    assert item.drive_id == "b!fallback"


def test_a_percent_encoded_folder_path_is_decoded_because_graph_encodes_spaces():
    item = graph_map.drive_item({"id": "01", "name": "a.txt", "parentReference": {
        "driveId": "d", "path": "/drives/d/root:/Board%20Papers/Q3"}})
    assert item.path == "Board Papers/Q3"


# ------------------------------------------------------------------ meetings
ONLINE_MEETING = {
    "id": "MSpkYzE3Njc0Yw==", "subject": "Design review",
    "startDateTime": "2026-09-01T10:00:00Z", "endDateTime": "2026-09-01T11:00:00Z",
    "participants": {"organizer": {"upn": "chair@lab.example",
                                   "identity": {"user": {"id": "u1", "displayName": "Chair"}}},
                     "attendees": [{"upn": "a@lab.example", "identity": {"user": {"id": "u2"}}},
                                   {"identity": {"user": {"id": "u3", "displayName": "Guest"}}}]}}

CALENDAR_EVENT = {
    "id": "AAMkAGI2==", "subject": "Weekly sync", "isOnlineMeeting": True,
    "start": {"dateTime": "2026-09-02T09:00:00.0000000", "timeZone": "UTC"},
    "end": {"dateTime": "2026-09-02T09:30:00.0000000", "timeZone": "UTC"},
    "organizer": {"emailAddress": {"name": "Chair", "address": "chair@lab.example"}},
    "attendees": [{"emailAddress": {"address": "a@lab.example", "name": "A"}}],
    "onlineMeeting": {"joinUrl": "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc/0"}}


def test_an_online_meeting_maps_to_the_domains_meeting():
    meeting = graph_map.meeting(ONLINE_MEETING, user_id="u1")
    assert meeting.subject == "Design review" and meeting.organizer == "chair@lab.example"
    assert meeting.start == "2026-09-01T10:00:00Z" and meeting.end == "2026-09-01T11:00:00Z"
    assert meeting.participants == ("chair@lab.example", "a@lab.example", "Guest")
    assert graph_map.split_meeting_ref(meeting.id) == ("u1", "MSpkYzE3Njc0Yw==")


def test_a_calendar_event_maps_to_the_same_shape_because_that_is_the_listable_window():
    """Graph cannot list a user's onlineMeetings over a time window — the calendar view can, and it
    carries the join URL that resolves to the meeting. So both shapes become one Meeting."""
    meeting = graph_map.meeting(CALENDAR_EVENT, user_id="u1")
    assert meeting.subject == "Weekly sync" and meeting.organizer == "chair@lab.example"
    assert meeting.start == "2026-09-02T09:00:00.0000000Z"
    assert meeting.participants == ("chair@lab.example", "a@lab.example")
    user, token = graph_map.split_meeting_ref(meeting.id)
    assert user == "u1" and token == CALENDAR_EVENT["onlineMeeting"]["joinUrl"]


def test_an_event_that_is_not_online_falls_back_to_its_own_id_and_can_still_be_named():
    meeting = graph_map.meeting({"id": "AAMk", "subject": "Room booking"}, user_id="u1")
    assert graph_map.split_meeting_ref(meeting.id) == ("u1", "AAMk")


def test_a_meeting_with_nothing_but_an_id_still_constructs():
    assert graph_map.meeting({"id": "m1"}).subject == ""


def test_a_zoneless_time_is_only_marked_utc_when_graph_says_it_is_utc():
    js = {"id": "m", "start": {"dateTime": "2026-09-02T09:00:00.0000000", "timeZone": "Pacific Standard Time"}}
    assert graph_map.meeting(js).start == "2026-09-02T09:00:00.0000000"


def test_a_recording_and_a_transcript_are_one_shape_told_apart_by_kind():
    ref = graph_map.meeting_ref("u1", "MSp/abc")
    rec = graph_map.media_record({"id": "rec1", "createdDateTime": "2026-09-01T11:05:00Z",
                                  "recordingContentUrl": "https://graph…"}, MediaKind.RECORDING, ref)
    tr = graph_map.media_record({"id": "tr1", "createdDateTime": "2026-09-01T11:06:00Z"},
                                MediaKind.TRANSCRIPT, ref)
    assert rec.kind is MediaKind.RECORDING and rec.media_type == "video/mp4"
    assert tr.kind is MediaKind.TRANSCRIPT and tr.media_type == "text/vtt"
    assert str(rec.handle) == f"collab://recording/{ref}/rec1"
    assert str(tr.handle) == f"collab://transcript/{ref}/tr1"


def test_a_provider_declared_media_type_and_size_win_over_the_defaults():
    rec = graph_map.media_record({"id": "r", "contentType": "video/webm", "size": 99},
                                 MediaKind.RECORDING, "u~m")
    assert rec.media_type == "video/webm" and rec.size == 99


# ------------------------------------------------------------------ subscriptions
SUBSCRIPTION = {"id": "sub-1", "resource": "/drives/b!abc/root", "changeType": "created,updated",
                "notificationUrl": "https://flow.example/hook", "clientState": "s3cr3t",
                "expirationDateTime": "2026-09-05T00:00:00Z"}


def test_a_subscription_maps_to_a_watch_with_its_changes_split_out():
    watch = graph_map.watch(SUBSCRIPTION)
    assert watch.id == "sub-1" and watch.resource == "/drives/b!abc/root"
    assert watch.notification_url == "https://flow.example/hook"
    assert watch.events == (ChangeType.CREATED, ChangeType.UPDATED)
    assert watch.expires == "2026-09-05T00:00:00Z"


def test_a_change_type_the_domain_does_not_model_is_dropped_not_guessed():
    watch = graph_map.watch({**SUBSCRIPTION, "changeType": "created,recordingAvailable"})
    assert watch.events == (ChangeType.CREATED,)


def test_a_subscription_with_no_change_type_the_domain_knows_is_refused():
    with pytest.raises(ValueError):
        graph_map.watch({**SUBSCRIPTION, "changeType": "recordingAvailable"})


def test_a_subscription_body_is_what_graph_expects_not_what_the_domain_calls_it():
    body = graph_map.subscription_body("/drives/d/root", "https://flow.example/hook",
                                       (ChangeType.CREATED, ChangeType.DELETED),
                                       "2026-09-05T00:00:00Z")
    assert body == {"resource": "/drives/d/root", "notificationUrl": "https://flow.example/hook",
                    "changeType": "created,deleted", "expirationDateTime": "2026-09-05T00:00:00Z"}


# ------------------------------------------------------------------ expiry clamping
def test_an_unstated_expiry_becomes_the_maximum_the_resource_allows_less_a_clock_margin():
    """42,300 minutes for a driveItem and 4,320 for a Teams resource, each less the margin: Graph
    checks the expiry against ITS clock, so asking for the exact maximum fails on any skew."""
    assert graph_map.expiry_for("/drives/d/root", now=at()) == "2026-10-03T17:50:00Z"
    assert graph_map.expiry_for("/communications/onlineMeetings/getAllRecordings",
                                now=at()) == "2026-09-07T08:50:00Z"


def test_a_requested_expiry_beyond_the_providers_maximum_is_clamped_not_rejected():
    assert graph_map.expiry_for("/chats/c/messages", "2027-01-01T00:00:00Z", now=at()) == "2026-09-07T08:50:00Z"


def test_a_requested_expiry_inside_the_maximum_is_honoured():
    assert graph_map.expiry_for("/drives/d/root", "2026-09-05T09:00:00Z", now=at()) == "2026-09-05T09:00:00Z"


def test_an_expiry_below_graphs_floor_is_raised_to_it_because_graph_would_do_that_anyway():
    assert graph_map.expiry_for("/drives/d/root", "2026-09-04T09:10:00Z", now=at()) == "2026-09-04T09:45:00Z"


def test_an_unparseable_expiry_is_treated_as_unstated_rather_than_failing_a_subscription():
    assert graph_map.expiry_for("/drives/d/root", "next tuesday", now=at()) == "2026-10-03T17:50:00Z"


def test_each_resource_family_gets_the_maximum_microsoft_documents_for_it():
    """Pinned to the "Subscription lifetime" table of
    https://learn.microsoft.com/graph/api/resources/subscription, read 4 Sep 2026. Note callRecord
    (a call detail record, 4,230) is NOT callRecording (a meeting artifact, 4,320) — one digit
    apart, and the wrong one makes every such subscription fail."""
    families = {"/communications/presence/u": 60, "/users/u/drive/root": 42300,
                "/sites/s/lists/l": 42300, "/users/u/events": 10080, "/users": 41760,
                "/teams/t/channels/c/messages": 4320, "/something/unmapped": 4320,
                "/communications/callRecords": 4230,
                "/users/u/onlineMeetings/m/recordings": 4320}
    for resource, minutes in families.items():
        assert graph_map.max_expiry_minutes(resource) == minutes


def test_a_malformed_encoded_id_is_a_caller_error_not_a_base64_traceback():
    """An encoded id comes back inside a handle the CALLER supplies, so malformed is ordinary."""
    for bad in ("b64.zzz!", "b64." + "/w==", "b64.////"):
        with pytest.raises(ValueError, match="malformed provider id"):
            graph_map.decode_id(bad)


def test_an_already_encoded_drive_id_is_not_encoded_twice():
    raw = "b!with/slash"
    once = graph_map.drive_item({"id": "01", "name": "a"}, drive_id=graph_map.encode_id(raw))
    assert graph_map.decode_id(once.drive_id) == raw


def test_an_expiry_is_always_emitted_in_the_utc_form_graph_accepts():
    stamped = graph_map.expiry_for("/drives/d/root", "2026-09-05T12:00:00+02:00", now=at())
    assert stamped == "2026-09-05T10:00:00Z"
