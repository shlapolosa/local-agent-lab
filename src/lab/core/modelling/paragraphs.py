"""What a "paragraph" is, per format (contract 1.4.0, agreed with SAF).

A paragraph is what the format calls one, and ONE split serves both the number the agent is shown and
the passage its quote is checked against:
- a Word document: each non-blank LINE of its extracted text (one Word paragraph or table row each);
- a PDF: each PAGE, separated by a form feed, empty pages included so the number is the page's own;
- anything else: each block separated by one or more blank lines.

How a Word document becomes those lines is `DOCX_EXTRACTION`, implemented by
`lab.platform.docparse.docx_lines` and held to golden files in `contracts/goldens/paragraphs/`.
"""
from __future__ import annotations

import re

__all__ = ["DEFAULT_RULE", "DOCX_EXTRACTION", "PARAGRAPH_RULES", "PDF_PAGE_SEPARATOR", "location_key",
           "numbered", "split"]

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF = "application/pdf"

#: media type -> rule. Anything not named here takes DEFAULT_RULE.
PARAGRAPH_RULES = {DOCX: "line", PDF: "page"}
DEFAULT_RULE = "blank-line-block"
#: Pages of an extracted PDF are separated by a form feed, because a page's own text can hold blank lines.
PDF_PAGE_SEPARATOR = "\f"

DOCX_EXTRACTION = (
    "Body only, in document order: walk w:body's children; each w:p is one line, each top-level w:tbl "
    "is one line per w:tr. A body-level w:sdt is descended into (its w:sdtContent children are walked "
    "in place). EXCLUDED: headers, footers, footnotes, endnotes, comments, text boxes (w:txbxContent), "
    "everything inside mc:AlternateContent (drawings and shapes, both Choice and Fallback) and nested "
    "tables. A paragraph's text is its w:t text in "
    "order, including inline w:sdt content, w:hyperlink text, w:fldSimple result runs and complex-field "
    "result runs (between fldChar separate and end); w:instrText (a field code) is excluded. Tracked "
    "changes read AS ACCEPTED: w:ins and w:moveTo included, w:del and w:moveFrom excluded. w:tab, w:br "
    "and w:cr each become one space; runs of whitespace collapse to one space; the line is trimmed; a "
    "line left empty is skipped and takes no number. A table row's line is its cells' text joined by "
    "' | '; a cell's text is its own paragraphs joined by one space (a nested table contributes "
    "nothing); a vertical-merge continuation cell (w:vMerge without val='restart') is the empty "
    "string; a gridSpan cell appears once and a legacy hMerge continuation is dropped; a row's line is "
    "the join exactly, not trimmed (a leading empty cell starts it with ' | '); a cell-level "
    "w:sdt is walked as the cell it wraps; a row whose cells are all empty is skipped. Lines are joined "
    "by '\\n'. Text over 60000 characters is cut there and a final '[truncated: ...]' line is added.")

_BLANK = re.compile(r"\n\s*\n")


def rule_for(media_type: str) -> str:
    return PARAGRAPH_RULES.get(media_type or "", DEFAULT_RULE)


def split(text: str | None, media_type: str = "") -> list[str]:
    """The paragraphs of a source's text, numbered from 1 by position."""
    text = text or ""
    rule = rule_for(media_type)
    if rule == "line":
        return [line.strip() for line in text.split("\n") if line.strip()]
    if rule == "page":
        return [page.strip() for page in text.split(PDF_PAGE_SEPARATOR)] if text else []
    return [p.strip() for p in _BLANK.split(text) if p.strip()]


def location_key(media_type: str) -> str:
    """Which location key names a paragraph of this format: `page` for a PDF, else `paragraph`."""
    return "page" if rule_for(media_type) == "page" else "paragraph"


def numbered(text: str | None, media_type: str = "") -> str:
    """The text as the agent sees it: each paragraph behind its marker ([¶n] or [page n]). An empty
    page shows nothing but keeps its number, so the next page's marker is still its own page."""
    unit = "page " if rule_for(media_type) == "page" else "¶"
    return "\n\n".join(f"[{unit}{i}] {p}" for i, p in enumerate(split(text, media_type), 1) if p)
