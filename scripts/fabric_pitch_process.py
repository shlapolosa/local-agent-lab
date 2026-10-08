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

W, H = 1680, 940

SYS = ("#f3f0fa", "#5b4b8a")      # the fabric
SOR = ("#ededed", "#777777")      # systems of record — consumed, never owned
HUM = ("#fdf3e3", "#b9770e")      # a human touchpoint
OUT = ("#e7f3ec", "#1e8449")      # surfaces people and agents meet

LANES = [
    ("AUTHOR", "writes where they already work", 60, 170, "#fbf7f0"),
    ("SYSTEMS OF RECORD", "SharePoint · ADO · APIM · EA — content stays here", 170, 300, "#f2f2f2"),
    ("THE FABRIC", "pointers, facets, relations — and how each fact is known", 300, 610, "#f7f5fc"),
    ("OWNER · STEWARD", "two questions, two different people", 610, 770, "#fbf7f0"),
    ("RESEARCHERS · AGENTS", "find, browse, anchor", 770, 890, "#eef7f2"),
]


def esc(s):
    return escape(str(s))


class Svg:
    def __init__(self):
        self.p: list[str] = []

    def lane(self, x, y, w, h, fill, name, sub):
        self.p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="#c9c9c9"/>')
        cy = y + h / 2
        self.p.append(f'<text x="{x + 20}" y="{cy - 6}" transform="rotate(-90 {x + 20} {cy})" '
                      f'text-anchor="middle" font-size="15" font-weight="700" fill="#555">{esc(name)}</text>')
        self.p.append(f'<text x="{x + 36}" y="{cy + 4}" transform="rotate(-90 {x + 36} {cy})" '
                      f'text-anchor="middle" font-size="10.5" fill="#888">{esc(sub)}</text>')

    def box(self, cx, cy, w, h, title, sub="", kind=SYS, dashed=False, human=False):
        fill, edge = kind
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

    def gate(self, cx, cy, label, note=""):
        r = 24
        self.p.append(f'<polygon points="{cx},{cy-r} {cx+r},{cy} {cx},{cy+r} {cx-r},{cy}" fill="#fff" '
                      f'stroke="#444" stroke-width="2"/>')
        self.p.append(f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" font-size="15" fill="#555">?</text>')
        self.p.append(f'<text x="{cx}" y="{cy - r - 8}" text-anchor="middle" font-size="12" '
                      f'font-weight="700" fill="#333">{esc(label)}</text>')
        if note:
            self.p.append(f'<text x="{cx}" y="{cy + r + 17}" text-anchor="middle" font-size="10" '
                          f'fill="#777">{esc(note)}</text>')

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

    def render(self) -> str:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
                f'font-family="Segoe UI,Helvetica,Arial,sans-serif">\n'
                f'<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
                f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#666"/></marker></defs>\n'
                f'<rect width="{W}" height="{H}" fill="#fff"/>\n' + "\n".join(self.p) + "\n</svg>\n")


