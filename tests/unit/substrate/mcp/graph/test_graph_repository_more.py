"""src/lab/substrate/mcp/graph/graph_repository.py — meetings the OPT-IN meeting app was added to.

The meeting app holds only resource-specific consent: Microsoft grants it a meeting's recordings and
transcripts only where an organiser added it. Measured 5 Oct 2026, that grant LISTS recordings but
cannot download one (a known Microsoft limitation), so the adapter splits the two jobs: the meeting
app's credential PROVES the opt-in, the reader's fetches the bytes. Every test here is about keeping
that split honest — a meeting the app was not added to must stay unreadable however its reference
is phrased.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/graph/test_graph_repository_more.py"""
import pytest

from fixtures.graph import FakeSleep, FakeTokens, FakeTransport
from lab.core.collab import CollabUnavailable, ContentHandle
from lab.substrate.mcp.graph import graph_map, graph_repository
from lab.substrate.mcp.graph.graph_rest import GraphClient

ORGANISER = "11111111-2222-3333-4444-555555555555"      # NOT a configured mailbox
MEETING = "MSoxMTExMTExMS0yMjIy"


def client(token, transport):
    return GraphClient(FakeTokens(token, ()), transport=transport, sleep=FakeSleep(), now=lambda: 0.0)


def made(app_transport=None, reader_transport=None, with_app=True):
    reader_t = reader_transport or FakeTransport()
    app_t = app_transport or FakeTransport()
    repo = graph_repository.GraphCollabRepository(
        client("reader-token", reader_t), FakeTokens("reader-token", ()),
        meeting_user="chair@lab.example",
        meeting_app_client=client("app-token", app_t) if with_app else None)
    return repo, reader_t, app_t


def ref(organiser=ORGANISER, meeting=MEETING):
    return graph_map.meeting_ref(organiser, meeting)


def test_the_meeting_apps_grant_proves_the_opt_in_and_the_reader_fetches_the_bytes():
    app_t = FakeTransport().expect("/recordings", body={"value": [{"id": "rec-1"}]})
    reader_t = FakeTransport().expect("/recordings/rec-1/content", body=b"video")
    repo, _, _ = made(app_t, reader_t)
    assert repo.content(ContentHandle.recording(ref(), "rec-1")).fileobj.read() == b"video"
    proof = app_t.calls[0]
    assert f"/users/{ORGANISER}/onlineMeetings/{MEETING}/recordings" in proof["url"]
    assert proof["headers"]["Authorization"] == "Bearer app-token"
    fetch = reader_t.calls[-1]
    assert fetch["url"].endswith("/recordings/rec-1/content")
    assert fetch["headers"]["Authorization"] == "Bearer reader-token"


def test_a_meeting_the_app_was_not_added_to_is_refused_before_the_reader_is_asked():
    """Microsoft answers the meeting app 403 outside the meetings it was added to. That answer is the
    whole bound: if the reader were asked anyway, its tenant-wide grant would read any meeting."""
    app_t = FakeTransport().expect("/recordings", status=403, body={"error": {"code": "Forbidden"}})
    repo, reader_t, _ = made(app_t)
    with pytest.raises(CollabUnavailable) as e:
        repo.content(ContentHandle.recording(ref(), "rec-1"))
    assert "added" in e.value.reason and "meeting" in e.value.remedy.lower()
    assert reader_t.calls == []


def test_the_proof_is_taken_once_per_meeting_not_once_per_call():
    app_t = FakeTransport().expect("/recordings", body={"value": []}, times=None)
    reader_t = FakeTransport().expect("/content", body=b"x", times=None).expect(
        "/transcripts", body={"value": []}, times=None)
    repo, _, _ = made(app_t, reader_t)
    repo.content(ContentHandle.recording(ref(), "rec-1"))
    repo.content(ContentHandle.transcript(ref(), "tr-1"))
    repo.transcripts(ref())
    assert len(app_t.calls) == 1


def test_listing_an_opted_in_meetings_transcripts_goes_through_the_same_gate():
    app_t = FakeTransport().expect("/recordings", body={"value": []})
    reader_t = FakeTransport().expect("/transcripts", body={"value": [{"id": "tr-1"}]})
    repo, _, _ = made(app_t, reader_t)
    page = repo.transcripts(ref())
    assert [r.id for r in page.items] and len(app_t.calls) == 1


def test_an_unconfigured_organiser_must_be_an_object_id_not_a_mailbox_name():
    """The opt-in path never resolves a UPN: that lookup would run on the READER's directory grant,
    for any name a caller supplies, before any proof was taken."""
    repo, reader_t, app_t = made()
    with pytest.raises(CollabUnavailable):
        repo.recordings(ref(organiser="ceo@lab.example"))
    assert reader_t.calls == [] and app_t.calls == []


def test_an_unconfigured_organisers_meeting_by_join_url_is_refused():
    """A join URL is resolved by FILTERING the organiser's meetings with the reader — a read taken
    before the proof could be. The app is told meeting ids, so it never needs one."""
    repo, reader_t, app_t = made()
    with pytest.raises(CollabUnavailable):
        repo.recordings(ref(meeting="https://teams.microsoft.com/l/meetup-join/x"))
    assert reader_t.calls == [] and app_t.calls == []


def test_without_a_meeting_app_an_unconfigured_organiser_is_refused_as_before():
    repo, reader_t, _ = made(with_app=False)
    with pytest.raises(CollabUnavailable):
        repo.recordings(ref())
    assert reader_t.calls == []


def test_a_configured_mailbox_needs_no_proof():
    """The existing path — a deployment that reads its own configured mailbox — is unchanged."""
    reader_t = (FakeTransport().expect("/users/chair%40lab.example", body={"id": "chair-oid"})
                .expect("/recordings", body={"value": []}))
    repo, _, app_t = made(reader_transport=reader_t)
    repo.recordings(ref(organiser="chair@lab.example"))
    assert app_t.calls == []


def test_build_wires_the_meeting_app_only_when_its_credential_is_configured(monkeypatch):
    built = graph_repository.build(tenant_id="t", client_id="c", client_secret="s", auth_mode="app",
                                   meeting_app_client_id="", meeting_app_client_secret="",
                                   client_factory=lambda *a, **k: None)
    assert built.meeting_app_client is None
    built = graph_repository.build(tenant_id="t", client_id="c", client_secret="s", auth_mode="app",
                                   meeting_app_client_id="app", meeting_app_client_secret="sec",
                                   client_factory=lambda *a, **k: None)
    assert built.meeting_app_client is not None and built.meeting_app_client is not built.client


def test_a_throttled_proof_is_reported_as_throttled_not_as_a_meeting_that_did_not_opt_in():
    """'Not added' tells an organiser to change something; a 429 needs only a retry. Confusing the
    two would send a person to re-add an app that was there all along."""
    from lab.core.collab import CollabThrottled
    app_t = FakeTransport().expect("/recordings", status=429, headers={"retry-after": "3"},
                                   body={"error": {"code": "TooManyRequests"}}, times=None)
    repo, reader_t, _ = made(app_t)
    with pytest.raises(CollabThrottled):
        repo.recordings(ref())
    assert reader_t.calls == []
