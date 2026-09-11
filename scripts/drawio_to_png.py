"""Rasterise a .drawio (mxGraph) file to PNG, with nothing but Pillow.

    .venv/bin/python scripts/drawio_to_png.py var/out/architecture/worktree-heatmap.drawio

WHY THIS EXISTS. The usual converters are all absent on this machine — no `drawio` CLI, no
`rsvg-convert`, no `inkscape`, no `cairosvg`, no ImageMagick — so a diagram that is only a `.drawio`
cannot be looked at without opening a browser. Pillow IS present, and the mxGraph file already
carries every coordinate: absolute `x/y/width/height` per vertex and explicit waypoints per edge.
So the raster is a direct read of the geometry rather than a re-layout, and it cannot disagree with
what draw.io shows except in typography.

DELIBERATELY NARROW. It renders what `drawio_c4` emits — rounded boxes, bands, dashed strokes,
polyline edges with arrowheads, bold-first-line labels. It is not an mxGraph implementation: no
curves, no swimlanes, no images, no relative child geometry. Anything it does not understand it
draws as a plain rectangle rather than guessing, because a diagram that quietly omits a shape is
worse than one that shows an unstyled box.
"""
import html
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

SCALE = 2                      # retina; the text stays legible when the png is scaled down
MARGIN = 30
BG = "#FFFFFF"

