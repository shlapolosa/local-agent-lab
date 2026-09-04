"""src/lab/substrate/mcp/graph/server.py — the COLLABORATION port as governed tools, through an
in-memory fastmcp Client and the offline `FakeGraph`, OFFLINE. Asserts the tool surface matches the
contract catalogue, the schemas an agent reads, every render shape (handles, pages, cursors), that a
typed refusal arrives as a SENTENCE rather than a status code, that `collab_fetch` STREAMS into the
upload store instead of buffering, and that the write tools are the ones the WRITE grant names.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/graph/test_server.py"""
import asyncio
import os
import runpy

import pytest
from fastmcp import Client

from fixtures.graph import FakeGraph
from lab.core.collab import (CAPABILITIES, ChangeType, CollabUnavailable, ContentHandle,
                             ContentStream, Drive, DriveItem, MediaKind, MediaRecord, Meeting, Site)
from lab.platform import config
from lab.platform.contracts import CollabTools
from lab.substrate import artifacts
from lab.substrate.mcp.graph import server as srv

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), *[".."] * 5))
SERVER_FILE = os.path.join(ROOT, "src", "lab", "substrate", "mcp", "graph", "server.py")

HANDLE = "collab://item/drive-1/item-1"


class FakeUploads:
    """The upload store, as a real backend behaves: it READS the object in bounded pieces and never
    whole. `put` is fatal — a fetched recording that went by value would be held in RAM twice."""

    def __init__(self, chunk=8):
        self.chunk, self.data, self.calls = chunk, b"", []

    def put(self, *args, **kwargs):
        raise AssertionError("collab_fetch must stream — put() buffers the whole object")

    def put_stream(self, name, fileobj, content_type="application/octet-stream", size_hint=None):
        self.calls.append({"name": name, "content_type": content_type, "size_hint": size_hint,
                           "fileobj": fileobj})
        while True:
            part = fileobj.read(self.chunk)
            assert len(part) <= self.chunk, "the source handed out more than it was asked for"
            if not part:
                break
            self.data += part
        return f"art://fake/{name}"


class Lazy(FakeGraph):
    """A provider whose `open()` counts how many chunks have actually been PULLED, so a server that
    drained the iterator before handing it to the store is visible rather than merely suspected."""

    def __init__(self, chunks, **kw):
        super().__init__(**kw)
        self.chunks, self.pulled = list(chunks), 0

    def open(self, handle):
        self._check("content", str(handle))

        def pull():
            for chunk in self.chunks:
                self.pulled += 1
                yield chunk

        return ContentStream(pull(), "application/octet-stream", sum(len(c) for c in self.chunks))


@pytest.fixture
def graph():
    return FakeGraph()


@pytest.fixture
def uploads():
    return FakeUploads()


@pytest.fixture
def server(graph, uploads):
    with srv.server.container.collab.override(graph), \
         srv.server.container.uploads.override(uploads):
        yield srv.server


def call(server, _tool, **args):
    async def go():
        async with Client(server.mcp) as c:
            return await c.call_tool(_tool, args)
    return asyncio.run(go()).data


def call_error(server, _tool, **args) -> str:
    async def go():
        async with Client(server.mcp) as c:
            r = await c.call_tool(_tool, args, raise_on_error=False)
            assert r.is_error, f"{_tool} should have failed"
            return r.content[0].text
    return asyncio.run(go())


def tools(server):
    async def go():
        async with Client(server.mcp) as c:
            return {t.name: t for t in await c.list_tools()}
    return asyncio.run(go())


# ---------------------------------------------------------------- the tool surface
def test_the_server_registers_exactly_the_contract_catalogue(server):
    by = tools(server)
    assert set(by) == CollabTools.names()
    assert set(CollabTools.READ) | set(CollabTools.WRITE) == set(by)
    assert all(len(by[n].description or "") > 80 for n in by), "an agent picks a tool by its description"


