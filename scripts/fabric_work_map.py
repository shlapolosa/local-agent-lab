"""The pitch process again — but coloured by WHERE THE WORK IS, not by what is running.

The RAG view (`fabric_pitch_process.py`) answers "what is true in the cloud today". This one answers the
other question a person asks in front of a plan: *which piece of work lands on which step, and which piece
am I in right now*. So every status colour is gone — a step carries a TAG instead, and the tags are the
plan's own names, so the picture and the plan cannot drift into describing different work.

Deliberately monochrome. A colour on a plan reads as status however it is labelled, and the whole point
here is that DONE and DOING and NOT YET are stages of one piece of work rather than a health report.

    .venv/bin/python scripts/fabric_work_map.py
"""
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fabric_pitch_process import HUM, OUT, SOR, SYS, Svg, W, H, COL, BOXW   # noqa: E402

#: tag -> (what the work is, what stage it is at). The stage is a WORD, never a colour: three greys and a
#: dashed outline carry it, so printing this in black and white loses nothing.
WORK = {
    "done":  ("already running", "done"),
    "T2.1":  ("one row per term: dedup, count, the artifacts that proposed it", "doing"),
    "T2.2":  ("a frequency threshold before a miss becomes a question", "next"),
    "T2.3":  ("batch admission — one card, N candidates", "next"),
    "T2.4":  ("re-match exactly the artifacts that asked (FR-1.1.5)", "next"),
    "T2.5":  ("decide ON the card — a flow that waits, not a deep link out", "next"),
    "T3.1":  ("custody lookup by URL — FR-4.1.4", "later"),
    "T3.2":  ("SharePoint knowledge source + agent instructions", "later"),
    "T3.3":  ("linked projection pages (corpus page: done today)", "later"),
    "T5.1":  ("RetrievalSource as a PORT, adapters per provider", "later"),
}
STAGE = {"done": ("#ffffff", "#9aa0a6", "#5f6368"),      # (fill, stroke, text) — three greys, no hue
         "doing": ("#2b2b2b", "#2b2b2b", "#ffffff"),     # the one you are in: solid, unmissable
         "next": ("#ffffff", "#2b2b2b", "#2b2b2b"),
         "later": ("#ffffff", "#bdbdbd", "#8a8a8a")}
NEUTRAL = ("#fafafa", "#9aa0a6")                          # every lane and box, so nothing reads as status


def esc(s):
    return escape(str(s))


def tag(s, cx, cy, w, h, name):
    """The work badge, top-right of a step. A pill, not a dot: the NAME is the information."""
    what, stage = WORK[name]
    fill, stroke, ink = STAGE[stage]
    tw = 15 + 7.6 * len(name)
    x, y = cx + w / 2 - tw - 6, cy - h / 2 - 9
    dash = ' stroke-dasharray="4 3"' if stage == "later" else ""
    s.p.append(f'<rect x="{x}" y="{y}" width="{tw}" height="19" rx="9.5" fill="{fill}" stroke="{stroke}" '
               f'stroke-width="1.5"{dash}><title>{esc(name)} — {esc(what)} ({esc(stage)})</title></rect>')
    s.p.append(f'<text x="{x + tw/2}" y="{y + 13.5}" text-anchor="middle" font-size="11.5" '
               f'font-weight="700" fill="{ink}">{esc(name)}</text>')


