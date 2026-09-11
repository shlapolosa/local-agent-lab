"""Build BRS.docx and FRS.docx from docs/fabric/BRS.md and FRS.md (python-docx).

Markdown subset: # headings (1-3), paragraphs with **bold** and `code`, "- " bullets, "1. " numbered items,
| tables |, ![caption](image.png), ``` fenced code, and {{include:relative.md}} (headings demoted one level).

    python scripts/fabric_build_docs.py
"""
from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

ROOT = Path("docs/fabric")


def expand_includes(text: str, base: Path, demote: int = 1) -> str:
    def rep(m):
        inc = (base / m.group(1)).read_text()
        out = []
        for ln in inc.splitlines():
            if ln.startswith("#"):
                ln = "#" * demote + ln
            out.append(ln)
        return "\n".join(out)
    return re.sub(r"^\{\{include:([^}]+)\}\}\s*$", rep, text, flags=re.M)


def add_inline(par, text: str):
    # split on **bold** and `code`
    for tok in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not tok:
            continue
        if tok.startswith("**") and tok.endswith("**"):
            r = par.add_run(tok[2:-2]); r.bold = True
        elif tok.startswith("`") and tok.endswith("`"):
            r = par.add_run(tok[1:-1]); r.font.name = "Consolas"; r.font.size = Pt(9)
        else:
            par.add_run(tok)


def add_table(doc, rows: list[list[str]]):
    header, body = rows[0], [r for r in rows[1:] if not set("".join(r)) <= set("-: ")]
    t = doc.add_table(rows=1 + len(body), cols=len(header))
    t.style = "Light Grid Accent 1"
    for j, h in enumerate(header):
        c = t.rows[0].cells[j]; c.text = ""; add_inline(c.paragraphs[0], h)
        for r in c.paragraphs[0].runs: r.bold = True
    for i, row in enumerate(body, start=1):
        for j in range(len(header)):
            c = t.rows[i].cells[j]; c.text = ""
            add_inline(c.paragraphs[0], row[j] if j < len(row) else "")
    for row in t.rows:
        for c in row.cells:
            for p in c.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(8.5)
            for p in c.paragraphs:
                p.paragraph_format.space_after = Pt(0)
    sp = doc.add_paragraph(); sp.paragraph_format.space_after = Pt(2)


def build(md_path: Path, out: Path, title: str):
    text = expand_includes(md_path.read_text(), md_path.parent)
    doc = Document()
    st = doc.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(10.5)
    st.paragraph_format.space_after = Pt(3); st.paragraph_format.space_before = Pt(0)
    for hs in ("Heading 1", "Heading 2", "Heading 3", "Heading 4"):
        doc.styles[hs].paragraph_format.space_before = Pt(8); doc.styles[hs].paragraph_format.space_after = Pt(3)
    for s in doc.sections:
        s.left_margin = s.right_margin = Inches(0.8); s.top_margin = s.bottom_margin = Inches(0.8)
    doc.core_properties.title = title
    lines = text.splitlines()
    i = 0; table: list[list[str]] = []; first_h1 = True
    def flush_table():
        nonlocal table
        if table:
            add_table(doc, table); table = []
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("|"):
            table.append([c.strip() for c in ln.strip().strip("|").split("|")]); i += 1; continue
        flush_table()
        if ln.startswith("```"):
            i += 1; code = []
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i]); i += 1
            i += 1
            p = doc.add_paragraph(); r = p.add_run("\n".join(code)); r.font.name = "Consolas"; r.font.size = Pt(8.5)
            p.paragraph_format.left_indent = Inches(0.3); p.paragraph_format.space_after = Pt(4)
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            level = len(m.group(1)); heading = m.group(2)
            if level == 1 and first_h1:
                p = doc.add_paragraph(); r = p.add_run(heading); r.bold = True; r.font.size = Pt(20)
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT; first_h1 = False
            else:
                doc.add_heading(heading, level=min(level, 4))
            i += 1; continue
        m = re.match(r"^!\[(.*?)\]\((.*?)\)\s*$", ln)
        if m:
            cap, img = m.group(1), md_path.parent / m.group(2)
            doc.add_picture(str(img), width=Inches(6.9))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            p = doc.add_paragraph(); r = p.add_run(cap); r.italic = True; r.font.size = Pt(9); r.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before = Pt(0); p.paragraph_format.space_after = Pt(6)
            doc.paragraphs[-2].paragraph_format.space_after = Pt(0)
            i += 1; continue
        m = re.match(r"^\s*[-*]\s+(.*)$", ln)
        if m:
            p = doc.add_paragraph(style="List Bullet"); add_inline(p, m.group(1)); i += 1; continue
        m = re.match(r"^\s*\d+\.\s+(.*)$", ln)
        if m:
            p = doc.add_paragraph(style="List Number"); add_inline(p, m.group(1)); i += 1; continue
        if ln.strip() == "":
            i += 1; continue
        # paragraph: gather consecutive non-empty, non-special lines
        buf = [ln]; i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#|\||!\[|```|\s*[-*]\s|\s*\d+\.\s)", lines[i]):
            buf.append(lines[i]); i += 1
        p = doc.add_paragraph(); add_inline(p, " ".join(b.strip() for b in buf))
    flush_table()
    doc.save(out); print(out)


if __name__ == "__main__":
    build(ROOT / "BRS.md", ROOT / "Documentation-Fabric-BRS-v2.0.docx", "Documentation Fabric — BRS v2.0")
    build(ROOT / "FRS.md", ROOT / "Documentation-Fabric-FRS-v2.0.docx", "Documentation Fabric — FRS v2.0")
    build(ROOT / "POC.md", ROOT / "Documentation-Fabric-POC-v1.1.docx", "Documentation Fabric — POC v1.1")