def test_the_schemas_say_what_an_agent_must_supply(server):
    by = tools(server)
    assert by[CollabTools.sites].inputSchema.get("required", []) == []
    assert by[CollabTools.drives].inputSchema["required"] == ["site_id"]
    assert by[CollabTools.user_drive].inputSchema["required"] == ["user_id"]
    assert by[CollabTools.list].inputSchema["required"] == ["drive_id"]
    assert by[CollabTools.item].inputSchema["required"] == ["handle"]
    assert by[CollabTools.fetch].inputSchema["required"] == ["handle"]
    assert by[CollabTools.watch].inputSchema["required"] == ["resource", "notification_url"]
    assert by[CollabTools.unwatch].inputSchema["required"] == ["watch_id"]
    listing = by[CollabTools.list].inputSchema["properties"]
    assert set(listing) == {"drive_id", "path", "limit", "cursor"}
    assert "cursor" in by[CollabTools.sites].inputSchema["properties"]


def test_the_descriptions_teach_the_two_rules_a_caller_must_know(server):
    by = tools(server)
    assert "art://" in by[CollabTools.fetch].description and "never" in by[CollabTools.fetch].description.lower()
    assert "collab://" in by[CollabTools.item].description
    assert "cursor" in by[CollabTools.sites].description.lower()
    for name in CollabTools.WRITE:
        assert "subscription" in by[name].description.lower()


# ---------------------------------------------------------------- capabilities
def test_capabilities_reports_the_whole_table_and_never_raises(server):
    out = call(server, CollabTools.capabilities)
    assert sorted(out["available"]) == sorted(CAPABILITIES) and out["unavailable"] == {}
    assert out["deep"] is False


def test_an_unavailable_capability_is_reported_as_a_sentence_with_its_remedy(uploads):
    off = FakeGraph(capabilities={"recordings": False})
    with srv.server.container.collab.override(off), srv.server.container.uploads.override(uploads):
        out = call(srv.server, CollabTools.capabilities, deep=True)
    assert "recordings" not in out["available"] and out["deep"] is True
    row = out["unavailable"]["recordings"]
    assert row["capability"] == "recordings" and row["sentence"].endswith(".")
    assert off.calls[0] == ("capabilities", True)          # the deep flag reaches the provider


def test_a_capability_the_provider_stayed_silent_about_is_not_reported_available(uploads):
    """The safe default for a capability table is the pessimistic one. An adapter that omits a key
    must not have it read as a green tick — silence is not a yes."""
    class Partial(FakeGraph):
        def capabilities(self, deep=False):
            return {"sites": None}

    with srv.server.container.collab.override(Partial()), srv.server.container.uploads.override(uploads):
        out = call(srv.server, CollabTools.capabilities)
    assert out["available"] == ["sites"]
    assert set(out["unavailable"]) == set(CAPABILITIES) - {"sites"}
    assert "did not report" in out["unavailable"]["meetings"]["reason"]


# ---------------------------------------------------------------- reading files
def test_sites_and_drives_render_the_domain_objects(server):
    sites = call(server, CollabTools.sites, query="lab")
    assert sites["items"] == [{"id": "site-1", "name": "Lab", "description": ""}]
    assert sites["cursor"] is None and sites["more"] is False
    drives = call(server, CollabTools.drives, site_id="site-1")
    assert drives["items"] == [{"id": "drive-1", "name": "Documents", "site_id": "site-1", "owner": ""}]


def test_a_persons_own_drive_is_reachable_because_a_site_listing_cannot_find_it(server, graph):
    """The gap this server closes: an ad-hoc meeting's recording is stored in the ORGANISER's drive,
    which belongs to no site, so no amount of collab_sites/collab_drives would ever reach it."""
    out = call(server, CollabTools.user_drive, user_id="maria@lab.example")
    assert out["owner"] == "maria@lab.example" and out["site_id"] == "" and out["id"]
    assert ("drives", "maria@lab.example") in graph.calls
    assert "person" in tools(server)[CollabTools.user_drive].description.lower()