def main(out: Path) -> None:
    s = Svg()
    s.p.append('<text x="60" y="40" font-size="26" font-weight="700" fill="#222">'
               'The Documentation Fabric — where the work is</text>')
    s.p.append('<text x="60" y="62" font-size="14" font-style="italic" fill="#555">'
               'The same process, tagged with the plan’s own task names. No status colours: a step is '
               'done, being done, next, or later — stages of one piece of work, not a health report.</text>')

    for name, sub, top, bottom, _fill in [(n, u, t, b, f) for n, u, t, b, f in __import__(
            "fabric_pitch_process").LANES]:
        s.lane(50, top, W - 100, bottom - top, NEUTRAL[0], name, sub)

    C = [260 + COL * i for i in range(9)]
    TOP, MID, LOW = 375, 505, 600
    PEOPLE, SURFACE = 705, 862

    def step(cx, cy, title, sub, work, **kw):
        s.box(cx, cy, BOXW, kw.pop("h", 58), title, sub, **kw)
        tag(s, cx, cy, BOXW, kw.get("h", 58), work)

    s.event(C[0], 125, "writes a document")
    step(C[0], 240, "Stored where it lives", "SharePoint · ADO · APIM — never copied", "done", kind=SOR)
    s.flow([(C[0], 144), (C[0], 211)])

    step(C[1], TOP, "Catalogue the record", "pointer + facets  (the ABox)", "done")
    s.flow([(C[0], 269), (C[0], TOP), (C[1] - BOXW // 2, TOP)], "change event")

    step(C[2], TOP, "Classify", "content + the ~123-concept scheme", "done")
    s.flow([(C[1] + BOXW // 2, TOP), (C[2] - BOXW // 2, TOP)])

    s.gate(C[3], TOP, "matched?")
    s.flow([(C[2] + BOXW // 2, TOP), (C[3] - 24, TOP)])

    step(C[4], TOP, "Subject link at rung X", "replaced on a re-read", "done")
    s.flow([(C[3] + 24, TOP), (C[4] - BOXW // 2, TOP)], "yes")

    step(C[4], MID, "Candidate register", "one row per TERM + who asked", "T2.1")
    s.flow([(C[3], TOP + 24), (C[3], MID), (C[4] - BOXW // 2, MID)], "no")

    s.gate(C[5], MID, "threshold?", "a term seen once is not a concept")
    tag(s, C[5], MID, 56, 56, "T2.2")
    s.flow([(C[4] + BOXW // 2, MID), (C[5] - 24, MID)], dashed=True)

    step(C[5], PEOPLE, "STEWARD admits terms", "a BATCH, answered ON the card", "T2.3",
         kind=HUM, human=True, h=62)
    tag(s, C[5], PEOPLE, BOXW, 62, "T2.5")
    s.flow([(C[5], MID + 24), (C[5], PEOPLE - 31)], "reached", dashed=True)

    step(C[4], LOW, "Re-match what waited", "exactly who asked — FR-1.1.5", "T2.4", dashed=True, h=54)
    s.flow([(C[5] - BOXW // 2, PEOPLE), (C[4], PEOPLE), (C[4], LOW + 27)], "on admission", dashed=True)
    s.flow([(C[4] - BOXW // 2, LOW), (C[2], LOW), (C[2], TOP + 29)], dashed=True)

    step(C[5], TOP, "Ask the OWNER", "type + context, and a differing reading", "done")
    s.flow([(C[4] + BOXW // 2, TOP), (C[5] - BOXW // 2, TOP)])

    step(C[6], PEOPLE, "OWNER confirms", "one tap · the only way up", "done", kind=HUM, human=True, h=62)
    s.flow([(C[5] + BOXW // 2, TOP), (C[6], TOP), (C[6], PEOPLE - 31)])

    s.gate(C[7], PEOPLE, "approved?")
    s.flow([(C[6] + BOXW // 2, PEOPLE), (C[7] - 24, PEOPLE)])

    s.event(C[7], SURFACE, "withdrawn", end=True)
    s.flow([(C[7], PEOPLE + 24), (C[7], SURFACE - 19)], "no")

    step(C[8], TOP, "Published", "state + baseline", "done")
    s.flow([(C[7] + 24, PEOPLE), (C[8], PEOPLE), (C[8], TOP + 29)], "yes")

    step(C[8], MID, "Project a page", "+ its link on the record", "done")
    s.flow([(C[8], TOP + 29), (C[8], MID - 29)])

    step(C[8], SURFACE, "Pages · corpus map · MCP", "pages do not link to each other yet", "T3.3", kind=OUT)
    s.flow([(C[8], MID + 29), (C[8], SURFACE - 29)])

    step(C[6], SURFACE, "Copilot answers", "custody by URL + a retrieval source", "T3.2", kind=OUT)
    tag(s, C[6], SURFACE, BOXW, 58, "T3.1")
    s.flow([(C[8] - BOXW // 2, SURFACE), (C[6] + BOXW // 2, SURFACE)])

    s.p.append(f'<text x="{W - 60}" y="{H - 24}" text-anchor="end" font-size="13" fill="#777">'
               f'&#9673; human touchpoint &#160;&#160; &#9671; gateway</text>')
    s.p.append(f'<text x="{W - 560}" y="{H - 132}" font-size="12.5" font-weight="700" fill="#333">'
               f'The work, by stage — 10 Oct 2026</text>')
    for i, (stage, words) in enumerate((("done", "shipped and exercised on real records"),
                                        ("doing", "in hand right now"),
                                        ("next", "the rest of Phase 2"),
                                        ("later", "Phase 3 and Phase 5"))):
        y = H - 112 + i * 22
        fill, stroke, ink = STAGE[stage]
        dash = ' stroke-dasharray="4 3"' if stage == "later" else ""
        s.p.append(f'<rect x="{W - 560}" y="{y - 13}" width="52" height="19" rx="9.5" fill="{fill}" '
                   f'stroke="{stroke}" stroke-width="1.5"{dash}/>')
        s.p.append(f'<text x="{W - 534}" y="{y}" text-anchor="middle" font-size="11.5" font-weight="700" '
                   f'fill="{ink}">{esc(stage)}</text>')
        s.p.append(f'<text x="{W - 498}" y="{y}" font-size="12.5" fill="#555">{esc(words)}</text>')
    s.p.append(f'<text x="60" y="{H - 24}" font-size="13" fill="#777">'
               f'Tags are the plan’s task names — hover a tag for what it is.</text>')
    s.check()
    out.write_text(s.render(), encoding="utf-8")
    print(f"wrote {out}  ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    main(root / "docs" / "fabric" / "work-map-v1.0.svg")
