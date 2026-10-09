"""The Documentation Fabric in one picture — who does what, when, how and where (BPMN-style swimlanes).

The elevator pitch drawn: a person authors where they already work, the fabric catalogues and classifies
what they produced, two different questions go to two different people, and an owner's approval is what
moves knowledge up the ladder and out to the surfaces people and agents use.

Lanes are the four cohorts plus the two things that are not people: the systems of record (where content
STAYS) and the fabric (which holds pointers, facets, relations and how each fact is known).

Emits SVG with no dependencies — matplotlib is not a declared dependency of this repo, and a diagram that
needs a 50 MB install to regenerate is one nobody regenerates. Open it in a browser or drop it in a doc.

    python scripts/fabric_pitch_process.py [out.svg]
"""
from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

W, H = 2420, 1000
COL, BOXW = 250, 210      # pitch > width + gap, or boxes overlap and their text clips

SYS = ("#f3f0fa", "#5b4b8a")      # the fabric
SOR = ("#ededed", "#777777")      # systems of record — consumed, never owned
HUM = ("#fdf3e3", "#b9770e")      # a human touchpoint
OUT = ("#e7f3ec", "#1e8449")      # surfaces people and agents meet

#: RAG — what is TRUE in the cloud today, not what is designed. GREEN is running and has been exercised
#: on real records; AMBER is built but unproven or only half of it is there; RED is not implemented. The
#: status is on the picture because a diagram of an intention is the easiest kind to believe.
RAG = {"green": "#1e8449", "amber": "#d68910", "red": "#c0392b"}
RAG_WHY = {"green": "running, exercised on real records", "amber": "built, unproven or partial",
           "red": "not implemented"}

LANES = [
    ("AUTHOR", "writes where they already work", 70, 180, "#fbf7f0"),
    ("SYSTEMS OF RECORD", "SharePoint · ADO · APIM · EA — content stays here", 180, 300, "#f2f2f2"),
    ("THE FABRIC", "pointers, facets, relations — and how each fact is known", 300, 640, "#f7f5fc"),
    ("OWNER · STEWARD", "two questions, two different people", 640, 790, "#fbf7f0"),
    ("RESEARCHERS · AGENTS", "find, browse, anchor", 790, 920, "#eef7f2"),
]


def esc(s):
    return escape(str(s))