def test_listing_a_drive_hands_back_a_fetchable_handle_per_file(server):
    out = call(server, CollabTools.list, drive_id="drive-1", path="Reports")
    item, = out["items"]
    assert item["name"] == "notes.docx" and item["handle"] == HANDLE and item["folder"] is False
    assert ContentHandle.parse(item["handle"]).kind.value == "item"


def test_a_folder_is_listed_without_a_handle_because_it_holds_no_content(uploads):
    folders = FakeGraph(items=(DriveItem("f1", "Reports", "drive-1", folder=True),))
    with srv.server.container.collab.override(folders), srv.server.container.uploads.override(uploads):
        item, = call(srv.server, CollabTools.list, drive_id="drive-1")["items"]
    assert item["folder"] is True and item["handle"] is None


def test_one_items_metadata_is_read_by_its_handle(server):
    out = call(server, CollabTools.item, handle=HANDLE)
    assert out["id"] == "item-1" and out["size"] == 12 and out["handle"] == HANDLE


def test_a_handle_of_the_wrong_shape_or_kind_is_refused_with_an_explanation(server):
    assert "not a content handle" in call_error(server, CollabTools.item, handle="art://a/b.docx")
    assert "only a file handle" in call_error(server, CollabTools.item,
                                              handle="collab://recording/meeting-1/rec-1")


def test_a_page_carries_its_cursor_out_and_back_untouched(uploads):
    many = FakeGraph(sites=tuple(Site(f"s{n}", f"Site {n}") for n in range(3)))
    with srv.server.container.collab.override(many), srv.server.container.uploads.override(uploads):
        first = call(srv.server, CollabTools.sites, limit=2)
        assert first["more"] is True and len(first["items"]) == 2
        second = call(srv.server, CollabTools.sites, limit=2, cursor=first["cursor"])
    assert second["more"] is False and [i["id"] for i in second["items"]] == ["s2"]


# ---------------------------------------------------------------- meetings
def test_meetings_recordings_and_transcripts_render_with_their_handles(uploads):
    provider = FakeGraph(
        meetings=(Meeting("chair~m1", "Design review", "chair@lab.example", "2026-09-01T09:00:00Z",
                          "2026-09-01T10:00:00Z", ("chair@lab.example", "maria@lab.example")),),
        recordings=(MediaRecord("rec-1", MediaKind.RECORDING, "chair~m1", media_type="video/mp4",
                                size=99),),
        transcripts=(MediaRecord("tr-1", MediaKind.TRANSCRIPT, "chair~m1", media_type="text/vtt"),))
    with srv.server.container.collab.override(provider), srv.server.container.uploads.override(uploads):
        meeting, = call(srv.server, CollabTools.meetings, since="2026-09-01T00:00:00Z")["items"]
        rec, = call(srv.server, CollabTools.recordings, meeting_id="chair~m1")["items"]
        tra, = call(srv.server, CollabTools.transcripts, meeting_id="chair~m1")["items"]
    assert meeting["subject"] == "Design review" and meeting["participants"] == ["chair@lab.example",
                                                                                "maria@lab.example"]
    assert rec["kind"] == "recording" and rec["handle"] == "collab://recording/chair~m1/rec-1"
    assert rec["size"] == 99 and tra["handle"] == "collab://transcript/chair~m1/tr-1"


# ---------------------------------------------------------------- fetch (the one verb that moves bytes)
def test_fetch_streams_the_content_into_the_upload_store_and_returns_a_reference(server, graph, uploads):
    out = call(server, CollabTools.fetch, handle=HANDLE)
    assert out["ref"] == "art://fake/notes.docx" and out["name"] == "notes.docx"
    assert out["bytes"] == len(graph.content) and out["handle"] == HANDLE
    assert uploads.data == graph.content and uploads.calls[0]["size_hint"] == len(graph.content)
    assert "storage" in out["read_with"], "the caller is told how to READ what was fetched"
    assert "art://" in out["read_with"] or out["ref"].startswith("art://")


