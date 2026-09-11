"""drawio_cafe_svg.py — minimal mxGraph (.drawio) → inline SVG renderer.

Handles the subset of mxGraph features produced by drawio_c4.C4Diagram:
  * vertex cells with mxGeometry (x, y, width, height) and inline style (fillColor, strokeColor, dashed, …)
  * edge cells with source + target, plus an optional Array of mxPoint bend points
  * text labels (cell value), with multi-line via <br>
  * arrow marker (endArrow=block / open)
  * dashed lines (dashed=1, dashPattern=...)

This is approximate (file://-friendly preview), not a pixel-perfect drawio renderer. The .drawio file
itself is the authoritative output; open it in app.diagrams.net for editing.
"""
from __future__ import annotations
import re
import xml.etree.ElementTree as ET
from html import escape


def _parse_style(s: str | None) -> dict:
    out = {}
    if not s: return out
    for part in s.split(";"):
        part = part.strip()
        if not part: continue
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
        else:
            out[part] = "1"
    return out


def _stroke_dash(style: dict) -> str:
    if style.get("dashed") != "1": return ""
    pat = style.get("dashPattern", "4 4")
    return f'stroke-dasharray="{pat}"'


def _color(style: dict, key: str, default: str) -> str:
    c = style.get(key, default)
    return c if c.startswith("#") else default


def _text_to_svg_lines(value: str) -> list[str]:
    if not value: return []
    txt = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    txt = re.sub(r"<[^>]+>", "", txt)
    txt = txt.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;","<").replace("&gt;",">")
    lines = [l.strip() for l in txt.split("\n") if l.strip()]
    return lines


def _arrow_marker(svg_id: str, color: str) -> str:
    return (
        f'<marker id="{svg_id}" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/></marker>'
    )


def _orthogonalise(pts):
    """Insert corner points wherever consecutive points form a non-axis-aligned segment.
    Guarantees every rendered segment is strictly horizontal or vertical.
    Default corner choice: vertical-first (go to the new y at current x, then horizontal).
    """
    if len(pts) < 2: return pts
    out = [pts[0]]
    for i in range(1, len(pts)):
        px, py = out[-1]
        x, y = pts[i]
        if abs(px - x) < 0.5 or abs(py - y) < 0.5:
            out.append((x, y))
        else:
            # Insert a corner. Vertical first by default; switch to horizontal-first if the
            # following segment is more vertical (heuristic to reduce backtracking).
            prefer_v = True
            if i + 1 < len(pts):
                nx, ny = pts[i + 1]
                if abs(ny - y) > abs(nx - x):  # next segment is vertical-ish
                    prefer_v = False
            corner = (px, y) if prefer_v else (x, py)
            out.append(corner)
            out.append((x, y))
    return out


# Theme presets — dark matches CAFE_Artifacts_Visualisation.html (bg #0b0d12).
THEMES = {
    "dark":  {"canvas": "#0b0d12", "default_text": "#E6E8EE", "title_text": "#9CA3AF"},
    "light": {"canvas": "#fafbfc", "default_text": "#1A1A1A", "title_text": "#444444"},
}

# Dark-theme zone fills, keyed by the band's stroke colour (each CAFÉ zone has a unique stroke).
# When a band comes through as outline-only (fillColor=none from engine), we substitute a dark fill
# from this map so the band shows as a coloured panel on the dark canvas (matches HTML M5_ZONES).
DARK_ZONE_FILL_BY_STROKE = {
    "#5A82C4": "#1A2540",  # exp / data
    "#4AA0C4": "#0F2A36",  # gw
    "#9A6FD0": "#251736",  # cog
    "#3FAE8E": "#0A2C24",  # knw
    "#D09A4E": "#311F08",  # mod
    "#4FAAB8": "#062A30",  # too
    "#9A7A5A": "#251D18",  # ext
    "#C0526E": "#280F17",  # ident
    "#6AAA60": "#142513",  # obs
    "#6A7488": "#1A1D24",  # plat
    "#C9A100": "#2A2200",  # gold trust strip
}

