"""Deterministic Visio (.vsdx) parser for the Visio->ArchiMate workflow.

Parses a real Visio Model Exchange file into a plain dict the Business Analyst agent reasons
over. Reading is **local file I/O, no egress** — it runs in the workflow's deterministic ingest
node, not as an in-agent tool (in-agent tool-calling is unreliable through the gateway; see
CLAUDE.md). Output shape:

    {
      "file": "<name>",
      "pages": ["Page-1", ...],
      "shapes":     [{"id","text","master","page"}],        # element shapes (boxes/icons)
      "connectors": [{"from_id","from","to_id","to","label","page"}],  # resolved 1-D links
    }

Connectors in Visio are 1-D shapes whose endpoints live in the page <Connects> section:
a `BeginX` Connect binds the connector to its SOURCE shape, an `EndX` Connect to its TARGET.
We classify a shape as a connector iff it appears as a `FromSheet` in the page connects, so the
same logic works on hand-authored fixtures and genuine Visio uploads alike.

A **Lucidchart export has no <Connects> section at all** (verified on the real 244-shape Sahatna
cloud diagram: zero `<Connect>` rows on every page), so that pass finds nothing. It does carry a
`com.lucidchart.Line.*` shape per line with real Begin/End coordinates, so a SECOND, geometric pass
runs on such a file: absolute bounding boxes for every element shape (group offsets folded in),
absolute endpoints for every line, and each endpoint matched to its nearest box
(`lab.core.visio.geometry.recover_connectors`). Recovered links merge into the SAME `connectors`
list and are marked `recovered: "geometry"` + `match_distance` so their provenance stays visible; a
line shape recovered this way is a connector, never an element, so its caption ("TCP 443") stops
being read as a box. The pass also reports what it could NOT recover under `recovery`
(lines drawn vs links made, and why the rest failed) — a partial recovery must never read like a
sparse diagram. Native Visio files never enter this pass and gain no `recovery` key.

CLI: `python read_vsdx.py <file.vsdx>` prints the JSON.
"""
import json
import sys

from vsdx import VisioFile

from lab.core.visio.geometry import (DEFAULT_TOLERANCE_FACTOR, Box, Recovery, Segment,
                                     recover_connectors)
from lab.core.visio.read_lucidchart import (is_line_master, is_lucidchart_master,
                                            type_hint_for_master)


def _txt(shape) -> str:
    try:
        return (shape.text or "").strip()
    except Exception:
        return ""


def _cellf(shape, name) -> float | None:
    """One numeric ShapeSheet cell as a float, or None when absent/blank/unparsable."""
    try:
        v = shape.cell_value(name)
    except Exception:
        return None
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _is_transformed(shape) -> bool:
    """True iff the shape is ROTATED or FLIPPED, so a plain offset is not its children's origin."""
    return any((_cellf(shape, c) or 0.0) != 0.0 for c in ("Angle", "FlipX", "FlipY"))