class Svg:
    def __init__(self):
        self.p: list[str] = []
        self.rects: list[tuple[float, float, float, float, str]] = []

    def lane(self, x, y, w, h, fill, name, sub):
        self.p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="#c9c9c9"/>')
        cy = y + h / 2
        self.p.append(f'<text x="{x + 20}" y="{cy - 6}" transform="rotate(-90 {x + 20} {cy})" '
                      f'text-anchor="middle" font-size="15" font-weight="700" fill="#555">{esc(name)}</text>')
        self.p.append(f'<text x="{x + 36}" y="{cy + 4}" transform="rotate(-90 {x + 36} {cy})" '
                      f'text-anchor="middle" font-size="10.5" fill="#888">{esc(sub)}</text>')

    def box(self, cx, cy, w, h, title, sub="", kind=SYS, dashed=False, human=False, rag=""):
        fill, edge = kind
        self.rects.append((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, title))
        dash = ' stroke-dasharray="7 4"' if dashed else ""
        self.p.append(f'<rect x="{cx - w/2}" y="{cy - h/2}" width="{w}" height="{h}" rx="7" fill="{fill}" '
                      f'stroke="{edge}" stroke-width="2"{dash}/>')
        ty = cy - 4 if sub else cy + 5
        self.p.append(f'<text x="{cx}" y="{ty}" text-anchor="middle" font-size="14" font-weight="700" '
                      f'fill="#222">{esc(title)}</text>')
        if sub:
            self.p.append(f'<text x="{cx}" y="{cy + 15}" text-anchor="middle" font-size="11" '
                          f'fill="#555">{esc(sub)}</text>')
        if human:
            self.p.append(f'<text x="{cx - w/2 + 13}" y="{cy - h/2 + 18}" text-anchor="middle" font-size="15" '
                          f'fill="#b9770e">&#9673;</text>')
        if rag:
            self.p.append(f'<circle cx="{cx + w/2 - 14}" cy="{cy - h/2 + 14}" r="7" fill="{RAG[rag]}" '
                          f'stroke="#fff" stroke-width="2"><title>{esc(RAG_WHY[rag])}</title></circle>')

    def gate(self, cx, cy, label, note="", rag=""):
        r = 24
        self.p.append(f'<polygon points="{cx},{cy-r} {cx+r},{cy} {cx},{cy+r} {cx-r},{cy}" fill="#fff" '
                      f'stroke="#444" stroke-width="2"/>')
        self.p.append(f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" font-size="15" fill="#555">?</text>')
        self.p.append(f'<text x="{cx}" y="{cy - r - 8}" text-anchor="middle" font-size="12" '
                      f'font-weight="700" fill="#333">{esc(label)}</text>')
        if note:
            self.p.append(f'<text x="{cx}" y="{cy + r + 17}" text-anchor="middle" font-size="10" '
                          f'fill="#777">{esc(note)}</text>')
        if rag:
            self.p.append(f'<circle cx="{cx + r - 4}" cy="{cy - r + 4}" r="7" fill="{RAG[rag]}" '
                          f'stroke="#fff" stroke-width="2"><title>{esc(RAG_WHY[rag])}</title></circle>')

    def event(self, cx, cy, label, end=False):
        self.p.append(f'<circle cx="{cx}" cy="{cy}" r="19" fill="#fff" stroke="#333" '
                      f'stroke-width="{4 if end else 2}"/>')
        self.p.append(f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" font-size="13" fill="#333">'
                      f'{"&#9632;" if end else "&#9654;"}</text>')
        self.p.append(f'<text x="{cx}" y="{cy + 36}" text-anchor="middle" font-size="11" '
                      f'fill="#333">{esc(label)}</text>')

    def flow(self, pts, label="", dashed=False):
        d = " ".join(f"{'M' if i == 0 else 'L'}{x},{y}" for i, (x, y) in enumerate(pts))
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        self.p.append(f'<path d="{d}" fill="none" stroke="#666" stroke-width="2" '
                      f'marker-end="url(#a)"{dash}/>')
        if label:
            (x1, y1), (x2, y2) = pts[-2], pts[-1]
            self.p.append(f'<text x="{(x1+x2)/2}" y="{(y1+y2)/2 - 7}" text-anchor="middle" font-size="11" '
                          f'fill="#666">{esc(label)}</text>')

    def check(self) -> None:
        """Refuse to emit a diagram whose boxes overlap or leave the canvas.

        The first render did both — the column pitch was narrower than the boxes, so three pairs sat on top
        of each other and their titles clipped mid-word ("Catalogue the rec\u2026"). Nothing failed: an SVG is
        valid whatever it looks like, and the defect was only visible to a person who opened it. A generator
        that cannot fail is the same instrument problem as a check that cannot go red, so it checks itself.
        """
        for i, (ax1, ay1, ax2, ay2, an) in enumerate(self.rects):
            if ax1 < 40 or ax2 > W - 40 or ay1 < 0 or ay2 > H:
                raise AssertionError(f"{an!r} leaves the canvas: ({ax1:.0f},{ay1:.0f})-({ax2:.0f},{ay2:.0f})")
            for bx1, by1, bx2, by2, bn in self.rects[i + 1:]:
                if ax1 < bx2 and bx1 < ax2 and ay1 < by2 and by1 < ay2:
                    raise AssertionError(f"{an!r} overlaps {bn!r}")

    def render(self) -> str:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
                f'font-family="Segoe UI,Helvetica,Arial,sans-serif">\n'
                f'<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
                f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#666"/></marker></defs>\n'
                f'<rect width="{W}" height="{H}" fill="#fff"/>\n' + "\n".join(self.p) + "\n</svg>\n")