FONTS = ("/System/Library/Fonts/Supplemental/Arial.ttf",
         "/System/Library/Fonts/Helvetica.ttc",
         "/Library/Fonts/Arial.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
BOLD = ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def _font(paths, size):
    for p in paths:
        if pathlib.Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:                      # noqa: BLE001 — a font that will not load is not fatal
                continue
    return ImageFont.load_default()


def style_of(cell) -> dict:
    out = {}
    for part in (cell.get("style") or "").split(";"):
        if "=" in part:
            k, _, v = part.partition("=")
            out[k.strip()] = v.strip()
        elif part.strip():
            out[part.strip()] = "1"
    return out


def text_of(cell) -> list[str]:
    """The label as lines. mxGraph puts `&#10;` between them and `<b>` around the first."""
    raw = cell.get("value") or ""
    raw = html.unescape(raw)
    raw = re.sub(r"<br\s*/?>", "\n", raw)
    bold_first = "<b>" in raw
    raw = re.sub(r"<[^>]+>", "", raw)
    lines = [ln for ln in raw.split("\n")]
    return lines, bold_first


def bounds(root) -> tuple[float, float, float, float]:
    xs, ys, xe, ye = [], [], [], []
    for cell in root.iter("mxCell"):
        g = cell.find("mxGeometry")
        if g is None:
            continue
        if g.get("x") is not None:
            x, y = float(g.get("x", 0)), float(g.get("y", 0))
            w, h = float(g.get("width", 0)), float(g.get("height", 0))
            xs.append(x); ys.append(y); xe.append(x + w); ye.append(y + h)
        for p in g.iter("mxPoint"):
            if p.get("x") is not None:
                xs.append(float(p.get("x"))); xe.append(float(p.get("x")))
                ys.append(float(p.get("y", 0))); ye.append(float(p.get("y", 0)))
    return min(xs), min(ys), max(xe), max(ye)


def render(path: pathlib.Path) -> pathlib.Path:
    root = ET.parse(path).getroot()
    x0, y0, x1, y1 = bounds(root)
    W = int((x1 - x0 + 2 * MARGIN) * SCALE)
    H = int((y1 - y0 + 2 * MARGIN) * SCALE)
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)

    def X(v): return (float(v) - x0 + MARGIN) * SCALE
    def Y(v): return (float(v) - y0 + MARGIN) * SCALE

    cells = list(root.iter("mxCell"))
    # bands first (widest boxes), so component boxes land on top of their container
    verts = [c for c in cells if c.get("vertex") == "1" and c.find("mxGeometry") is not None]
    verts.sort(key=lambda c: -float(c.find("mxGeometry").get("width", 0)))

    for cell in verts:
        g = cell.find("mxGeometry")
        st = style_of(cell)
        bx, by = X(g.get("x", 0)), Y(g.get("y", 0))
        bw, bh = float(g.get("width", 0)) * SCALE, float(g.get("height", 0)) * SCALE
        # `none` is a real mxGraph value for BOTH of these and Pillow rejects it as a colour.
        # The CAFE renderer uses strokeColor=none where the C4 one never did — found by rendering it.
        def _col(v, fallback=None):
            return fallback if v in (None, "", "none") else v
        fill = _col(st.get("fillColor"))
        stroke = _col(st.get("strokeColor"), "#000000")
        box = [bx, by, bx + bw, by + bh]
        if st.get("ellipse"):
            dr.ellipse(box, fill=fill, outline=stroke)
            continue
        radius = 10 * SCALE if st.get("rounded") == "1" else 0
        kw = {"fill": fill, "outline": stroke,
              "width": max(1, int(float(st.get("strokeWidth", 1)) * SCALE))}
        if radius:
            dr.rounded_rectangle(box, radius=radius, **kw)
        else:
            dr.rectangle(box, **kw)

        lines, bold_first = text_of(cell)
        if not any(ln.strip() for ln in lines):
            continue
        size = int(float(st.get("fontSize", 10)) * SCALE)
        fcol = st.get("fontColor", "#1A1A1A")
        head = _font(BOLD if bold_first or st.get("fontStyle") == "1" else FONTS, size)
        body = _font(FONTS, max(8, size - SCALE))
        align = st.get("align", "center")

        # WRAP. mxGraph boxes carry `whiteSpace=wrap` and draw.io honours it; Pillow has no concept
        # of a text box, so without this a description simply runs out of its box and is overprinted
        # by the neighbour — which is what the first CAFE render did, silently and legibly enough to
        # look almost right.
        avail = bw - 16 * SCALE
        wrapped: list[tuple[str, object]] = []
        for i, ln in enumerate(lines):
            f = head if i == 0 else body
            if dr.textlength(ln, font=f) <= avail or not ln.strip():
                wrapped.append((ln, f))
                continue
            cur = ""
            for word in ln.split():
                trial = f"{cur} {word}".strip()
                if dr.textlength(trial, font=f) <= avail or not cur:
                    cur = trial
                else:
                    wrapped.append((cur, f))
                    cur = word
            if cur:
                wrapped.append((cur, f))

        lh = size + 2 * SCALE
        ty = by + (6 * SCALE if st.get("verticalAlign", "middle") == "top" else
                   max(4 * SCALE, (bh - len(wrapped) * lh) / 2))
        for text, f in wrapped:
            tw = dr.textlength(text, font=f)
            tx = {"left": bx + 8 * SCALE, "right": bx + bw - tw - 8 * SCALE}.get(
                align, bx + (bw - tw) / 2)
            dr.text((tx, ty), text, font=f, fill=fcol)
            ty += lh

    for cell in (c for c in cells if c.get("edge") == "1"):
        g = cell.find("mxGeometry")
        if g is None:
            continue
        pts = [(X(p.get("x")), Y(p.get("y"))) for p in g.iter("mxPoint")
               if p.get("x") is not None and p.get("as") not in ("offset",)]
        if len(pts) < 2:
            continue
        st = style_of(cell)
        col = st.get("strokeColor") or "#1A1A1A"
        col = "#1A1A1A" if col == "none" else col
        w = max(1, int(float(st.get("strokeWidth", 1)) * SCALE))
        if st.get("dashed") == "1":
            for (ax, ay), (bx2, by2) in zip(pts, pts[1:]):        # manual dashes: Pillow has none
                n = max(1, int(((bx2 - ax) ** 2 + (by2 - ay) ** 2) ** 0.5 / (8 * SCALE)))
                for k in range(0, n, 2):
                    t0, t1 = k / n, min(1.0, (k + 1) / n)
                    dr.line([ax + (bx2 - ax) * t0, ay + (by2 - ay) * t0,
                             ax + (bx2 - ax) * t1, ay + (by2 - ay) * t1], fill=col, width=w)
        else:
            dr.line([c for p in pts for c in p], fill=col, width=w)
        # arrowhead on the final segment
        (px, py), (qx, qy) = pts[-2], pts[-1]
        dx, dy = qx - px, qy - py
        n = (dx * dx + dy * dy) ** 0.5 or 1
        ux, uy = dx / n, dy / n
        s = 5 * SCALE
        dr.polygon([(qx, qy), (qx - ux * s * 2 - uy * s, qy - uy * s * 2 + ux * s),
                    (qx - ux * s * 2 + uy * s, qy - uy * s * 2 - ux * s)], fill=col)

    out = path.with_suffix(".png")
    img.save(out, "PNG")
    return out


if __name__ == "__main__":
    src = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                       else "var/out/architecture/worktree-heatmap.drawio")
    dest = render(src)
    im = Image.open(dest)
    print(f"wrote {dest}  {im.width}x{im.height}px  {dest.stat().st_size // 1024} KB")