# Edge palette swap for dark theme: dark-on-light hex → bright-on-dark hex.
# Covers both CAFÉ palette and engine internal-edge colours we don't control.
DARK_EDGE_REMAP = {
    "#1A1A1A": "#C7CED8",  # request — was near-black, now light slate
    "#0B7E63": "#2DD4BF",  # knowledge — bright teal
    "#C4651F": "#FB923C",  # tool — bright orange
    "#2D5B9E": "#60A5FA",  # data — bright blue
    "#777777": "#9CA3AF",  # event — light grey
    "#B89500": "#FBBF24",  # policy — bright gold
    "#7A4FB5": "#A78BFA",  # identity (CAFÉ) — bright purple
    "#9966AA": "#A78BFA",  # identity (engine default) — bright purple
    "#4F8A37": "#4ADE80",  # observe — bright green
    "#B85450": "#F87171",  # engine xtrust — bright red
    "#7A7A7A": "#9CA3AF",  # engine async — light grey
}


def drawio_to_svg(xml_text: str, title: str = "", theme: str = "dark") -> str:
    """Convert a drawio (mxGraph) XML document to a self-contained SVG string."""
    th = THEMES.get(theme, THEMES["dark"])
    # drawio_c4 writes raw mxGraphModel as the document; example:
    # <mxGraphModel ...><root>... <mxCell .../> ...</root></mxGraphModel>
    root = ET.fromstring(xml_text)
    cells = root.findall(".//mxCell")
    # Collect vertices and edges
    nodes: dict[str, dict] = {}      # id -> {x,y,w,h,style,value}
    edges: list[dict] = []
    for c in cells:
        cid = c.get("id"); style = _parse_style(c.get("style"))
        value = c.get("value", "") or ""
        if c.get("vertex") == "1":
            g = c.find("mxGeometry")
            if g is None: continue
            try:
                x = float(g.get("x", 0)); y = float(g.get("y", 0))
                w = float(g.get("width", 0)); h = float(g.get("height", 0))
            except (TypeError, ValueError):
                continue
            nodes[cid] = {"x":x,"y":y,"w":w,"h":h,"style":style,"value":value}
        elif c.get("edge") == "1":
            src = c.get("source"); tgt = c.get("target")
            pts = []
            arr = c.find(".//Array[@as='points']")
            if arr is not None:
                for p in arr.findall("mxPoint"):
                    try: pts.append((float(p.get("x",0)), float(p.get("y",0))))
                    except (TypeError, ValueError): pass
            edges.append({"id":cid,"src":src,"tgt":tgt,"pts":pts,"style":style,"value":value})

    # Canvas size: bounding box of all nodes + padding
    if not nodes:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="40"><text x="10" y="20">empty</text></svg>'
    pad = 20
    maxx = max(n["x"]+n["w"] for n in nodes.values())
    maxy = max(n["y"]+n["h"] for n in nodes.values())
    W = int(maxx + pad); H = int(maxy + pad)

    # Edge-color resolution: on dark theme, remap to bright variants for contrast.
    def resolve_edge_color(raw: str) -> str:
        if theme == "dark":
            return DARK_EDGE_REMAP.get(raw, raw)
        return raw

    # Collect arrow markers per (resolved) color
    markers = {}  # color -> marker id
    def marker_for(color: str) -> str:
        c = color or "#1A1A1A"
        if c not in markers:
            markers[c] = f"arr{len(markers)}"
        return markers[c]

    # Pre-pass: ensure arrow markers for every edge (using remapped colours)
    for e in edges:
        col = resolve_edge_color(_color(e["style"], "strokeColor", "#1A1A1A"))
        if e["style"].get("endArrow", "block") != "none":
            marker_for(col)

    # ----- Render vertices: zones (rounded=0, large; behind) and components (rounded=1, in front) -----
    # Sort: bigger boxes (zones) first (back), smaller (components) last (front)
    rendered = sorted(nodes.items(), key=lambda kv: -(kv[1]["w"]*kv[1]["h"]))

    parts = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
                 f'width="{W}" height="{H}" font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif">')
    # Defs (markers)
    parts.append("<defs>")
    for col, mid in markers.items():
        parts.append(_arrow_marker(mid, col))
    parts.append("</defs>")
    # Background — themed canvas (drawn FIRST so vertices sit on top)
    parts.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="{th["canvas"]}"/>')
    # Title
    if title:
        parts.append(f'<text x="{pad}" y="14" font-size="12" fill="{th["title_text"]}">{escape(title)}</text>')

    for cid, n in rendered:
        st = n["style"]
        raw_fill = st.get("fillColor", "")  # may legitimately be "none" (transparent)
        stroke = _color(st, "strokeColor", "#888888")
        sw = st.get("strokeWidth", "1")
        dash = _stroke_dash(st)
        rx = "6" if st.get("rounded") == "1" else "0"
        # Zone / band rendering: engine emits fillColor=none for bands in outline mode.
        # On dark theme, substitute a dark coloured fill keyed by stroke so the band shows
        # as a panel (not invisible). On light theme, keep "none" (engine's intended look).
        is_band_or_strip = n["w"] > 400 and n["h"] < 200 and raw_fill == "none"
        if raw_fill == "none":
            if theme == "dark":
                fill = DARK_ZONE_FILL_BY_STROKE.get(stroke, th["canvas"])
            else:
                fill = "none"
        else:
            fill = raw_fill if raw_fill.startswith("#") else "#FFFFFF"
        # Title cell on dark theme: engine writes strokeColor=none, fillColor=none — keep transparent
        if raw_fill == "none" and st.get("strokeColor", "") == "none":
            fill = "none"
        # Skip drawing rect if fully transparent (no stroke, no fill)
        if fill == "none" and st.get("strokeColor", "") == "none":
            pass
        else:
            stroke_attr = stroke if st.get("strokeColor", "") != "none" else "none"
            parts.append(
                f'<rect x="{n["x"]:.0f}" y="{n["y"]:.0f}" width="{n["w"]:.0f}" height="{n["h"]:.0f}" '
                f'rx="{rx}" ry="{rx}" fill="{fill}" stroke="{stroke_attr}" stroke-width="{sw}" {dash}/>'
            )
        # Label
        lines = _text_to_svg_lines(n["value"])
        if lines:
            # Heuristic: place text near top for tall bands, centred for small comps
            is_band = n["w"] > 400 and n["h"] < 120
            font_size = 12 if n["h"] > 60 else 11
            if is_band:
                tx = n["x"] + 10; ty = n["y"] + 16
                anchor = "start"; weight = "600"
            else:
                tx = n["x"] + n["w"]/2; ty = n["y"] + n["h"]/2 - (len(lines)-1)*6
                anchor = "middle"; weight = "500"
            # Honour cell's own fontColor if drawio-cafe post-processor set one; else theme default.
            font_fill = _color(st, "fontColor", th["default_text"])
            for i, ln in enumerate(lines):
                parts.append(
                    f'<text x="{tx:.0f}" y="{(ty + i*(font_size+2)):.0f}" font-size="{font_size}" '
                    f'fill="{font_fill}" text-anchor="{anchor}" font-weight="{weight}">{escape(ln)}</text>'
                )

    # ----- Render edges with explicit waypoint paths -----
    for e in edges:
        src = nodes.get(e["src"]); tgt = nodes.get(e["tgt"])
        if not src or not tgt: continue
        # Source/target ports = top/bottom centre per drawio-c4 convention
        sx, sy = src["x"]+src["w"]/2, src["y"]+src["h"]/2
        tx, ty = tgt["x"]+tgt["w"]/2, tgt["y"]+tgt["h"]/2
        # Snap to edge of box centre (top or bottom depending on direction)
        if ty >= sy:
            sy = src["y"]+src["h"]; ty = tgt["y"]
        else:
            sy = src["y"]; ty = tgt["y"]+tgt["h"]
        pts = [(sx, sy)] + e["pts"] + [(tx, ty)]
        pts = _orthogonalise(pts)  # guarantee strictly H/V segments — no diagonals
        d_attr = "M " + " L ".join(f"{x:.0f} {y:.0f}" for x,y in pts)
        col = resolve_edge_color(_color(e["style"], "strokeColor", "#1A1A1A"))
        # Slightly thicker default for visibility on dark canvas
        sw = e["style"].get("strokeWidth", "1.6" if theme == "dark" else "1.2")
        dash = _stroke_dash(e["style"])
        end_arrow = e["style"].get("endArrow", "block")
        marker = f'marker-end="url(#{markers[col]})"' if end_arrow != "none" and col in markers else ""
        parts.append(
            f'<path d="{d_attr}" fill="none" stroke="{col}" stroke-width="{sw}" {dash} {marker}/>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


# CLI smoke test
if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("usage: drawio_cafe_svg.py <file.drawio>"); sys.exit(2)
    xml = open(sys.argv[1]).read()
    print(drawio_to_svg(xml))