def test_fetch_pulls_the_source_lazily_rather_than_draining_it_first(uploads):
    """The proof that it streams: the provider's chunks are pulled by the STORE's reads, so a
    gigabyte recording never exists in this process. A server that joined the iterator would have
    pulled every chunk before the store's first read."""
    lazy = Lazy([b"aaaa", b"bbbb", b"cccc"], items=(DriveItem("item-1", "rec.bin", "drive-1", size=12),))
    store = FakeUploads(chunk=4)
    with srv.server.container.collab.override(lazy), srv.server.container.uploads.override(store):
        out = call(srv.server, CollabTools.fetch, handle=HANDLE)
    assert store.data == b"aaaabbbbcccc" and out["bytes"] == 12
    assert lazy.pulled == 3                      # every chunk, but pulled by reads — never joined
    # and what the store was handed is the CLAMPING adapter, whose unbounded read() is capped at one
    # CHUNK (tests/unit/substrate/test_artifacts.py) — never a buffer holding the whole object
    assert isinstance(store.calls[0]["fileobj"], artifacts.IteratorReader)


def test_fetching_a_recording_names_and_types_it_without_a_listing(uploads):
    """A media handle carries no name: the server supplies a neutral one per handle KIND so the
    upload store has something storage-mcp can recognise, and a caller may override it."""
    provider = FakeGraph(content=b"video-bytes")
    with srv.server.container.collab.override(provider), srv.server.container.uploads.override(uploads):
        out = call(srv.server, CollabTools.fetch, handle="collab://recording/m1/rec-1")
        assert out["name"] == "recording-rec-1.mp4" and out["content_type"] == "video/mp4"
        named = call(srv.server, CollabTools.fetch, handle="collab://transcript/m1/tr-1",
                     name="review.vtt")
    assert named["name"] == "review.vtt" and named["content_type"] == "text/vtt"


def test_every_kind_of_handle_a_fetch_can_receive_can_be_named_and_typed():
    """A ratchet on the domain: adding a kind of fetchable content must not leave collab_fetch
    KeyError-ing on it. A FILE takes its name and type from its own metadata; every other kind needs
    an entry here."""
    from lab.core.collab import HandleKind
    assert set(srv.FETCH_DEFAULTS) | {HandleKind.ITEM} == set(HandleKind)


def test_what_the_provider_declares_beats_every_default(uploads):
    """The default table is a FALLBACK, not a guess used in place of fact: a provider that reports a
    media type and a length must have both stored, so storage-mcp reads the truth and the store can
    refuse an over-large object BEFORE the download is paid for."""
    declared = FakeGraph(content=b"0123456789", content_type="audio/wav")
    with srv.server.container.collab.override(declared), srv.server.container.uploads.override(uploads):
        out = call(srv.server, CollabTools.fetch, handle="collab://recording/m1/rec-1")
    assert out["content_type"] == "audio/wav"                    # not video/mp4 from FETCH_DEFAULTS
    assert uploads.calls[0]["size_hint"] == 10 and uploads.calls[0]["content_type"] == "audio/wav"


def test_a_declared_size_reaches_the_store_so_an_over_large_object_is_refused_before_it_moves(uploads):
    """The whole reason a recording is streamed: the store's up-front guard can only fire if it is
    told the size, and only the provider knows it at fetch time."""
    class Refusing(FakeUploads):
        def put_stream(self, name, fileobj, content_type="", size_hint=None):
            raise artifacts.ArtifactTooLarge(f"'{name}' exceeds this store's limit — declared {size_hint} bytes")

    big = FakeGraph(content=b"x" * 64)
    with srv.server.container.collab.override(big), srv.server.container.uploads.override(Refusing()):
        message = call_error(srv.server, CollabTools.fetch, handle="collab://recording/m1/rec-1")
    assert "declared 64 bytes" in message


