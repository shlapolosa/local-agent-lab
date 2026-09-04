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

CLI: `python read_vsdx.py <file.vsdx>` prints the JSON.
"""
import json
import sys

from vsdx import VisioFile

from lab.core.visio.read_lucidchart import is_lucidchart_master, type_hint_for_master


def _txt(shape) -> str:
    try:
        return (shape.text or "").strip()
    except Exception:
        return ""


def _page_match(page_name: str, want: str | None) -> bool:
    """Page selector: None = every page; else case/space-insensitive name match."""
    if want is None:
        return True
    return (page_name or "").strip().lower() == want.strip().lower()


def read_vsdx(path: str, page: str | None = None) -> dict:
    """Parse the file. `page` (optional) restricts shapes/connectors to that ONE page by name — a
    multi-page workbook is many views, and a run models one view (Phase B explodes a workbook into
    one request per page). `pages` still lists every page so a caller can enumerate them."""
    f = VisioFile(path)
    try:
        out = {"file": path.split("/")[-1], "pages": [], "shapes": [], "connectors": [],
               "lucidchart": False, "page": page}
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
            # id -> shape (all shapes on the page, connectors included)
            by_id = {}
            for s in page_obj.all_shapes:
                if s.ID is not None:
                    by_id[str(s.ID)] = s
            connector_ids = {str(c.from_id) for c in connects if c.from_id is not None}

            # element shapes = everything that is not a connector and carries a caption
            for sid, s in by_id.items():
                if sid in connector_ids:
                    continue
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
