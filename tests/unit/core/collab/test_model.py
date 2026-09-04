"""src/lab/core/collab/model.py — the COLLABORATION domain's value objects: the things a
collaboration provider holds (Site, Drive, DriveItem, Meeting, MediaRecord, Watch), the opaque
`collab://` ContentHandle that names fetchable content, and the cursor-paged Page.
Pure: frozen, hashable, no I/O, no vendor word anywhere.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/core/collab/test_model.py"""
import pytest

from lab.core.collab.model import (DEFAULT_LIMIT, MAX_LIMIT, ChangeType, ContentHandle, Drive,
                                   DriveItem, HandleKind, MediaKind, MediaRecord, Meeting, Page,
                                   Site, Watch, clamp_limit)


# ------------------------------------------------------------------ ContentHandle
def test_handle_round_trips_through_its_text_form():
    h = ContentHandle.item("drive-1", "item-9")
    assert str(h) == "collab://item/drive-1/item-9"
    assert ContentHandle.parse(str(h)) == h
    assert h.kind is HandleKind.ITEM and h.scope == "drive-1" and h.id == "item-9"


def test_the_three_kinds_have_named_constructors_and_parse_back():
    rec = ContentHandle.recording("meet-1", "rec-2")
    tra = ContentHandle.transcript("meet-1", "tra-3")
    assert str(rec) == "collab://recording/meet-1/rec-2" and rec.kind is HandleKind.RECORDING
    assert str(tra) == "collab://transcript/meet-1/tra-3" and tra.kind is HandleKind.TRANSCRIPT
    assert ContentHandle.parse(str(rec)) == rec and ContentHandle.parse(str(tra)) == tra
    assert rec != tra                                        # the KIND is part of the identity


def test_a_kind_given_as_a_string_is_coerced_so_construction_and_parsing_agree():
    assert ContentHandle("item", "d", "i") == ContentHandle(HandleKind.ITEM, "d", "i")


def test_is_handle_is_the_cheap_syntactic_check():
    assert ContentHandle.is_handle("collab://item/d/i")
    assert not ContentHandle.is_handle("art://3f2a/malaffi.vsdx")
    assert not ContentHandle.is_handle("/tmp/x.docx") and not ContentHandle.is_handle(None)


def test_handles_are_frozen_and_hashable():
    h = ContentHandle.item("d", "i")
    with pytest.raises(Exception):
        h.id = "z"
    assert {h, ContentHandle.item("d", "i")} == {h}


@pytest.mark.parametrize("bad", ["", "collab:/item/d/i", "art://d/i", "collab://item/d",
                                 "collab://item/d/i/extra", "collab://folder/d/i", "collab://item//i",
                                 "collab://"])
def test_parse_refuses_anything_that_is_not_a_well_formed_handle(bad):
    with pytest.raises(ValueError, match="content handle"):
        ContentHandle.parse(bad)


@pytest.mark.parametrize("bad", ["https://host/x", "d/i", "id with space", "id?sig=abc", "id#frag"])
def test_a_handle_may_never_carry_a_url_or_a_credential(bad):
    """The whole point of a handle: it is an ID PAIR, so it can be logged, traced and handed to an
    agent. A download URL (a SAS/CDN link with a token in its query) must never end up inside one."""
    with pytest.raises(ValueError, match="never a URL or a credential"):
        ContentHandle.item(bad, "i")
    with pytest.raises(ValueError, match="never a URL or a credential"):
        ContentHandle.item("d", bad)


# ------------------------------------------------------------------ the things a provider holds
def test_a_site_and_a_drive_are_identified_values():
    site = Site(id="s1", name="Clinical Governance", description="policies")
    drive = Drive(id="d1", name="Documents", site_id="s1")
    assert (site.id, site.name, site.description) == ("s1", "Clinical Governance", "policies")
    assert (drive.id, drive.name, drive.site_id) == ("d1", "Documents", "s1")
    assert {site, Site("s1", "Clinical Governance", "policies")} == {site}      # frozen + hashable
    assert Drive("d1", "Documents").site_id == ""


def test_a_drive_says_whether_a_place_or_a_person_owns_it():
    """A drive hangs off a SITE or off a PERSON, and which one decides where its content is found —
    a meeting recorded ad hoc lands in the organiser's personal drive, not in any site's library. So
    the object carries its owner rather than leaving the caller to remember how it was reached."""
    library = Drive("d1", "Documents", site_id="s1")
    personal = Drive("d2", "Files", owner="maria@lab.example")
    assert (library.owner, library.site_id) == ("", "s1")
    assert (personal.owner, personal.site_id) == ("maria@lab.example", "")
    assert {personal, Drive("d2", "Files", owner="maria@lab.example")} == {personal}   # still hashable