def test_a_provider_supplied_file_name_is_validated_too(uploads):
    """A provider's own file name is caller input once removed — an `art://<id>/<name>` reference is
    parsed on the slash, so it cannot be trusted just because a caller did not type it."""
    hostile = FakeGraph(items=(DriveItem("item-1", "../../etc/passwd", "drive-1"),))
    with srv.server.container.collab.override(hostile), srv.server.container.uploads.override(uploads):
        assert "not a path" in call_error(srv.server, CollabTools.fetch, handle=HANDLE)
    nameless = FakeGraph(items=(DriveItem("item-1", "   ", "drive-1"),))
    with srv.server.container.collab.override(nameless), srv.server.container.uploads.override(uploads):
        out = call(srv.server, CollabTools.fetch, handle=HANDLE)
    assert out["name"] == "item-item-1", "a nameless object must not mint art://<id>/"


def test_a_fetch_name_is_a_name_not_a_path(server):
    """`art://<id>/<name>` is parsed on the slash — a name carrying one would mint an unreadable ref."""
    assert "not a path" in call_error(server, CollabTools.fetch, handle=HANDLE, name="a/b.docx")


def test_a_refusal_from_the_provider_arrives_as_a_sentence_never_a_status(uploads):
    off = FakeGraph(capabilities={"content": False})
    with srv.server.container.collab.override(off), srv.server.container.uploads.override(uploads):
        message = call_error(srv.server, CollabTools.fetch, handle=HANDLE)
    assert message.endswith(".") and "Remedy:" in message and "content is unavailable" in message


# ---------------------------------------------------------------- the write side
def test_the_subscription_tools_are_exactly_the_write_grant(server):
    assert set(CollabTools.WRITE) == {CollabTools.watch, CollabTools.watch_renew, CollabTools.unwatch}
    made = call(server, CollabTools.watch, resource="/drives/drive-1/root",
                notification_url="https://flow.example/hook", events=["created", "updated"])
    assert made["events"] == ["created", "updated"] and made["notification_url"] == "https://flow.example/hook"
    listed = call(server, CollabTools.watches)
    assert [w["id"] for w in listed["items"]] == [made["id"]]
    renewed = call(server, CollabTools.watch_renew, watch_id=made["id"], expires="2026-09-30T00:00:00Z")
    assert renewed["expires"] == "2026-09-30T00:00:00Z"
    gone = call(server, CollabTools.unwatch, watch_id=made["id"])
    assert gone == {"watch_id": made["id"], "removed": True}
    assert call(server, CollabTools.watches)["items"] == []


def test_a_watch_defaults_to_creations_and_refuses_a_change_it_cannot_model(server):
    made = call(server, CollabTools.watch, resource="/drives/d/root",
                notification_url="https://flow.example/hook")
    assert made["events"] == [ChangeType.CREATED.value]
    message = call_error(server, CollabTools.watch, resource="/drives/d/root",
                         notification_url="https://flow.example/hook", events=["exploded"])
    assert "exploded" in message and "created" in message


def test_an_un_allow_listed_destination_is_refused_by_the_adapter_as_a_sentence(uploads):
    """The server does not second-guess the policy — it relays the adapter's typed refusal, whole."""
    refusing = FakeGraph(raises=CollabUnavailable(
        "watches", "https://evil.example/hook is not an allow-listed destination",
        "add it to the allow-list"))
    with srv.server.container.collab.override(refusing), srv.server.container.uploads.override(uploads):
        message = call_error(srv.server, CollabTools.watch, resource="/drives/d/root",
                             notification_url="https://evil.example/hook")
    assert "not an allow-listed destination" in message and message.endswith(".")


