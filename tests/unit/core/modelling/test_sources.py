"""What the modelling agent is shown: each input under a short key, prose numbered by paragraph."""
from lab.core.modelling.provenance import Source
from lab.core.modelling.sources import keyed


def test_the_message_shows_each_source_under_its_key_with_numbered_text():
    from lab.core.modelling.sources import message
    srcs = keyed([Source(ref="art://1/brief.docx", name="brief.docx", media_type="x", text="A.\n\nB."),
                  Source(ref="art://2/d.png", name="d.png", media_type="image/png")])
    text = message(srcs)
    assert "## S1 — brief.docx\n\n[¶1] A.\n\n[¶2] B." in text
    assert "## S2 — d.png" in text and "attached as an image" in text


def test_sources_get_short_stable_keys_in_input_order():
    a = Source(ref="art://1/brief.docx", name="brief.docx", media_type="x", text="t")
    b = Source(ref="art://2/diagram.png", name="diagram.png", media_type="image/png")
    assert keyed([a, b]) == {"S1": a, "S2": b}