def _collect_geometry(shapes, ox: float, oy: float, boxes: dict, segments: list,
                      skipped: list | None = None) -> None:
    """Walk the shape tree once, converting LOCAL ShapeSheet geometry to ABSOLUTE page coordinates.

    A Visio group's children are positioned in the group's own coordinate space, whose origin is the
    group's `(PinX - LocPinX, PinY - LocPinY)`; the offset accumulates down the tree (the Sahatna
    pages nest three deep). That formula holds only while the group is UNROTATED and UNFLIPPED — a
    non-zero `Angle`/`FlipX`/`FlipY` invalidates BOTH the shape's own axis-aligned box and its
    children's origin, and a box placed by the wrong formula would still match SOME endpoint and
    emit a confidently wrong relation. So a transformed shape and its whole subtree are skipped
    (recorded in `skipped`) rather than mis-placed: a missing link is a gap a reader can see, a
    wrong one survives the approval gate looking plausible. A LINE is exempt — its Begin/End cells
    ARE its endpoints, unaffected by its own rotation — so it is matched before this check.

    Fills `boxes` (shape id -> (x0, y0, x1, y1), any 2-D shape), `segments` (one `Segment` per line
    shape, endpoints already absolute) and `skipped` (ids of transformed groups)."""
    for s in shapes:
        px, py = _cellf(s, "PinX"), _cellf(s, "PinY")
        lx, ly = _cellf(s, "LocPinX") or 0.0, _cellf(s, "LocPinY") or 0.0
        w, h = _cellf(s, "Width"), _cellf(s, "Height")
        sid = str(s.ID) if s.ID is not None else None
        master = getattr(s, "universal_name", None) or _master(s)
        if sid and is_line_master(master):
            bx, by = _cellf(s, "BeginX"), _cellf(s, "BeginY")
            ex, ey = _cellf(s, "EndX"), _cellf(s, "EndY")
            if None not in (bx, by, ex, ey):
                segments.append(Segment(id=sid, label=_txt(s),
                                        bx=bx + ox, by=by + oy, ex=ex + ox, ey=ey + oy))
        elif _is_transformed(s):
            # A rotated/flipped shape's axis-aligned box AND its children's origin are both wrong
            # under this formula, so the whole subtree is skipped and counted — see the docstring.
            if skipped is not None and sid:
                skipped.append(sid)
            continue
        elif sid and px is not None and py is not None and w is not None and h is not None:
            x0, y0 = px - lx + ox, py - ly + oy
            boxes[sid] = (min(x0, x0 + w), min(y0, y0 + h), max(x0, x0 + w), max(y0, y0 + h))
        kids = list(getattr(s, "child_shapes", []) or [])
        if kids:
            kx, ky = (px - lx + ox, py - ly + oy) if px is not None and py is not None else (ox, oy)
            _collect_geometry(kids, kx, ky, boxes, segments, skipped)


def _page_match(page_name: str, want: str | None) -> bool:
    """Page selector: None = every page; else case/space-insensitive name match."""
    if want is None:
        return True
    return (page_name or "").strip().lower() == want.strip().lower()


def page_index(names, want: str | None) -> int:
    """Position of the page called `want` among `names` (the parse's `pages`), 0 when no page is
    named. Same case/space-insensitive matching as the parser, so the ONE page selector the whole
    pipeline uses (`ref#Page`) resolves identically for a parse and for a render."""
    if want is None:
        return 0
    for i, n in enumerate(names):
        if _page_match(n, want):
            return i
    raise ValueError(f"no page named {want!r} (pages: {list(names)})")


def page_names(path: str) -> list:
    """Just the drawable page names, in order — what `page_index` resolves against."""
    f = VisioFile(path)
    try:
        return [p.name for p in f.pages if not p.is_master_page]
    finally:
        f.close_vsdx()


