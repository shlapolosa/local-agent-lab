"""A `GraphRenderer` adapter: one self-contained HTML page with an inline SVG.

Why this shape, and what it deliberately is not. The interactive force-directed graph the CAFÉ skill produces is
better to explore and impossible to deploy here: it needs a vendored copy of D3 in a public repository and, for
its PNG, a headless browser in the substrate image. What a person actually needs from Teams is a link that opens
and shows the truth — so the page carries no script, no font and no network call, opens from a download, and
prints.

The layout is CONCENTRIC and deterministic rather than force-directed: the record in the middle, what it is about
around it, and what those connect it to outside that. A force layout would move every node whenever anything
changed, which makes two views of the same knowledge impossible to compare; concentric rings put the same concept
in the same place twice.

Colour says HOW THE FABRIC KNOWS, which is the question the rung ladder exists to answer, so a reader can see at a
glance that a link was confirmed by a person rather than suggested by a model.
"""
from __future__ import annotations

import html
import math
from dataclasses import dataclass

from lab.core.viz import FOCUS, PROPOSED, VOCABULARY, Node, Rendered, TopologyView, colour

__all__ = ["SvgHtmlRenderer", "build"]

W, H = 1180, 820


@dataclass(frozen=True)
class _Placed:
    node: Node
    x: float
    y: float


def _colour(status: str) -> tuple[str, str, str]:
    return colour(status)              # the shared table in `lab.core.viz` — see PALETTE there


def _ring(view: TopologyView) -> dict[str, int]:
    """Which ring each node sits on: 0 the record, 1 what it is directly about or related to, 2 everything the
    vocabulary brings in behind those."""
    rings = {n.id: 2 for n in view.nodes}
    rings[view.focus] = 0
    for e in view.edges:
        if e.source == view.focus:
            rings[e.target] = 1
        elif e.target == view.focus:
            rings[e.source] = 1
    return rings


def _place(view: TopologyView) -> list[_Placed]:
    """Concentric and deterministic: ring members are laid out in the order the view lists them, so the same
    knowledge always draws the same way and two pictures can be compared."""
    rings = _ring(view)
    by_ring: dict[int, list[Node]] = {}
    for n in view.nodes:
        by_ring.setdefault(rings[n.id], []).append(n)
    cx, cy = W / 2, H / 2 + 10
    out: list[_Placed] = []
    for ring, members in sorted(by_ring.items()):
        if ring == 0:
            out += [_Placed(n, cx, cy) for n in members]
            continue
        radius = 170 if ring == 1 else 330
        step = 2 * math.pi / max(len(members), 1)
        start = -math.pi / 2 + (step / 2 if ring == 2 else 0)
        for i, n in enumerate(members):
            out.append(_Placed(n, cx + radius * math.cos(start + i * step),
                               cy + radius * 0.72 * math.sin(start + i * step)))
    return out


def _wrap(text: str, width: int = 18, lines: int = 2) -> list[str]:
    """A label into at most `lines` rows, ellipsised when a word had to be left out.

    The ellipsis is decided on WORDS CONSUMED, never on joined length: a label with a double space is shorter
    once normalised, so a length comparison would mark it truncated when nothing was dropped — an ellipsis that
    says a name is longer than it is."""
    words, rows, row, used = text.split(), [], "", 0
    for w in words:
        if len(row) + len(w) + 1 > width and row:
            rows.append(row); row = w
        else:
            row = f"{row} {w}".strip()
        if len(rows) == lines:
            break
        used += 1
    if row and len(rows) < lines:
        rows.append(row)
    if not rows:
        return [text[:width]]
    if used < len(words):
        rows[-1] = rows[-1][: width - 1] + "…"
    return rows