# ---------------------------------------------------------------- observability is not an egress hole
def test_no_span_attribute_carries_a_person_or_caller_free_text(uploads):
    """Tool arguments and results cross the gateway and are PII-scanned; SPAN attributes are not —
    they go straight to an OTLP endpoint that in this lab is public and unauthenticated. This is the
    first server whose arguments are real people, so the ratchet: drive every tool with arguments
    that are obviously personal, and assert none of them reaches a span."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    person, meeting = "maria.smith@lab.example", "maria.smith%40lab.example~m1"
    provider_double = FakeGraph(
        meetings=(Meeting(meeting, "1:1", person),),
        recordings=(MediaRecord("rec-1", MediaKind.RECORDING, meeting),),
        transcripts=(MediaRecord("tr-1", MediaKind.TRANSCRIPT, meeting),))
    with srv.server.container.collab.override(provider_double), \
         srv.server.container.uploads.override(uploads), \
         srv.server.container.tracer.override(provider.get_tracer("graph-mcp")):
        call(srv.server, CollabTools.user_drive, user_id=person)
        call(srv.server, CollabTools.meetings, organizer=person)
        call(srv.server, CollabTools.sites, query="maria smith severance")
        call(srv.server, CollabTools.recordings, meeting_id=meeting)
        call(srv.server, CollabTools.transcripts, meeting_id=meeting)
        call(srv.server, CollabTools.fetch, handle=f"collab://recording/{meeting}/rec-1")
        call(srv.server, CollabTools.watch, resource=f"/users/{person}/drive/root",
             notification_url="https://flow.example/hook")

    values = [str(v) for span in exporter.get_finished_spans()
              for v in (span.attributes or {}).values()]
    assert values, "the spans were not recorded at all — the ratchet would pass vacuously"
    for leaked in ("maria", "@lab.example", "smith", "severance"):
        assert not [v for v in values if leaked in v.lower()], \
            f"{leaked!r} reached a span attribute: {[v for v in values if leaked in v.lower()]}"
    # ... and the useful, impersonal ones are still there, so the rule cost no observability
    keys = {k for span in exporter.get_finished_spans() for k in (span.attributes or {})}
    assert {"collab.count", "collab.drive", "collab.handle.kind", "collab.organizer.given"} <= keys


# ---------------------------------------------------------------- identity + entry point
def test_server_identity_and_main(server):
    assert srv.SERVICE == "graph-mcp" and srv.server.service == "graph-mcp"
    assert srv.server.port == config.GRAPH_MCP_PORT == 9500
    assert srv.server.mcp.name == "graph-mcp"
    import lab.substrate.mcpserver as ms
    served, real = [], ms.serve
    ms.serve = lambda mcp, service, port, **kw: served.append((service, port))
    try:
        runpy.run_path(SERVER_FILE, run_name="__main__")
        assert served == [("graph-mcp", config.GRAPH_MCP_PORT)]
    finally:
        ms.serve = real


def test_the_provider_is_resolved_per_call_so_an_override_is_always_honoured(uploads):
    """Every tool resolves the container PROVIDER rather than a captured client, which is what lets
    a second adapter — or a test double — be swapped into a server that was built at import."""
    one, two = FakeGraph(sites=(Site("a", "A"),)), FakeGraph(sites=(Site("b", "B"),))
    with srv.server.container.uploads.override(uploads):
        with srv.server.container.collab.override(one):
            assert call(srv.server, CollabTools.sites)["items"][0]["id"] == "a"
        with srv.server.container.collab.override(two):
            assert call(srv.server, CollabTools.sites)["items"][0]["id"] == "b"


def test_drives_render_without_a_site_when_they_belong_to_a_person(uploads):
    personal = FakeGraph(drives=(Drive("d9", "Personal", owner="maria@lab.example"),))
    with srv.server.container.collab.override(personal), srv.server.container.uploads.override(uploads):
        out = call(srv.server, CollabTools.user_drive, user_id="maria@lab.example")
    assert out == {"id": "d9", "name": "Personal", "site_id": "", "owner": "maria@lab.example"}


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
