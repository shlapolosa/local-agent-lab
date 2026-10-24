"""What the modelling agent is shown: each input under a short key, prose numbered by paragraph."""
from lab.core.modelling.provenance import Source
from lab.core.modelling.sources import keyed, numbered


def test_paragraphs_are_numbered_from_one_on_blank_lines():
    text = "First para\nstill first.\n\n\nSecond.\n\n  \nThird."
    assert numbered(text) == "[¶1] First para\nstill first.\n\n[¶2] Second.\n\n[¶3] Third."


def test_numbering_nothing_is_nothing():
    assert numbered("") == "" and numbered(None) == ""


def test_sources_get_short_stable_keys_in_input_order():
    a = Source(ref="art://1/brief.docx", name="brief.docx", media_type="x", text="t")
    b = Source(ref="art://2/diagram.png", name="diagram.png", media_type="image/png")
    assert keyed([a, b]) == {"S1": a, "S2": b}
