"""The CollabRepository contract, run against BOTH implementations — the real Graph adapter and the
offline `FakeGraph` double.

Why this file exists: a tool or workflow written against the fake will pass its own tests and then
fail against Microsoft Graph the moment the two disagree about something the port promises. So the
properties `lab/core/collab/port.py` declares in prose are asserted here once, parametrised over
every implementation, and a new provider adapter joins by adding one line to `IMPLEMENTATIONS`.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/graph/test_port_contract.py"""
import pytest

from fixtures.graph import FakeGraph, FakeSleep, FakeTokens, FakeTransport
from lab.core.collab import (CollabError, CollabRepository, ContentHandle, Drive, DriveItem,
                             HandleKind, MAX_LIMIT, Page)
from lab.substrate.mcp.graph import graph_repository
from lab.substrate.mcp.graph.graph_rest import GraphClient

PAGES = {"value": [{"id": f"x{n}", "name": f"n{n}", "displayName": f"n{n}"} for n in range(3)],
         "@odata.nextLink": "https://graph.microsoft.com/v1.0/sites?$skiptoken=NEXT"}


USER_DRIVE = {"id": "b!me", "name": "Personal", "owner": {"user": {"displayName": "Chair"}}}


def graph_adapter():
    """The real adapter, driven by canned Graph payloads — no tenant, no network."""
    transport = (FakeTransport()
                 # the personal-drive route answers a single drive, not a page (rules match in order)
                 .expect("chair%40lab.example/drive", body=USER_DRIVE, times=None)
                 .expect("", body=PAGES, times=None))
    tokens = FakeTokens("tok", ("Sites.Read.All", "Files.Read.All"))
    client = GraphClient(tokens, transport=transport, sleep=FakeSleep(), now=lambda: 0.0)
    return graph_repository.GraphCollabRepository(client, tokens, meeting_user="chair@lab.example")


IMPLEMENTATIONS = {"graph": graph_adapter, "fake": FakeGraph}


@pytest.fixture(params=sorted(IMPLEMENTATIONS), ids=sorted(IMPLEMENTATIONS))
def repository(request):
    return IMPLEMENTATIONS[request.param]()


def test_every_implementation_satisfies_the_port(repository):
    assert isinstance(repository, CollabRepository)


def test_a_listing_is_a_page_whose_cursor_is_opaque_and_echoable(repository):
    """The caller never parses a cursor: it comes back from a page and goes out again unchanged."""
    page = repository.sites()
    assert isinstance(page, Page) and len(page) == len(page.items)
    if page.more:
        assert isinstance(page.cursor, str) and repository.sites(cursor=page.cursor) is not None


def test_a_page_size_is_clamped_by_the_domain_not_by_the_caller(repository):
    """An absurd limit is clamped rather than refused, and no page exceeds the domain's ceiling.
    (WHERE the clamp lands differs: the adapter sends the clamped `$top` and the provider obeys it —
    asserted in test_graph_rest — while the fake truncates. The promise is the same either way.)"""
    assert len(repository.sites(limit=10_000).items) <= MAX_LIMIT
    assert isinstance(repository.sites(limit=1), Page)


def test_a_capability_table_answers_for_every_area_and_never_raises(repository):
    table = repository.capabilities()
    assert set(table) and all(v is None or isinstance(v, CollabError) for v in table.values())


def test_a_persons_own_drive_is_reachable_in_every_implementation(repository):
    """The gap live testing exposed. `drives()` reaches only a SITE's libraries, so an ad-hoc
    meeting's recording — stored in the organiser's own drive — was unreachable through the port at
    all. Both implementations answer one drive, attributed to the person, belonging to no site."""
    drive = repository.user_drive("chair@lab.example")
    assert isinstance(drive, Drive) and drive.id and drive.owner == "chair@lab.example"
    assert drive.site_id == ""
    with pytest.raises(ValueError):
        repository.user_drive("")


def test_a_content_handle_round_trips_through_its_own_parser(repository):
    item = next(i for i in repository.items("drive-1").items if isinstance(i, DriveItem))
    handle = item.handle
    assert ContentHandle.parse(str(handle)) == handle
    assert handle.kind is HandleKind.ITEM


def test_a_handle_of_the_wrong_kind_is_a_caller_error_in_every_implementation(repository):
    with pytest.raises(ValueError):
        repository.item(ContentHandle.recording("chair%40lab.example~m1", "rec-1"))


def test_a_refusal_is_always_typed_and_renders_a_sentence(repository):
    """Nothing an implementation refuses may reach a caller as a status code or a provider's dict."""
    try:
        repository.watch("/drives/d/root", "https://not-allow-listed.example/hook", ("created",))
    except CollabError as e:
        assert e.sentence.endswith(".") and e.to_dict()["capability"]
    except NotImplementedError:                      # a read-only implementation is allowed to say so
        pass
