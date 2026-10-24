"""Provenance: what ties one modelled element or relation back to the input it came from (D5)."""
import pytest

from lab.core.modelling.provenance import LOCATION_KEYS, Provenance, Source, check


def _p(**kw):
    base = {"source_ref": "art://a/brief.docx", "location": {"paragraph": 1},
            "quote": "the clinician assesses the referral"}
    return Provenance.from_dict(base | kw)


def test_location_names_where_in_the_source_and_nothing_else():
    assert set(LOCATION_KEYS) == {"page", "paragraph", "figure", "shape"}
    assert _p(location={"page": 2, "paragraph": 4}).location == {"page": 2, "paragraph": 4}
    with pytest.raises(ValueError):
        _p(location={})
    with pytest.raises(ValueError):
        _p(location={"line": 7})


def test_a_provenance_needs_a_source_and_a_quote():
    with pytest.raises(ValueError):
        _p(source_ref="")
    with pytest.raises(ValueError):
        _p(quote="  ")


def test_round_trip_is_lossless():
    p = _p(location={"figure": "2"})
    assert Provenance.from_dict(p.to_dict()) == p


def _sources(**texts):
    return {ref: Source(ref=ref, name=ref.rsplit("/", 1)[-1], media_type="text/plain", text=t)
            for ref, t in texts.items()}


def test_a_quote_found_verbatim_raises_no_question():
    src = _sources(**{"art://a/brief.docx": "Today the clinician\nassesses the referral by hand."})
    assert check(_p(), src) is None          # whitespace across a line break is honest quoting


def test_a_paraphrase_is_flagged_not_failed():
    src = _sources(**{"art://a/brief.docx": "A clinician reviews each referral."})
    assert check(_p(), src) == "quote-not-found"


def test_a_source_the_run_never_read_is_flagged():
    assert check(_p(source_ref="art://b/other.pdf"), _sources(**{"art://a/brief.docx": "x"})) == \
        "unknown-source"


def test_a_source_with_no_text_cannot_confirm_a_quote():
    """An image is read by vision: there is no text to hold the quote against."""
    src = _sources(**{"art://a/brief.docx": None})
    assert check(_p(), src) == "unverifiable"


def test_a_figure_in_a_text_document_is_for_the_architect_to_verify():
    """The figure's words are not in the prose, so a miss would read as a paraphrase. It is not one."""
    src = _sources(**{"art://a/brief.docx": "unrelated prose"})
    assert check(_p(location={"figure": 2}), src) == "unverifiable"
    assert check(_p(location={"page": 4, "shape": "s12"}), src) == "unverifiable"