@pytest.mark.parametrize("factory", [lambda: Site("", "n"), lambda: Drive(" ", "n"),
                                     lambda: DriveItem("", "n", "d"), lambda: Meeting(""),
                                     lambda: MediaRecord("", MediaKind.RECORDING, "m"),
                                     lambda: Watch("", "r", "https://cb", ["created"])])
def test_every_object_refuses_to_exist_without_an_id(factory):
    with pytest.raises(ValueError, match="id"):
        factory()


def test_a_file_names_its_own_content_handle():
    f = DriveItem(id="i1", name="policy.docx", drive_id="d1", size=120, modified="2026-09-04T10:00:00Z",
                  path="Policies")
    assert f.handle == ContentHandle.item("d1", "i1") and not f.folder
    assert (f.size, f.modified, f.path) == (120, "2026-09-04T10:00:00Z", "Policies")


def test_a_folder_has_no_content_to_fetch():
    folder = DriveItem(id="i2", name="Policies", drive_id="d1", folder=True)
    with pytest.raises(ValueError, match="folder"):
        folder.handle


def test_a_meeting_keeps_its_participants_as_a_hashable_tuple():
    m = Meeting(id="m1", subject="EA review", organizer="maria", start="2026-09-04T09:00:00Z",
                end="2026-09-04T10:00:00Z", participants=["maria", "omar"])
    assert m.participants == ("maria", "omar") and {m} == {m}      # a list in, a tuple out
    assert Meeting("m1").participants == ()


def test_one_shape_carries_a_recording_and_a_transcript_distinguished_by_its_kind():
    rec = MediaRecord(id="r1", kind=MediaKind.RECORDING, meeting_id="m1", created="2026-09-04T10:05:00Z",
                      media_type="video/mp4", size=8_000_000)
    tra = MediaRecord(id="t1", kind="transcript", meeting_id="m1", media_type="text/vtt")
    assert rec.kind is MediaKind.RECORDING and tra.kind is MediaKind.TRANSCRIPT     # a string is coerced
    assert rec.handle == ContentHandle.recording("m1", "r1")
    assert tra.handle == ContentHandle.transcript("m1", "t1")
    assert (rec.size, tra.size) == (8_000_000, 0)


def test_every_media_kind_is_a_handle_kind_so_a_record_can_always_name_its_content():
    assert {k.value for k in MediaKind} <= {k.value for k in HandleKind}


def test_a_watch_is_a_subscription_to_named_changes_on_a_resource():
    w = Watch(id="w1", resource="drives/d1/root", notification_url="https://flow.example/hook",
              events=["created", ChangeType.UPDATED], expires="2026-09-07T00:00:00Z")
    assert w.events == (ChangeType.CREATED, ChangeType.UPDATED)      # strings coerced, order kept
    assert w.notification_url == "https://flow.example/hook" and {w} == {w}


@pytest.mark.parametrize("events", [(), []])
def test_a_watch_without_an_event_is_a_subscription_to_nothing(events):
    with pytest.raises(ValueError, match="at least one change"):
        Watch("w1", "drives/d1/root", "https://flow.example/hook", events)


def test_a_watch_needs_somewhere_to_notify():
    with pytest.raises(ValueError, match="notification"):
        Watch("w1", "drives/d1/root", "  ", ["created"])


# ------------------------------------------------------------------ paging
def test_a_page_carries_its_items_and_an_opaque_cursor():
    page = Page(items=[Site("s1", "A"), Site("s2", "B")], cursor="next-token")
    assert page.items == (Site("s1", "A"), Site("s2", "B"))          # a list in, a tuple out
    assert page.more and len(page) == 2 and [s.id for s in page] == ["s1", "s2"]


def test_the_last_page_has_no_cursor():
    assert Page().cursor is None and not Page().more and len(Page()) == 0
    assert Page(items=(Site("s1", "A"),), cursor="").cursor is None     # "" is not a cursor
    assert Page(items=(Site("s1", "A"),), cursor="  ").more is False


def test_a_page_is_frozen_and_hashable_like_everything_else_in_the_domain():
    page = Page(items=(Site("s1", "A"),))
    with pytest.raises(Exception):
        page.cursor = "x"
    assert {page, Page(items=(Site("s1", "A"),))} == {page}


def test_the_page_size_is_hard_capped_so_a_listing_cannot_blow_an_agents_context():
    assert clamp_limit(None) == DEFAULT_LIMIT and DEFAULT_LIMIT < MAX_LIMIT
    assert clamp_limit(10) == 10 and clamp_limit(MAX_LIMIT + 5000) == MAX_LIMIT
    assert clamp_limit(0) == 1 and clamp_limit(-3) == 1