class SvgHtmlRenderer:
    """One page, no script, no network. Satisfies `lab.core.viz.GraphRenderer`."""

    name = "svg"
    media_type = "text/html; charset=utf-8"
    suffix = ".html"

    def render(self, view: TopologyView) -> Rendered:
        placed = _place(view)
        at = {p.node.id: p for p in placed}
        parts = [
            f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" '
            f'aria-label="{html.escape(view.title)} and what it is connected to">',
            '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#90a4ae"/></marker></defs>',
        ]
        for e in view.edges:
            s, t = at.get(e.source), at.get(e.target)
            if not s or not t:
                continue
            stroke = _colour(e.status)[1]
            dash = ' stroke-dasharray="5 4"' if e.status in (PROPOSED, VOCABULARY) else ""
            parts.append(f'<line x1="{s.x:.0f}" y1="{s.y:.0f}" x2="{t.x:.0f}" y2="{t.y:.0f}" stroke="{stroke}" '
                         f'stroke-width="1.6" opacity="0.75" marker-end="url(#a)"{dash}/>')
            mx, my = (s.x + t.x) / 2, (s.y + t.y) / 2
            parts.append(f'<text x="{mx:.0f}" y="{my - 4:.0f}" text-anchor="middle" font-size="11" '
                         f'fill="#455a64" paint-order="stroke" stroke="#ffffff" stroke-width="3">'
                         f'{html.escape(e.label)}</text>')
        for p in placed:
            fill, stroke, _ = _colour(p.node.status)
            focus = p.node.status == FOCUS
            rx, ry = (108, 40) if focus else (78, 30)
            shape = (f'<rect x="{p.x - rx:.0f}" y="{p.y - ry:.0f}" width="{rx * 2}" height="{ry * 2}" rx="10" '
                     if p.node.kind == "artifact" else
                     f'<rect x="{p.x - rx:.0f}" y="{p.y - ry:.0f}" width="{rx * 2}" height="{ry * 2}" rx="{ry}" ')
            parts.append(f'{shape}fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
            rows = _wrap(p.node.label, 22 if focus else 16, 2)
            top = p.y - (len(rows) - 1) * 7
            for i, row in enumerate(rows):
                parts.append(f'<text x="{p.x:.0f}" y="{top + i * 14:.0f}" text-anchor="middle" '
                             f'font-size="{13 if focus else 11.5}" fill="#ffffff" font-weight="'
                             f'{600 if focus else 400}">{html.escape(row)}</text>')
            if p.node.note:
                parts.append(f'<text x="{p.x:.0f}" y="{p.y + ry + 13:.0f}" text-anchor="middle" font-size="10" '
                             f'fill="#607d8b">{html.escape(p.node.note)}</text>')
        parts.append("</svg>")

        legend = "".join(
            f'<li><span style="background:{_colour(s)[0]}"></span>{html.escape(_colour(s)[2])}</li>'
            for s in view.statuses)
        subtitle = " · ".join(x for x in (view.subtitle, view.as_of) if x)
        page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(view.title)} — what it is connected to</title>
<style>
 :root {{ color-scheme: light }}
 body {{ margin:0; padding:24px; background:#f7f9fb; color:#1f2a44;
        font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif }}
 header {{ max-width:1180px; margin:0 auto 12px }}
 h1 {{ font-size:19px; margin:0 0 4px }} p {{ margin:0; color:#546e7a }}
 main {{ max-width:1180px; margin:0 auto; background:#fff; border:1px solid #e0e6ea; border-radius:10px;
         padding:8px }}
 ul {{ max-width:1180px; margin:14px auto 0; padding:0; list-style:none; display:flex; flex-wrap:wrap; gap:16px }}
 li {{ display:flex; align-items:center; gap:7px; color:#455a64; font-size:12.5px }}
 li span {{ width:13px; height:13px; border-radius:3px; display:inline-block }}
 footer {{ max-width:1180px; margin:16px auto 0; color:#78909c; font-size:12px }}
 @media print {{ body {{ background:#fff }} main {{ border:0 }} }}
</style></head>
<body><header><h1>{html.escape(view.title)}</h1><p>{html.escape(subtitle)}</p></header>
<main>{''.join(parts)}</main>
<ul>{legend}</ul>
<footer>The colour of a box says how the fabric knows it. Drawn from the graph as it stood when this page was
written; open it again for a newer one.</footer>
</body></html>
"""
        return Rendered(content=page.encode("utf-8"), media_type=self.media_type, suffix=self.suffix)


def build(**overrides) -> SvgHtmlRenderer:
    """The composition root's factory, so an adapter is chosen by configuration like every other port.

    This one has nothing to configure — the layout is deterministic and the palette is the rung ladder's
    own vocabulary — so an override is a caller's mistaken belief about it, and saying so beats accepting
    a setting that would never take effect."""
    if overrides:
        raise TypeError(f"the svg renderer takes no options; got {sorted(overrides)}")
    return SvgHtmlRenderer()
