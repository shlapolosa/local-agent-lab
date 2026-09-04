"""Lucidchart / Azure typed-stencil -> ArchiMate 3.1 type EVIDENCE for the Visio parser.

A Lucidchart-exported `.vsdx` names each icon's master with a stable stencil-family string
(captured as a shape's `universal_name` / `master`), e.g. `com.lucidchart.VirtualMachineAzure2021.109`
or `com.lucidchart.ExpressRouteDirectAzure2021.592`. Two things follow from that, and this module
holds both — as PURE data + string matching + arithmetic (no I/O, no vsdx, no egress):

1. **Typed stencils are type EVIDENCE.** The master string names the Azure resource kind, which maps
   deterministically to a best-guess ArchiMate 3.1 element type. `read_vsdx.py` stamps it as an
   additive per-shape `type_hint`; a master matching no token stays None, so native Visio parsing is
   unchanged.
2. **Connectors must be recovered GEOMETRICALLY.** A Lucidchart export writes NO `<Connects>` section
   at all (verified on the 244-shape Sahatna cloud diagram: 0 `<Connect>` rows across every page), so
   the native endpoint resolution finds nothing. What it DOES write is a `com.lucidchart.Line.*` shape
   per line carrying real `BeginX/BeginY/EndX/EndY` cells in page coordinates. Matching each endpoint
   to the nearest element bounding box therefore reconstructs `from`/`to` — see `recover_connectors`.

The map is intentionally a simple ORDERED list of (token, ArchiMate type). Matching is
case/space/punctuation-insensitive (so `com.lucidchart.VirtualMachineAzure2021.109`, a bare
`VirtualMachine`, and a native `"Virtual Machine"` stencil all match the same token). First match
wins, so list more specific tokens before their substrings. Extend by adding a row.
"""
from dataclasses import dataclass

from lab.core.canon import squash   # the lab's ONE punctuation-squash normaliser


# (token, ArchiMate 3.1 type). token is matched, normalized, as a substring of the normalized
# master string. Order matters: earlier rows win, so put specific tokens above broader ones.
STENCIL_TYPE_MAP = [
    # --- compute -> Node (a computational resource that hosts/executes) ---
    ("VMScaleSets",        "Node"),
    ("VirtualMachine",     "Node"),
    ("Kubernetes",         "Node"),
    ("AKS",                "Node"),
    ("Bastion",            "Node"),
    ("Firewall",           "Node"),
    ("ApplicationGateway", "Node"),   # L7 gateway/appliance
    ("LoadBalancer",       "Node"),
    # --- application workloads -> ApplicationComponent ---
    ("AppService",         "ApplicationComponent"),
    ("WebApp",             "ApplicationComponent"),
    ("FunctionApps",       "ApplicationComponent"),   # serverless app (extra, clear)
    # --- platform / system software -> SystemSoftware ---
    ("KeyVault",           "SystemSoftware"),
    ("CacheRedis",         "SystemSoftware"),          # extra: managed cache runtime
    ("ApplicationInsights","SystemSoftware"),          # extra: observability/Monitor family
    ("LogAnalytics",       "SystemSoftware"),          # extra: observability/Monitor family
    ("Observability",      "SystemSoftware"),
    ("Monitor",            "SystemSoftware"),
    ("EventHubs",          "SystemSoftware"),           # extra: managed messaging runtime
    # --- data -> DataObject ---
    ("SqlDatabase",        "DataObject"),
    ("Database",           "DataObject"),
    # --- storage -> Artifact (a passive stored data element) ---
    ("StorageAccounts",    "Artifact"),
    ("Blob",               "Artifact"),
    ("Storage",            "Artifact"),
    # --- networking -> CommunicationNetwork ---
    ("ExpressRoute",       "CommunicationNetwork"),
    ("VirtualNetwork",     "CommunicationNetwork"),
    ("Subnet",             "CommunicationNetwork"),
    ("NetworkInterface",   "CommunicationNetwork"),     # extra: NIC, a network access point
    ("PrivateLink",        "CommunicationNetwork"),      # extra: private network path
]


# precompute normalized tokens once
_NORM_MAP = [(squash(tok), arch) for tok, arch in STENCIL_TYPE_MAP]


def is_lucidchart_master(master) -> bool:
    """True iff the master string is a Lucidchart-exported stencil (`com.lucidchart.*`)."""
    return isinstance(master, str) and "com.lucidchart." in master.lower()


