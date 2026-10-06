"""The Meeting Notes TAB serves this meeting's transcript, minutes and comparison — to members only.

Every request carries the viewer's Teams sign-in token; the service checks it is OURS (entra.validate)
and that the viewer is a MEMBER of the meeting chat it asks about, and a file is served only if it was
recorded for that chat — a ref guessed or copied from elsewhere gets nothing.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/meetingapp/test_tab_files.py"""
from fastapi.testclient import TestClient

from fixtures.fakes import FakeRedis
from lab.substrate.meetingapp import registry, service

CHAT = "19:meeting_x@thread.v2"
FILES = [{"name": "Meeting.soniox-en.minutes.txt", "ref": "art://a1/Meeting.soniox-en.minutes.txt", "lane": "soniox-en"},
         {"name": "Meeting.soniox-en.transcript.txt", "ref": "art://a2/Meeting.soniox-en.transcript.txt", "lane": "soniox-en"}]


def client(members=("member-oid",)):
    r = FakeRedis()
    registry.record_files(CHAT, FILES, client=r)

    async def is_member(chat_id, oid):
        return chat_id == CHAT and oid in members

    def who(tok):
        if tok != "good":
            raise ValueError("bad token")
        return "member-oid"
    app = service.web(client_state="s", who=who, is_member=is_member,
                      read=lambda ref: ("﻿" + ref).encode(), redis=r)
    return TestClient(app)


def test_a_member_sees_this_meetings_files_by_lane():
    got = client().get("/tab/api/files", params={"chat": CHAT}, headers={"Authorization": "Bearer good"})
    assert got.status_code == 200
    assert [f["name"] for f in got.json()["files"]] == [f["name"] for f in FILES]
    assert "ref" not in got.json()["files"][0], "the page addresses a file by name; refs stay server-side"


def test_no_token_or_a_bad_token_is_401_and_a_non_member_is_403():
    c = client()
    assert c.get("/tab/api/files", params={"chat": CHAT}).status_code == 401
    assert c.get("/tab/api/files", params={"chat": CHAT}, headers={"Authorization": "Bearer bad"}).status_code == 401
    assert client(members=()).get("/tab/api/files", params={"chat": CHAT},
                                  headers={"Authorization": "Bearer good"}).status_code == 403


def test_a_member_downloads_a_recorded_file_as_an_attachment():
    got = client().get("/tab/api/file", params={"chat": CHAT, "name": FILES[0]["name"]},
                       headers={"Authorization": "Bearer good"})
    assert got.status_code == 200 and got.content.startswith("﻿".encode())
    assert "attachment" in got.headers["content-disposition"] and FILES[0]["name"] in got.headers["content-disposition"]
    assert got.headers["content-type"].startswith("text/plain")


def test_a_file_not_recorded_for_this_meeting_is_not_served():
    c = client()
    assert c.get("/tab/api/file", params={"chat": CHAT, "name": "someone-elses.minutes.txt"},
                 headers={"Authorization": "Bearer good"}).status_code == 404
    assert c.get("/tab/api/file", params={"chat": "19:other@thread.v2", "name": FILES[0]["name"]},
                 headers={"Authorization": "Bearer good"}).status_code == 403


def test_recording_files_again_replaces_by_name_so_a_rerun_or_the_comparison_does_not_duplicate():
    r = FakeRedis()
    registry.record_files(CHAT, FILES, client=r)
    registry.record_files(CHAT, [{"name": FILES[0]["name"], "ref": "art://new/x", "lane": "soniox-en"},
                                 {"name": "Meeting.comparison.txt", "ref": "art://c/c", "lane": ""}], client=r)
    got = {f["name"]: f["ref"] for f in registry.files_of(CHAT, client=r)}
    assert got[FILES[0]["name"]] == "art://new/x" and len(got) == 3


def test_the_status_page_asks_teams_for_the_viewer_and_lists_the_files():
    page = TestClient(service.web(client_state="s")).get("/tab").text
    assert "getAuthToken" in page and "/tab/api/files" in page and "getContext" in page
