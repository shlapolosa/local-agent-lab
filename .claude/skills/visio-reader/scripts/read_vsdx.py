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


def _txt(shape) -> str:
    try:
        return (shape.text or "").strip()
    except Exception:
        return ""


def read_vsdx(path: str) -> dict:
    f = VisioFile(path)
    try:
        out = {"file": path.split("/")[-1], "pages": [], "shapes": [], "connectors": []}
        for page in f.pages:
            if page.is_master_page:
                continue
            out["pages"].append(page.name)
            connects = list(page.connects)
            # id -> shape (all shapes on the page, connectors included)
            by_id = {}
            for s in page.all_shapes:
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
                out["shapes"].append({
                    "id": sid, "text": text,
                    "master": getattr(s, "universal_name", None) or _master(s),
                    "page": page.name,
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
                    "page": page.name,
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


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: read_vsdx.py <file.vsdx>", file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(read_vsdx(sys.argv[1]), indent=2))
