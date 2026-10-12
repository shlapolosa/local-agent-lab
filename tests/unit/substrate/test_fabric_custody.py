"""src/lab/substrate/fabric_custody.py — a web URL resolved to the custody pointer the catalogue is
keyed by, through the governed collaboration port.

Retrieval hands an assistant an `https://…` address; the catalogue is keyed by
`collab://item/<drive>/<item>`. This is the one hop between the two, and it asks the PROVIDER rather
than any index of the fabric's own — stated and tested here because the alternative (a url recorded
when the item was swept) is wrong from the moment anybody renames a file.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/test_fabric_custody.py"""
import asyncio

import pytest

from lab.platform.contracts import CollabTools
from lab.substrate import fabric_custody as C

URL = "https://tenant.sharepoint.com/sites/poc/Shared%20Documents/BRS.md"
ITEM = {"id": "item-1", "name": "BRS.md", "drive_id": "drive-1",
        "handle": "collab://item/drive-1/item-1", "folder": False}


def calls(*answers):
    """A gateway transport that records what was asked and answers in order."""
    asked = []

    async def call(batch):
        asked.append(list(batch))
        return list(answers[len(asked) - 1])
    return call, asked


def test_the_pointer_comes_from_the_provider_and_names_the_source_the_catalogue_uses():
    call, asked = calls([ITEM])
    pointer = asyncio.run(C.pointer_for(URL, call=call))
    assert pointer == {"source": "collab", "handle": "collab://item/drive-1/item-1"}
    # ONE governed tool call, and the url is normalised before it leaves
    assert asked == [[(CollabTools.item_by_url, {"url": URL})]]


def test_a_view_state_query_is_normalised_away_so_one_document_asks_one_question():
    call, asked = calls([ITEM])
    asyncio.run(C.pointer_for(f"{URL}?web=1#heading", call=call))
    assert asked[0][0][1] == {"url": URL}


def test_a_url_the_provider_does_not_recognise_is_nothing_never_a_guess():
    """The whole reason this exists: the fallback a missing resolver forces is matching on TITLE,
    which is silently wrong whenever two records share one. Nothing is the right answer."""
    call, _ = calls([None])
    assert asyncio.run(C.pointer_for(URL, call=call)) is None


def test_an_item_the_provider_resolved_but_cannot_be_addressed_is_nothing_too():
    """A folder carries no handle (`collab_list` renders null for one), and a pointer without a
    handle would key nothing — so it is an absence rather than a malformed lookup."""
    call, _ = calls([{"id": "f", "name": "Shared Documents", "folder": True, "handle": None}])
    assert asyncio.run(C.pointer_for(URL, call=call)) is None


@pytest.mark.parametrize("bad", ["", "   ", "collab://item/drive-1/item-1", "/sites/poc/BRS.md"])
def test_anything_that_is_not_a_web_url_never_reaches_the_gateway(bad):
    call, asked = calls([ITEM])
    with pytest.raises(ValueError):
        asyncio.run(C.pointer_for(bad, call=call))
    assert asked == []


def test_a_url_the_provider_REFUSES_is_an_absence_too_and_says_so_out_loud(capsys):
    """Measured in UAT, 12 Oct 2026. SharePoint answers a `shares/{url}` lookup for an address that does
    not resolve with **403, not 404**, so `graph_probe.explain` reads it as a consent problem and the
    caller gets "grant the application permission Files.Read.All … and give it admin consent". A
    researcher who pastes the url of a document the fabric simply does not hold is told the platform is
    misconfigured. `semantic_catalog_by_url` promises the opposite in its own words: "null means exactly
    that no catalogued artifact has that url".

    So a provider refusal on THIS lookup is an absence — but never a silent one. If the application
    really did lose its permission, every lookup would return nothing, and the only thing standing
    between that and "the catalogue is empty" is this line in the log. The trade is deliberate: the
    common case (an uncatalogued document) gets the truthful answer, and the rare case (a real consent
    failure) is loud in the service log rather than in a researcher's chat."""
    boom = RuntimeError("items is unavailable: the Microsoft Graph permission this needs is not consented")

    async def call(batch):
        raise boom

    assert asyncio.run(C.pointer_for(URL, call=call)) is None
    assert "could not resolve" in capsys.readouterr().out.lower()
