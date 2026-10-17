"""How an artifact becomes linked knowledge — AS-IS against the proposed inversion.

The pitch picture (`fabric_pitch_process.py`) has ONE box called "Classify". This is that box opened up,
because the change being considered is entirely inside it and is invisible at pitch scale.

The inversion: today the classifier is handed ~100 concepts and asked which fit — taxonomy-first, a closed
set. Proposed is extraction-first — read the artifact, say what it is about in its own words, and match
afterwards. Two reasons that is not cosmetic: a closed set ANCHORS the answer (measured — `UseCase` sits on
37 of the 40 records carrying any subject, `Clinical document` on 39 of 93), and a taxonomy only fits in a
prompt while it is small, so taxonomy-first cannot survive a real one.

Grey is AS-IS, green is TO-BE. Deliberately NOT the grey of the pitch picture's status dots, which means
"built and deliberately off" — this diagram has no status axis at all, and reusing that grey would overload
a colour that already carries a decision.

    python scripts/fabric_classification_pipeline.py [out.svg]
"""
from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

W, H = 1960, 1090
ASIS = ("#f0f0f0", "#8a8a8a")        # today
TOBE = ("#e7f3ec", "#1e8449")        # proposed
HUM = ("#fdf3e3", "#b9770e")         # a person decides
NEW = ("#fff8e1", "#b9770e")         # unchanged, shown for honesty about scope

#: What DECIDES the step — the lab's own vocabulary, carried as a letter so it survives in monochrome.
MODE = {"A": "an AGENT decides — schema-validated, gated after",
        "D": "DETERMINISTIC — no model in the path",
        "H": "a PERSON decides — the only way a term enters the vocabulary"}


def esc(s):
    return escape(str(s))


class Svg:
    def __init__(self):
        self.p: list[str] = []
        self.rects: list[tuple] = []

    def pill(self, cx, cy, w, mode):
        x, y = cx - w / 2 + 6, cy - 32 - 9
        fill, ink = ("#2b2b2b", "#ffffff") if mode in ("A", "H") else ("#ffffff", "#2b2b2b")
        ring = ' stroke-width="3.2"' if mode == "H" else ' stroke-width="1.5"'
        self.p.append(f'<rect x="{x}" y="{y}" width="21" height="19" rx="9.5" fill="{fill}" '
                      f'stroke="#2b2b2b"{ring}><title>{esc(MODE[mode])}</title></rect>')
        self.p.append(f'<text x="{x + 10.5}" y="{y + 13.5}" text-anchor="middle" font-size="11.5" '
                      f'font-weight="700" fill="{ink}">{mode}</text>')

    def box(self, cx, cy, title, sub="", kind=TOBE, mode="", w=250, h=64, dashed=False):
        fill, edge = kind
        self.rects.append((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, title))
        dash = ' stroke-dasharray="7 4"' if dashed else ""
        self.p.append(f'<rect x="{cx - w/2}" y="{cy - h/2}" width="{w}" height="{h}" rx="7" fill="{fill}" '
                      f'stroke="{edge}" stroke-width="2"{dash}/>')
        self.p.append(f'<text x="{cx}" y="{cy - 4 if sub else cy + 5}" text-anchor="middle" font-size="13.5" '
                      f'font-weight="700" fill="#222">{esc(title)}</text>')
        for i, line in enumerate((sub or "").split("\n")):
            if line:
                self.p.append(f'<text x="{cx}" y="{cy + 13 + i * 13}" text-anchor="middle" font-size="10.5" '
                              f'fill="#555">{esc(line)}</text>')
        if mode:
            self.pill(cx, cy, w, mode)

    def flow(self, pts, label="", dashed=False):
        d = " ".join(f"{'M' if i == 0 else 'L'}{x},{y}" for i, (x, y) in enumerate(pts))
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        self.p.append(f'<path d="{d}" fill="none" stroke="#666" stroke-width="2" marker-end="url(#a)"{dash}/>')
        if label:
            (x1, y1), (x2, y2) = pts[-2], pts[-1]
            self.p.append(f'<text x="{(x1+x2)/2}" y="{(y1+y2)/2 - 7}" text-anchor="middle" font-size="10.5" '
                          f'fill="#666">{esc(label)}</text>')

    def line(self, pts, dashed=False):
        """A bus: a connector with NO arrowhead, so a fan-out reads as one decision with three
        outcomes rather than three unrelated arrows."""
        d = " ".join(f"{'M' if i == 0 else 'L'}{x},{y}" for i, (x, y) in enumerate(pts))
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        self.p.append(f'<path d="{d}" fill="none" stroke="#666" stroke-width="2"{dash}/>')

    def text(self, x, y, s, size=13, weight="400", fill="#333", style=""):
        st = f' font-style="{style}"' if style else ""
        self.p.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}"{st}>'
                      f'{esc(s)}</text>')

    def check(self):
        for i, (ax1, ay1, ax2, ay2, an) in enumerate(self.rects):
            if ax1 < 30 or ax2 > W - 30 or ay1 < 0 or ay2 > H:
                raise AssertionError(f"{an!r} leaves the canvas ({ax1:.0f},{ay1:.0f})-({ax2:.0f},{ay2:.0f})")
            for bx1, by1, bx2, by2, bn in self.rects[i + 1:]:
                if ax1 < bx2 and bx1 < ax2 and ay1 < by2 and by1 < ay2:
                    raise AssertionError(f"{an!r} overlaps {bn!r}")

    def render(self):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
                f'font-family="Segoe UI,Helvetica,Arial,sans-serif">\n'
                f'<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
                f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#666"/></marker></defs>\n'
                f'<rect width="{W}" height="{H}" fill="#fff"/>\n' + "\n".join(self.p) + "\n</svg>\n")


