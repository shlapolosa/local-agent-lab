"""`GraphCollabRepository.item_by_url` + `graph_map.share_id` — resolving the address a PERSON has
to the custody handle the fabric's catalogue is keyed by.

The whole point is that it is the PROVIDER that resolves it, never this side guessing: a web URL is
path-based, so it changes the moment anyone renames or moves the file, while the item id behind it
does not. A url that names nothing comes back as NOTHING — an absence, not a refusal, and never a
near-enough match.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/graph/test_item_by_url.py"""
import base64

import pytest

from fixtures.graph import FakeSleep, FakeTokens, FakeTransport
from lab.core.collab import CollabUnavailable, ContentHandle, DriveItem
from lab.substrate.mcp.graph import graph_map, graph_repository
from lab.substrate.mcp.graph.graph_rest import GraphClient

URL = "https://tenant.sharepoint.com/sites/poc/Shared%20Documents/BRS.md"
ITEM = {"id": "01ITEMID", "name": "BRS.md", "size": 42, "webUrl": URL,
        "lastModifiedDateTime": "2026-10-11T09:00:00Z",
        "parentReference": {"driveId": "b!DRIVE", "id": "01PARENT",
                            "path": "/drives/b!DRIVE/root:/Shared Documents"}}


def repo(transport):
    tokens = FakeTokens("tok", ("Files.Read.All",))
    client = GraphClient(tokens, transport=transport, sleep=FakeSleep(), now=lambda: 0.0)
    return graph_repository.GraphCollabRepository(client, tokens)


# ------------------------------------------------------------------ the encoding
def test_a_share_id_is_the_urls_unpadded_url_safe_base64_under_the_providers_marker():
    """Microsoft's documented `u!` sharing-token encoding: url-safe base64 with the padding stripped.
    Asserted against `base64` itself rather than a frozen literal, so the property is what is pinned."""
    sid = graph_map.share_id(URL)
    assert sid.startswith("u!") and "=" not in sid and "+" not in sid and "/" not in sid
    assert base64.urlsafe_b64decode(sid[2:] + "=" * (-len(sid[2:]) % 4)).decode() == URL


def test_the_share_id_normalises_first_so_two_shapes_of_one_url_ask_one_question():
    assert graph_map.share_id(f"  {URL}?web=1  ") == graph_map.share_id(URL)


# ------------------------------------------------------------------ the adapter
def test_the_provider_resolves_the_url_and_the_item_carries_its_custody_handle():
    t = FakeTransport().expect("/shares/", body=ITEM)
    item = repo(t).item_by_url(URL)
    assert isinstance(item, DriveItem)
    assert item.handle == ContentHandle.item("b!DRIVE", "01ITEMID")
    # ...asked of the provider, at the documented route, with the url as the share id
    assert f"/shares/{graph_map.share_id(URL)}/driveItem" in t.urls[0]


def test_a_url_that_resolves_to_nothing_is_nothing():
    """Not a refusal and emphatically not a near match: the catalogue's answer to "is this document
    governed" must be able to be NO. A 404 from the provider is the honest absence."""
    assert repo(FakeTransport()).item_by_url(URL) is None      # unmatched = Graph's own 404 shape


def test_a_refusal_is_still_a_refusal():
    """403 is not absence — the lab may simply not be allowed to see it, and answering "not
    catalogued" there would be a lie a reader cannot tell from the truth."""
    t = FakeTransport().expect("/shares/", status=403, body={"error": {"code": "accessDenied", "message": "no"}})
    with pytest.raises(CollabUnavailable):
        repo(t).item_by_url(URL)


@pytest.mark.parametrize("bad", ["", "   ", "collab://item/b!DRIVE/01ITEMID", "/sites/poc/BRS.md"])
def test_anything_that_is_not_a_web_url_never_reaches_the_provider(bad):
    t = FakeTransport()
    with pytest.raises(ValueError):
        repo(t).item_by_url(bad)
    assert t.calls == []