def read_vsdx(path: str, page: str | None = None,
              tolerance_factor: float = DEFAULT_TOLERANCE_FACTOR) -> dict:
    """Parse the file. `page` (optional) restricts shapes/connectors to that ONE page by name — a
    multi-page workbook is many views, and a run models one view (Phase B explodes a workbook into
    one request per page). `pages` still lists every page so a caller can enumerate them.
    `tolerance_factor` tunes the Lucidchart geometric endpoint match (see `read_lucidchart`)."""
    f = VisioFile(path)
    try:
        out = {"file": path.split("/")[-1], "pages": [], "shapes": [], "connectors": [],
               "lucidchart": False, "page": page}
        recovery = Recovery()                              # totalled across the parsed pages
        # pre-pass: is this a Lucidchart export? (any shape carrying a `com.lucidchart.*` master).
        # Known up front so per-shape type_hint can trust bare child masters inside such a file.
        for pg in f.pages:                                 # `pg`, not `page`: `page` is the selector
            if pg.is_master_page:
                continue
            for s in pg.all_shapes:
                if is_lucidchart_master(getattr(s, "universal_name", None) or _master(s)):
                    out["lucidchart"] = True
                    break
            if out["lucidchart"]:
                break
        for page_obj in f.pages:
            if page_obj.is_master_page:
                continue
            out["pages"].append(page_obj.name)
            if not _page_match(page_obj.name, page):
                continue                                   # enumerate, but don't parse, other pages
            connects = list(page_obj.connects)
            # Lucidchart export: recover the geometry the export wrote instead of <Connects>.
            geo_boxes: dict = {}
            segments: list = []
            skipped: list = []
            if out["lucidchart"]:
                _collect_geometry(list(page_obj.child_shapes), 0.0, 0.0, geo_boxes, segments, skipped)
            line_ids = {seg.id for seg in segments}
            # id -> shape (all shapes on the page, connectors included)
            by_id = {}
            for s in page_obj.all_shapes:
                if s.ID is not None:
                    by_id[str(s.ID)] = s
            connector_ids = {str(c.from_id) for c in connects if c.from_id is not None}

            # element shapes = everything that is not a connector and carries a caption
            for sid, s in by_id.items():
                if sid in connector_ids or sid in line_ids:
                    continue          # a Lucidchart line is a connector; its caption is a link label
                text = _txt(s)
                if not text:
                    continue
                master = getattr(s, "universal_name", None) or _master(s)
                out["shapes"].append({
                    "id": sid, "text": text,
                    "master": master,
                    # additive ArchiMate 3.1 type EVIDENCE from a Lucidchart/Azure typed
                    # stencil; null for native/unrecognized shapes (behaviour unchanged there)
                    "type_hint": type_hint_for_master(master, out["lucidchart"]),
                    "page": page_obj.name,
                })

            # resolve each connector's source/target from its Begin/End connects
            grouped = {}
            for c in connects:
                grouped.setdefault(str(c.from_id), []).append(c)
            for cid, rows in grouped.items():
                src_id = tgt_id = None
                for c in rows:
                    rel = (c.from_rel or "")
                    if "Begin" in rel:
                        src_id = str(c.to_id)
                    elif "End" in rel:
                        tgt_id = str(c.to_id)
                # fallback for connectors without Begin/End labelling: order of appearance
                if (src_id is None or tgt_id is None) and len(rows) >= 2:
                    ends = [str(r.to_id) for r in rows]
                    src_id = src_id or ends[0]
                    tgt_id = tgt_id or ends[1]
                if not src_id or not tgt_id:
                    continue
                conn_shape = by_id.get(cid)
                out["connectors"].append({
                    "from_id": src_id, "from": _txt(by_id.get(src_id)) if by_id.get(src_id) else None,
                    "to_id": tgt_id, "to": _txt(by_id.get(tgt_id)) if by_id.get(tgt_id) else None,
                    "label": _txt(conn_shape) if conn_shape else "",
                    "page": page_obj.name,
                })

            # second pass: geometric recovery, over the elements THIS page reported. A pair the
            # native pass already resolved is authoritative and is never duplicated.
            if segments:
                # THIS page's native pairs only: shape ids repeat across pages (the Sahatna
                # workbook's pages are near-copies), so a file-wide set silently dropped real links
                native = {(c["from_id"], c["to_id"]) for c in out["connectors"]
                          if c["page"] == page_obj.name}
                elements = [Box(sh["id"], sh["text"], *geo_boxes[sh["id"]])
                            for sh in out["shapes"]
                            if sh["page"] == page_obj.name and sh["id"] in geo_boxes]
                rec = recover_connectors(segments, elements, page_obj.name, tolerance_factor)
                fresh = [c for c in rec.connectors if (c["from_id"], c["to_id"]) not in native]
                out["connectors"] += fresh
                rec.stats["skipped_transformed_groups"] = len(skipped)
                recovery = recovery.merged(Recovery(fresh, rec.stats))
        if out["lucidchart"]:
            out["recovery"] = recovery.stats
        return out
    finally:
        f.close_vsdx()


def _master(shape):
    try:
        m = shape.master_shape
        return getattr(m, "text", None) or getattr(m, "name", None)
    except Exception:
        return None


def main(argv=None):
    """CLI: read_vsdx <file.vsdx> -> the parsed JSON on stdout (exit 2 on a usage error)."""
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: read_vsdx.py <file.vsdx>", file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(read_vsdx(argv[0]), indent=2))


if __name__ == "__main__":
    main()