def main(out: Path) -> None:
    s = Svg()
    C = [190, 500, 810, 1120, 1430, 1740]
    s.text(60, 42, "Classifying an artifact — as-is, and the proposed inversion", 25, "700", "#222")
    s.text(60, 66, "Today the classifier is given the taxonomy and asked what fits. Proposed: read the "
                   "artifact first, say what it is about, match afterwards.", 13.5, "400", "#555", "italic")

    # ---------------------------------------------------------------- AS-IS
    s.text(60, 128, "AS-IS", 15, "700", "#8a8a8a")
    s.text(60, 146, "one model call does the reading AND the mapping", 11, "400", "#999")
    y = 196
    s.box(C[0], y, "Excerpt", "bounded text\nfrom the document only", ASIS, "D")
    s.box(C[1], y, "LLM classify", "~100 concepts IN the prompt\n→ type + subjects + confidence", ASIS, "A")
    s.box(C[2], y, "vocab_link", "EXACT label match\n→ linked / missed / conflicts", ASIS, "D")
    s.box(C[3], y, "Candidate", "the residue: what matched\nnothing", ASIS, "D")
    s.box(C[4], y, "STEWARD", "one queue, one question:\nadmit this term?", HUM, "H")
    for a, b in zip(C[:4], C[1:5]):
        s.flow([(a + 125, y), (b - 125, y)])
    s.text(C[5] - 110, y - 16, "The closed set anchors", 12, "700", "#8a8a8a")
    s.text(C[5] - 110, y + 2, "the answer: UseCase on 37", 11, "400", "#777")
    s.text(C[5] - 110, y + 16, "of 40, Clinical document on", 11, "400", "#777")
    s.text(C[5] - 110, y + 30, "39 of 93. And a taxonomy", 11, "400", "#777")
    s.text(C[5] - 110, y + 44, "only fits while it is small.", 11, "400", "#777")

    # ---------------------------------------------------------------- TO-BE
    s.text(60, 316, "TO-BE", 15, "700", "#1e8449")
    s.text(60, 334, "one model call READS; everything after it is deterministic", 11, "400", "#6aa684")
    y = 410
    s.box(C[0], y, "Render to text", "doc \u00b7 audio \u00b7 video \u00b7 diagram\nstamps the FIDELITY", TOBE, "D")
    s.box(C[1], y, "LLM extract", "\u2192 [{term, evidence span,\nsalience}]  inference allowed", TOBE, "A")
    s.box(C[2], y, "Ground", "is the span present verbatim?\nif not, discard", TOBE, "D")
    s.box(C[3], y, "Normalise", "lemmatise \u00b7 strip determiners\n(spaCy, or simpler)", TOBE, "D")
    s.box(C[4], y, "Match", "embed vs concept DEFINITIONS\nhit if \u2265 threshold", TOBE, "D")
    for a, b in zip(C[:4], C[1:5]):
        s.flow([(a + 125, y), (b - 125, y)])

    # A structured diagram is a second KIND of input, not an outcome — routed ABOVE the row so it reads
    # as arriving from the same rendering step rather than falling out of the match.
    s.box(C[5], y, "Structured diagram", "boxes are TERMS, arrows are\ncandidate RELATIONS", NEW, "D", dashed=True)
    s.flow([(C[0], y - 32), (C[0], 356), (C[5], 356), (C[5], y - 32)], "when the artifact is a diagram")

    # outcomes of the match, fanned off ONE bus below the row
    y2, bus = 578, 486
    s.box(C[2], y2, "Link doc \u2192 concept", "rung X \u00b7 strength \u221d specificity", TOBE, "D", h=58)
    s.box(C[3], y2, "Alias candidate", "term matched, but is not yet\none of that concept's labels", TOBE, "D", h=58)
    s.box(C[4], y2, "Concept candidate", "no match \u2014 prefLabel + a\ndefinition drafted from evidence", TOBE, "D", h=58)
    s.line([(C[4], y + 32), (C[4], bus)])
    s.line([(C[2], bus), (C[4], bus)])
    for cx, lab in ((C[2], "hit"), (C[3], "hit, new label"), (C[4], "miss")):
        s.flow([(cx, bus), (cx, y2 - 29)], lab)

    # stewards
    y3 = 732
    s.box(C[3], y3, "STEWARD A1 \u2014 alias", "is this another word for it?\nhigh volume \u00b7 batched \u00b7 seconds", HUM, "H", h=58)
    s.box(C[4], y3, "STEWARD A2 \u2014 concept", "is this a new concept?\nneeds a definition", HUM, "H", h=58)
    s.box(C[5], y3, "STEWARD B \u2014 topology", "where does it sit? broader /\nrelated \u2014 CONCEPTS, never labels", HUM, "H", h=58)
    s.flow([(C[3], y2 + 29), (C[3], y3 - 29)])
    s.flow([(C[4], y2 + 29), (C[4], y3 - 29)])
    s.flow([(C[4] + 125, y3), (C[5] - 125, y3)], "once admitted")
    s.flow([(C[5], y + 32), (C[5], y3 - 29)], "the only feeder B has")
    # The loop is stated rather than drawn: an arrow from A1 back to Match crosses the whole fan and buys
    # nothing a sentence cannot say.
    s.text(C[3] - 125, y3 + 48, "\u21b3 an admitted alias matches deterministically next time \u2014 the "
                                "vocabulary improves itself, and the embedder is needed less often.",
           11, "400", "#b9770e")

    # ---------------------------------------------------------------- legend
    s.text(60, 876, "The four signals, and where each is produced", 13, "700", "#333")
    for i, (sig, where) in enumerate((("salience", "step 2 — is this what the artifact is about?"),
                                      ("grounding", "step 3 — is there textual evidence for it?"),
                                      ("match", "step 5 — how well does it map to an admitted concept?"),
                                      ("specificity", "link — is the concept rare enough to carry one?"))):
        s.text(60, 898 + i * 19, f"{sig:<13}", 11.5, "700", "#1e8449")
        s.text(160, 898 + i * 19, where, 11.5, "400", "#555")
    s.text(60, 1000, "× fidelity of the rendering — a concept grounded in one provider's transcript is weaker "
                    "evidence than the same concept in the document itself.", 11.5, "400", "#777")
    s.text(60, 1022, "Grey is today, green is proposed. Amber is a person. This diagram carries NO status axis: "
                    "its grey is not the pitch picture's “built and deliberately off”.", 11.5, "400", "#999")
    s.text(60, 1044, "Unchanged, and shown dashed for honesty about scope: document TYPE stays a closed-set "
                    "choice, and CITATIONS stay their own path (doc →references→ doc).", 11.5, "400", "#999")

    s.check()
    out.write_text(s.render())
    print(out.resolve())


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/fabric/classification-pipeline.svg"))