def main(out: Path) -> None:
    s = Svg()
    s.p.append(f'<text x="60" y="36" font-size="22" font-weight="700" fill="#222">'
               f'The Documentation Fabric — who does what, when and where</text>')
    s.p.append(f'<text x="60" y="54" font-size="12.5" font-style="italic" fill="#555">'
               f'Microsoft retrieves; the fabric vouches — the two meet in the assistant, at the moment a '
               f'question is answered, never by pre-merging one into the other’s store.</text>')

    for name, sub, top, bottom, fill in LANES:
        s.lane(50, top, W - 100, bottom - top, fill, name, sub)

    C = [230 + 168 * i for i in range(9)]

    # author -> the system of record it lands in
    s.event(C[0], 115, "writes a document")
    s.box(C[1], 235, 250, 56, "Stored where it lives", "SharePoint · ADO · APIM — never copied", kind=SOR)
    s.flow([(C[0] + 19, 115), (C[1], 115), (C[1], 207)])

    # the fabric: catalogue -> classify -> matched?
    s.box(C[1], 360, 250, 56, "Catalogue the record", "pointer + facets  (the ABox)")
    s.flow([(C[1], 263), (C[1], 332)], "change event")

    s.box(C[2], 360, 240, 56, "Classify", "reads the ~100-concept scheme (the TBox)")
    s.flow([(C[1] + 125, 360), (C[2] - 120, 360)])

    s.gate(C[3] - 40, 360, "matched?")
    s.flow([(C[2] + 120, 360), (C[3] - 64, 360)])

    s.box(C[4], 340, 250, 52, "Subject link at rung X", "an agent extracted this")
    s.flow([(C[3] - 16, 360), (C[4] - 125, 345)], "yes")

    s.box(C[4], 470, 250, 52, "Candidate register", "counted, not asked")
    s.flow([(C[3] - 40, 384), (C[3] - 40, 470), (C[4] - 125, 470)], "no")

    s.gate(C[5] + 10, 470, "threshold?", "a term seen once is not a concept")
    s.flow([(C[4] + 125, 470), (C[5] - 14, 470)], dashed=True)

    # steward: the vocabulary question, batched
    s.box(C[5] + 10, 680, 270, 60, "STEWARD admits the term",
          "batched · once per term, not per artifact", kind=HUM, human=True, dashed=True)
    s.flow([(C[5] + 10, 494), (C[5] + 10, 650)], "reached", dashed=True)
    s.box(C[4], 560, 250, 50, "Re-match what waited", "FR-1.1.5", dashed=True)
    s.flow([(C[5] - 125, 680), (C[4], 680), (C[4], 585)], "on admission", dashed=True)
    s.flow([(C[4] - 125, 560), (C[2], 560), (C[2], 388)], dashed=True)

    # owner: the artifact question, one card
    s.box(C[5] + 10, 340, 250, 52, "Ask the OWNER", "one card — type and context")
    s.flow([(C[4] + 125, 345), (C[5] - 115, 345)])

    s.box(C[6] + 30, 680, 250, 60, "OWNER confirms",
          "one tap · the only way up the ladder", kind=HUM, human=True)
    s.flow([(C[5] + 135, 345), (C[6] + 30, 345), (C[6] + 30, 650)])

    s.gate(C[7] + 50, 680, "approved?")
    s.flow([(C[6] + 155, 680), (C[7] + 26, 680)])

    s.event(C[7] + 50, 820, "withdrawn", end=True)
    s.flow([(C[7] + 50, 704), (C[7] + 50, 801)], "no")

    s.box(C[8] - 10, 360, 220, 52, "Published", "state + baseline")
    s.flow([(C[7] + 74, 680), (C[8] - 10, 680), (C[8] - 10, 386)], "yes")

    s.box(C[8] - 10, 480, 220, 52, "Project a page", "metadata only, never the content")
    s.flow([(C[8] - 10, 386), (C[8] - 10, 454)])

    # the surfaces
    s.box(C[6] + 30, 830, 260, 52, "Copilot answers", "retrieval + the fabric’s facts, merged", kind=OUT)
    s.box(C[8] - 10, 830, 220, 52, "Pages · MCP", "browse · agents anchor", kind=OUT)
    s.flow([(C[8] - 10, 506), (C[8] - 10, 804)])
    s.flow([(C[8] - 120, 830), (C[6] + 160, 830)])

    s.p.append(f'<text x="{W - 60}" y="{H - 22}" text-anchor="end" font-size="11" fill="#777">'
               f'&#9673; human touchpoint &#160;&#160; &#9671; gateway &#160;&#160; dashed = not built yet</text>')
    s.p.append(f'<text x="60" y="{H - 22}" font-size="11" fill="#777">'
               f'Rungs: O observed &#183; S suggested &#183; X extracted &#183; C constructed &#183; '
               f'H human-confirmed &#183; D derived &#160;&#8212;&#160; only C&#183;X&#183;H answer '
               f'&#8220;what does this change break?&#8221;</text>')

    out.write_text(s.render())
    print(out.resolve())


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/fabric/pitch-process-v1.0.svg"))
