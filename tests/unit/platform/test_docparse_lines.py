"""A Word document becomes LINES exactly as contract 1.4.0's DOCX_EXTRACTION states (agreed with SAF),
read here from the committed synthetic golden, one deliberate case per rule."""
import os

from lab.platform import docparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SYNTHETIC = os.path.join(ROOT, "contracts", "goldens", "paragraphs", "synthetic", "source.docx")


def _lines():
    with open(SYNTHETIC, "rb") as f:
        return docparse.docx_lines(f.read())


def test_every_rule_yields_the_stated_line_in_document_order():
    assert _lines() == [
        "1. A plain paragraph.",
        "2. Tab stop definitions are not text; a run tab is one space.",
        "3. A line break inside a paragraph is one space.",
        "4. Runs with spaced words collapse.",
        "5. Inserted text is kept and moved-to text too.",
        "6. A hyperlink's text is kept.",
        "7. A simple field result: 42",
        "8. A complex field: 2026",
        "9. Inline content control: kept",
        "10. A body-level content control is walked in place.",
        "11. A text box is outside the flow",
        "12a. header | 12b. spans two",
        "13a. merge start |  | 13c.",
        " | 14b. two paragraphs | 14c. outer",
        "15a. cell in a control | 15b. | 15c.",
        "16. After the table, in document order.",
    ]


def test_nothing_outside_the_body_flow_is_read():
    text = "\n".join(_lines())
    for absent in ("HEADER", "FOOTER", "TEXTBOX", "CHOICE", "FALLBACK", "NESTED", "CONTINUATION",
                   "DELETED", "MOVEDAWAY", "DATE"):
        assert absent not in text, absent


def test_document_text_for_a_docx_is_its_lines():
    with open(SYNTHETIC, "rb") as f:
        assert docparse.document_text(f.read(), ".docx") == "\n".join(_lines())


def test_a_pdf_separates_pages_with_a_form_feed(monkeypatch):
    class Page:
        def __init__(self, t):
            self.t = t

        def extract_text(self):
            return self.t

    class Reader:
        def __init__(self, _):
            self.pages = [Page("one\n\nstill one"), Page(""), Page("three")]

    import pypdf
    monkeypatch.setattr(pypdf, "PdfReader", Reader)
    assert docparse.document_text(b"%PDF", ".pdf") == "one\n\nstill one\f\fthree"