def main(out: Path) -> None:
    s = Svg()
    s.p.append('<text x="60" y="40" font-size="26" font-weight="700" fill="#222">'
               'The Documentation Fabric \u2014 who does what, when and where</text>')
    s.p.append('<text x="60" y="62" font-size="14" font-style="italic" fill="#555">'
               'Microsoft retrieves; the fabric vouches \u2014 the two meet in the assistant, at the moment a '
               'question is answered, never by pre-merging one into the other\u2019s store.</text>')

    for name, sub, top, bottom, fill in LANES:
        s.lane(50, top, W - 100, bottom - top, fill, name, sub)

    C = [260 + COL * i for i in range(9)]
    TOP, MID, LOW = 375, 505, 600          # the fabric's three rows
    PEOPLE, SURFACE = 705, 862

    s.event(C[0], 125, "writes a document")
    s.box(C[0], 240, BOXW, 58, "Stored where it lives", "SharePoint \u00b7 ADO \u00b7 APIM \u2014 never copied", kind=SOR, rag="green")
    s.flow([(C[0], 144), (C[0], 211)])

    s.box(C[1], TOP, BOXW, 58, "Catalogue the record", "pointer + facets  (the ABox)", rag="green")
    s.flow([(C[0], 269), (C[0], TOP), (C[1] - BOXW // 2, TOP)], "change event")

    s.box(C[2], TOP, BOXW, 58, "Classify", "reads content + the ~100-concept scheme", rag="green")
    s.flow([(C[1] + BOXW // 2, TOP), (C[2] - BOXW // 2, TOP)])

    s.gate(C[3], TOP, "matched?", rag="green")
    s.flow([(C[2] + BOXW // 2, TOP), (C[3] - 24, TOP)])

    s.box(C[4], TOP, BOXW, 58, "Subject link at rung X", "replaced on a re-read", rag="green")
    s.flow([(C[3] + 24, TOP), (C[4] - BOXW // 2, TOP)], "yes")

    s.box(C[4], MID, BOXW, 58, "Candidate register", "parked; no count yet", rag="amber")
    s.flow([(C[3], TOP + 24), (C[3], MID), (C[4] - BOXW // 2, MID)], "no")

    s.gate(C[5], MID, "threshold?", "a term seen once is not a concept", rag="red")
    s.flow([(C[4] + BOXW // 2, MID), (C[5] - 24, MID)], dashed=True)

    s.box(C[5], PEOPLE, BOXW, 62, "STEWARD admits the term",
          "one at a time, never exercised", kind=HUM, human=True, rag="amber")
    s.flow([(C[5], MID + 24), (C[5], PEOPLE - 31)], "reached", dashed=True)

    s.box(C[4], LOW, BOXW, 54, "Re-match what waited", "FR-1.1.5", dashed=True, rag="red")
    s.flow([(C[5] - BOXW // 2, PEOPLE), (C[4], PEOPLE), (C[4], LOW + 27)], "on admission", dashed=True)
    s.flow([(C[4] - BOXW // 2, LOW), (C[2], LOW), (C[2], TOP + 29)], dashed=True)

    s.box(C[5], TOP, BOXW, 58, "Ask the OWNER", "one card \u2014 type and context", rag="green")
    s.flow([(C[4] + BOXW // 2, TOP), (C[5] - BOXW // 2, TOP)])

    s.box(C[6], PEOPLE, BOXW, 62, "OWNER confirms", "one tap \u00b7 the only way up", kind=HUM, human=True, rag="green")
    s.flow([(C[5] + BOXW // 2, TOP), (C[6], TOP), (C[6], PEOPLE - 31)])

    s.gate(C[7], PEOPLE, "approved?", rag="green")
    s.flow([(C[6] + BOXW // 2, PEOPLE), (C[7] - 24, PEOPLE)])

    s.event(C[7], SURFACE, "withdrawn", end=True)
    s.flow([(C[7], PEOPLE + 24), (C[7], SURFACE - 19)], "no")

    s.box(C[8], TOP, BOXW, 58, "Published", "state + baseline", rag="green")
    s.flow([(C[7] + 24, PEOPLE), (C[8], PEOPLE), (C[8], TOP + 29)], "yes")

    s.box(C[8], MID, BOXW, 58, "Project a page", "metadata only, never content", rag="green")
    s.flow([(C[8], TOP + 29), (C[8], MID - 29)])

    s.box(C[8], SURFACE, BOXW, 58, "Pages \u00b7 MCP", "no links between pages yet", kind=OUT, rag="amber")
    s.flow([(C[8], MID + 29), (C[8], SURFACE - 29)])

    s.box(C[6], SURFACE, BOXW, 58, "Copilot answers", "no retrieval source wired", kind=OUT, rag="amber")
    s.flow([(C[8] - BOXW // 2, SURFACE), (C[6] + BOXW // 2, SURFACE)])

    s.p.append(f'<text x="{W - 60}" y="{H - 24}" text-anchor="end" font-size="13" fill="#777">'
               f'&#9673; human touchpoint &#160;&#160; &#9671; gateway</text>')
    for i, (k, label) in enumerate((("green", "running, exercised on real records"),
                                    ("amber", "built, unproven or partial"),
                                    ("red", "not implemented"))):
        y = H - 92 + i * 22
        s.p.append(f'<circle cx="{W - 430}" cy="{y - 4}" r="7" fill="{RAG[k]}" stroke="#fff" stroke-width="2"/>')
        s.p.append(f'<text x="{W - 412}" y="{y}" font-size="12.5" fill="#555">{esc(label)}</text>')
    s.p.append(f'<text x="{W - 430}" y="{H - 112}" font-size="12.5" font-weight="700" fill="#333">'
               f'Status, 9 Oct 2026 \u2014 what is true in the cloud</text>')
    s.p.append(f'<text x="60" y="{H - 24}" font-size="13" fill="#777">'
               f'Rungs: O observed &#183; S suggested &#183; X extracted &#183; C constructed &#183; '
               f'H human-confirmed &#183; D derived &#8212; only C&#183;X&#183;H answer '
               f'&#8220;what does this change break?&#8221;</text>')

    s.check()
    out.write_text(s.render())
    print(out.resolve())


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/fabric/pitch-process-v1.0.svg"))