def is_typed_stencil(master) -> bool:
    """True iff `master` is a TYPED cloud stencil we trust for type evidence.

    That means a Lucidchart export (`com.lucidchart.*`) or an Azure-branded master
    (e.g. Lucidchart's `...Azure2021`, or a native Microsoft Azure Visio stencil). This gate is
    deliberate: a broad token like `Database` or `Storage` would otherwise also fire on a GENERIC
    native Visio shape (e.g. Malaffi's `Database.70`), which is NOT a typed cloud stencil and must
    stay `type_hint=None`. Type evidence comes only from a recognizably typed stencil.
    """
    if not isinstance(master, str):
        return False
    low = master.lower()
    return "com.lucidchart." in low or "azure" in low


def _token_type(master) -> str | None:
    """Raw token lookup: the ArchiMate type for the first matching stencil token, else None."""
    if not isinstance(master, str) or not master:
        return None
    norm = squash(master)
    for norm_tok, arch in _NORM_MAP:
        if norm_tok in norm:
            return arch
    return None


def type_hint_for_master(master, in_lucidchart_file: bool = False) -> str | None:
    """Best-guess ArchiMate 3.1 type for a stencil master, else None.

    Type evidence is trusted only from a TYPED cloud stencil. A master qualifies when it is
    Azure-branded / Lucidchart itself (`is_typed_stencil`), OR when the whole file is a Lucidchart
    export (`in_lucidchart_file=True`) — inside such a file even bare child masters like
    `ExpressRoute` are genuine typed stencils. A generic native Visio shape (e.g. Malaffi's
    `Database.70`) matches neither and stays None, so native parsing is unchanged.
    """
    if not (in_lucidchart_file or is_typed_stencil(master)):
        return None
    return _token_type(master)


# ------------------------------------------------------------------ geometric connector recovery
# A Lucidchart line's endpoint is drawn a small gap away from the shape it attaches to, so the match
# is "nearest bounding box within a tolerance". The tolerance is expressed as a MULTIPLE OF THE
# MEDIAN ELEMENT SIZE rather than an absolute length, because a .vsdx page is in inches at whatever
# scale the author drew at (the Sahatna pages span ~13-16 in diagonal with ~0.3 in icons). Reading:
# "an endpoint belongs to a shape if it is no further away than a typical element is wide".
# Measured on the real file: 1.0 resolves 76/82 endpoints on page 1 and 37/48 on page 2; 1.5 gains a
# few more but starts reaching PAST a nearer shape, so 1.0 is the default and the caller can widen it.
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


def is_line_master(master) -> bool:
    """True iff the master names Lucidchart's LINE family (`com.lucidchart.Line.<n>`) — the shapes
    that carry a connector's endpoint geometry. Narrow on purpose: `com.lucidchart.LineChart.*` is a
    different family, and on the real file only this one carries `BeginX` at top level."""
    if not isinstance(master, str):
        return False
    parts = master.split(".")
    return len(parts) >= 3 and parts[0].lower() == "com" and parts[1].lower() == "lucidchart" \
        and parts[2].lower() == "line"


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
                       tolerance_factor: float = DEFAULT_TOLERANCE_FACTOR) -> list[dict]:
    """Rebuild `from`/`to` links from line geometry: each segment's begin/end point is matched to the
    nearest element box within `tolerance_factor * median element size`.

    Returns connector dicts in exactly the shape `read_vsdx` emits for NATIVE connectors, plus two
    provenance keys a native connector never carries — `recovered: "geometry"` and `match_distance`
    (the worse of the two endpoint distances) — so a reader can see the link was inferred and how
    tight the inference was. A segment is dropped when either endpoint matches nothing or both match
    the SAME shape (a self-link is a drawing artefact, not a dependency); a pair already recovered is
    kept once, preferring the labelled occurrence."""
    if not segments or not boxes:
        return []
    tolerance = median_min_edge(boxes) * tolerance_factor
    out: dict[tuple[str, str], dict] = {}
    for seg in segments:
        src = nearest_box(seg.bx, seg.by, boxes, tolerance)
        tgt = nearest_box(seg.ex, seg.ey, boxes, tolerance)
        if not src or not tgt or src[0].id == tgt[0].id:
            continue
        key = (src[0].id, tgt[0].id)
        prev = out.get(key)
        if prev and (prev["label"] or not seg.label):
            continue                                  # keep the first, unless this one adds a label
        out[key] = {"from_id": src[0].id, "from": src[0].text, "to_id": tgt[0].id, "to": tgt[0].text,
                    "label": seg.label, "page": page, "recovered": "geometry",
                    "match_distance": round(max(src[1], tgt[1]), 4)}
    return list(out.values())
