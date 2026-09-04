"""Connector recovery from LINE GEOMETRY — for a diagram whose exporter drew its lines as plain
shapes instead of binding them to the shapes they touch.

Pure arithmetic on plain values: boxes and segments in, connector dicts out. No vsdx, no I/O, no
vendor. `read_vsdx.py` extracts the geometry (folding group offsets into absolute page coordinates)
and a vendor profile (`read_lucidchart.py` today) says WHICH shapes are lines; everything from there
on is here, so the next exporter that needs it reuses this module rather than copying it.

Why it is needed at all: a native Visio file binds a connector to its endpoints in the page's
`<Connects>` section, and resolving `from`/`to` is a lookup. A Lucidchart export writes no
`<Connects>` at all (verified: zero `<Connect>` rows on every page of the 244-shape Sahatna cloud
diagram), so the only evidence left is where each line's ends were DRAWN — matched to the nearest
element bounding box.

The result is honest about itself: every recovered link carries `recovered: "geometry"` and its
`match_distance`, and `Recovery.stats` counts the lines that could NOT be turned into a link, so a
reader is never left thinking a sparse parse was a sparse diagram.
"""
from dataclasses import dataclass, field

# A line's endpoint is drawn a small gap away from the shape it attaches to, so the match is
# "nearest bounding box within a tolerance". The tolerance is a MULTIPLE OF THE MEDIAN ELEMENT SIZE
# rather than an absolute length, because a .vsdx page is in inches at whatever scale the author
# drew at (the Sahatna pages span ~13-16 in diagonal with ~0.3 in icons). Reading: "an endpoint
# belongs to a shape if it is no further away than a typical element is wide". Measured on the real
# file: 1.0 resolves 76/82 endpoints on page 1 and 37/48 on page 2; 1.5 gains a few more but starts
# reaching PAST a nearer shape, so 1.0 is the default and the caller can widen it.
DEFAULT_TOLERANCE_FACTOR = 1.0


@dataclass(frozen=True)
class Box:
    """An element shape's ABSOLUTE bounding box on the page (group offsets already folded in)."""
    id: str
    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def area(self) -> float:
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    @property
    def min_edge(self) -> float:
        return min(self.x1 - self.x0, self.y1 - self.y0)


@dataclass(frozen=True)
class Segment:
    """A line shape's ABSOLUTE begin/end point plus its caption (the connector's label)."""
    id: str
    label: str
    bx: float
    by: float
    ex: float
    ey: float


@dataclass(frozen=True)
class Recovery:
    """What `recover_connectors` produced AND what it could not: `stats` is the audit trail that
    keeps a partial recovery from reading like a sparse diagram (`lines` drawn, `recovered` links,
    and the three reasons a line yields none)."""
    connectors: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def merged(self, other: "Recovery") -> "Recovery":
        """This recovery plus another's — used to total a multi-page parse."""
        stats = dict(self.stats)
        for k, v in other.stats.items():
            stats[k] = stats.get(k, 0) + v
        return Recovery(self.connectors + other.connectors, stats)


def box_distance(x: float, y: float, box: Box) -> float:
    """Euclidean distance from a point to a box; 0 when the point is inside or on the edge."""
    dx = max(box.x0 - x, 0.0, x - box.x1)
    dy = max(box.y0 - y, 0.0, y - box.y1)
    return (dx * dx + dy * dy) ** 0.5


def median_min_edge(boxes) -> float:
    """Median of the elements' shorter edge — the drawing's own length scale (0 when there are none)."""
    edges = sorted(b.min_edge for b in boxes)
    if not edges:
        return 0.0
    mid = len(edges) // 2
    return edges[mid] if len(edges) % 2 else (edges[mid - 1] + edges[mid]) / 2


def nearest_box(x: float, y: float, boxes, tolerance: float):
    """The element a point attaches to: `(Box, distance)` or None when nothing is within `tolerance`.
    Ties (a point inside both an element and its grouping box) go to the SMALLER box — the specific
    element, never the zone that merely contains it."""
    best = None
    for b in boxes:
        d = box_distance(x, y, b)
        if d <= tolerance and (best is None or (d, b.area) < (best[1], best[0].area)):
            best = (b, d)
    return best


def recover_connectors(segments, boxes, page: str,
                       tolerance_factor: float = DEFAULT_TOLERANCE_FACTOR) -> Recovery:
    """Rebuild `from`/`to` links from line geometry: each segment's begin/end point is matched to the
    nearest element box within `tolerance_factor * median element size`.

    Connector dicts come out in exactly the shape `read_vsdx` emits for NATIVE connectors, plus two
    provenance keys a native connector never carries — `recovered: "geometry"` and `match_distance`
    (the worse of the two endpoint distances) — so a reader can see the link was inferred and how
    tight the inference was. A segment yields nothing when an endpoint matches no element, when both
    ends match the SAME shape (a self-link is a drawing artefact, not a dependency), or when that
    pair is already recovered (the labelled occurrence wins). Each of those is COUNTED in
    `Recovery.stats`, because a silently dropped line is a dependency the model will never show."""
    stats = {"lines": len(segments), "recovered": 0,
             "unmatched_endpoint": 0, "self_link": 0, "duplicate": 0}
    if not segments or not boxes:
        stats["unmatched_endpoint"] = len(segments)
        return Recovery([], stats)
    tolerance = median_min_edge(boxes) * tolerance_factor
    out: dict[tuple[str, str], dict] = {}
    for seg in segments:
        src = nearest_box(seg.bx, seg.by, boxes, tolerance)
        tgt = nearest_box(seg.ex, seg.ey, boxes, tolerance)
        if not src or not tgt:
            stats["unmatched_endpoint"] += 1
            continue
        if src[0].id == tgt[0].id:
            stats["self_link"] += 1
            continue
        key = (src[0].id, tgt[0].id)
        prev = out.get(key)
        if prev:
            stats["duplicate"] += 1
            if prev["label"] or not seg.label:
                continue                              # keep the first, unless this one adds a label
        out[key] = {"from_id": src[0].id, "from": src[0].text, "to_id": tgt[0].id, "to": tgt[0].text,
                    "label": seg.label, "page": page, "recovered": "geometry",
                    "match_distance": round(max(src[1], tgt[1]), 4)}
    stats["recovered"] = len(out)
    return Recovery(list(out.values()), stats)
