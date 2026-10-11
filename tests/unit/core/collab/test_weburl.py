"""src/lab/core/collab/weburl.py — the ONE normaliser for a provider WEB URL (the address a person
copies out of a browser), used to resolve one to a custody handle.

What it must get right is a balance, not a maximum: the same document asked for in two shapes must
give ONE answer, and two DIFFERENT documents must never collide. So the scheme and host are
lower-cased (DNS is case-insensitive), the fragment and the view-state query go, and the path's
bytes — case and percent-encoding alike — are left exactly as the person copied them.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/core/collab/test_weburl.py"""
import pytest

from lab.core.collab import normalise_web_url as n

SITE = "https://socratesbusiness.sharepoint.com/sites/ai-usecase-intake-poc"
DOC = f"{SITE}/Shared%20Documents/BRS.md"


@pytest.mark.parametrize("given", [
    DOC,
    f"  {DOC}  ",                      # copied out of a chat message
    f"{DOC}?web=1",                    # what SharePoint's "Copy link" adds
    f"{DOC}?csf=1&web=1&e=4Hk2Lm",     # ...and what the Office viewer adds
    f"{DOC}#heading-2",                # a reader's anchor
    f"{DOC}/",                         # a trailing slash
    DOC.replace("https://socratesbusiness", "HTTPS://SocratesBusiness"),   # host typed in another case
])
def test_every_shape_of_the_same_document_normalises_to_one_url(given):
    assert n(given) == DOC


def test_percent_escaping_and_path_case_are_left_exactly_as_given():
    """Two items must never collide. `Shared Documents` and `Shared%20Documents` are the same folder
    to a provider but NOT the same bytes, and `BRS.md`/`brs.md` may be two files on another provider
    — so neither is touched here. Normalising them would be a guess dressed as a convenience."""
    assert n(f"{SITE}/Shared Documents/BRS.md") == f"{SITE}/Shared Documents/BRS.md"
    assert n(f"{SITE}/Shared%20Documents/brs.md") != n(DOC)


def test_a_query_that_names_the_item_is_kept():
    """A classic library view carries the file's own server-relative path in `?id=`; dropping it
    would turn the address of ONE document into the address of the whole library — a different
    thing that still resolves, which is the worst possible failure here."""
    url = f"{SITE}/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2Fx%2FBRS.md&web=1"
    assert n(url) == url
    assert n(f"{SITE}/x.docx?sourcedoc=%7Bguid%7D").endswith("?sourcedoc=%7Bguid%7D")


@pytest.mark.parametrize("bad", ["", "   ", None, "collab://item/d/i", "/sites/x/BRS.md",
                                 "ftp://host/x", "file:///tmp/BRS.md"])
def test_anything_that_is_not_an_absolute_web_url_is_a_caller_error(bad):
    with pytest.raises(ValueError):
        n(bad)
