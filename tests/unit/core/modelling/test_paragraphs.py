"""What a "paragraph" is, per format (contract 1.4.0, agreed with SAF): the number the agent is shown
and the passage its quote is checked against come from ONE split."""
from lab.core.modelling import paragraphs as P

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_a_word_document_has_one_paragraph_per_non_blank_line():
    text = "Intro line\n\nRow a | b\n   \nLast"
    assert P.split(text, DOCX) == ["Intro line", "Row a | b", "Last"]


def test_a_pdf_has_one_paragraph_per_page_counting_empty_pages():
    text = "page one\n\nstill one\fpage two\f\fpage four"
    assert P.split(text, "application/pdf") == ["page one\n\nstill one", "page two", "", "page four"]


def test_everything_else_splits_on_blank_lines():
    for mt in ("text/markdown", "text/plain", "application/x-unknown", ""):
        assert P.split("a\nb\n\n\nc", mt) == ["a\nb", "c"]


def test_the_marker_names_the_unit():
    assert P.numbered("x\fy", "application/pdf") == "[page 1] x\n\n[page 2] y"
    assert P.numbered("x\ny", DOCX) == "[¶1] x\n\n[¶2] y"
    assert P.numbered("", "text/plain") == ""


def test_an_empty_pdf_page_still_takes_its_number_in_the_message():
    assert P.numbered("x\f\fz", "application/pdf") == "[page 1] x\n\n[page 3] z"


def test_the_location_key_checked_follows_the_rule():
    assert P.location_key("application/pdf") == "page" and P.location_key(DOCX) == "paragraph"
    assert P.location_key("text/markdown") == "paragraph"
