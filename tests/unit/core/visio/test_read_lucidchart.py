"""src/lab/core/visio/read_lucidchart — stencil master -> ArchiMate type_hint table (incl. the native
`Database.70` negative), the shared `squash` normaliser, and the PURE geometric connector recovery
(endpoint -> nearest element bounding box) that gives a Lucidchart export the connectors its export
never wrote as native `<Connects>`. No I/O, no vsdx: plain Box/Segment values in, connector dicts out.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/core/visio/test_read_lucidchart.py"""
import pytest

from lab.core.canon import squash
from lab.core.visio import read_lucidchart as L

# (master, in_lucidchart_file) -> type_hint
TABLE = [
    ("com.lucidchart.VirtualMachineAzure2021.109", False, "Node"),
    ("com.lucidchart.ExpressRouteDirectAzure2021.592", False, "CommunicationNetwork"),
    ("com.lucidchart.VMScaleSetsAzure2021.3", False, "Node"),            # specific token wins over VirtualMachine
    ("com.lucidchart.SqlDatabaseAzure2021.12", False, "DataObject"),
    ("com.lucidchart.StorageAccountsAzure2021.7", False, "Artifact"),
    ("com.lucidchart.KeyVaultAzure2021.1", False, "SystemSoftware"),
    ("com.lucidchart.UnknownThingAzure2021.1", False, None),             # typed stencil, no token -> None
    ("Microsoft Azure SQL Database", False, "DataObject"),               # native Azure-branded Visio master
    ("ExpressRoute", True, "CommunicationNetwork"),                      # bare child master inside a Lucidchart file
    ("ExpressRoute", False, None),                                       # …but not trusted outside one
    ("Database.70", False, None),                                        # generic native Visio shape stays untyped
    ("Database.70", True, "DataObject"),                                 # inside a Lucidchart export it IS a typed stencil
    ("Process", True, None),
    ("", True, None),
    (None, True, None),
]


def test_type_hint_table():
    for master, in_lucid, expected in TABLE:
        got = L.type_hint_for_master(master, in_lucidchart_file=in_lucid)
        assert got == expected, (master, in_lucid, got, expected)


def test_gates():
    assert L.is_lucidchart_master("com.lucidchart.X") and not L.is_lucidchart_master("X") and not L.is_lucidchart_master(None)
    assert L.is_typed_stencil("Microsoft Azure Blob") and L.is_typed_stencil("COM.LUCIDCHART.y")
    assert not L.is_typed_stencil("Database.70") and not L.is_typed_stencil(7)


def test_normaliser_is_the_shared_one():
    assert L.squash is squash                                             # one normaliser, no local copy


def test_line_master_family_is_recognised_narrowly():
    assert L.is_line_master("com.lucidchart.Line.105") and L.is_line_master("COM.LUCIDCHART.LINE.7")
    assert not L.is_line_master("com.lucidchart.LineChart.9")      # a different family, not a connector
    assert not L.is_line_master("com.lucidchart.FreehandBlock.44")
    assert not L.is_line_master("Dynamic connector") and not L.is_line_master(None)


# ------------------------------------------------------------------ pure geometry
def box(i, text, x0, y0, x1, y1):
    return L.Box(id=i, text=text, x0=x0, y0=y0, x1=x1, y1=y1)


def seg(i, bx, by, ex, ey, label=""):
    return L.Segment(id=i, label=label, bx=bx, by=by, ex=ex, ey=ey)


#   A = [0,0]-[1,1]      B = [3,0]-[4,1]      C (container) = [-1,-1]-[5,2]
A, B, CONTAINER = box("1", "Alpha", 0, 0, 1, 1), box("2", "Beta", 3, 0, 4, 1), box("3", "Zone", -1, -1, 5, 2)


def test_box_distance_is_zero_inside_and_euclidean_outside():
    assert L.box_distance(0.5, 0.5, A) == 0.0            # inside
    assert L.box_distance(1.0, 0.5, A) == 0.0            # on the edge
    assert L.box_distance(2.0, 0.5, A) == 1.0            # straight out to the right
    assert L.box_distance(4.0, 4.0, A) == pytest.approx((3 ** 2 + 3 ** 2) ** 0.5)   # diagonal corner


def test_median_min_edge_scales_the_tolerance_to_the_drawing():
    assert L.median_min_edge([A, B]) == 1.0
    assert L.median_min_edge([]) == 0.0                  # nothing to scale to


def test_nearest_box_prefers_the_smallest_box_at_equal_distance():
    # the endpoint is inside BOTH the element and its container -> the element (smaller area) wins
    hit = L.nearest_box(0.5, 0.5, [CONTAINER, A], tolerance=1.0)
    assert hit is not None and hit[0].id == "1" and hit[1] == 0.0


def test_nearest_box_returns_none_beyond_the_tolerance():
    assert L.nearest_box(10.0, 10.0, [A, B], tolerance=1.0) is None
    assert L.nearest_box(2.0, 0.5, [A, B], tolerance=0.5) is None       # 1.0 away, tolerance 0.5
    assert L.nearest_box(2.0, 0.5, [A, B], tolerance=1.0)[0].id == "1"  # exactly at the tolerance
    assert L.nearest_box(0.5, 0.5, [], tolerance=1.0) is None


def test_recover_connectors_links_endpoints_to_the_nearest_elements():
    conns = L.recover_connectors([seg("9", 1.05, 0.5, 2.95, 0.5, "TCP 443")], [A, B], page="P1")
    assert conns == [{"from_id": "1", "from": "Alpha", "to_id": "2", "to": "Beta", "label": "TCP 443",
                      "page": "P1", "recovered": "geometry", "match_distance": 0.05}]


def test_recover_connectors_drops_unresolvable_self_and_duplicate_links():
    segs = [seg("9", 0.5, 0.5, 3.5, 0.5),          # A -> B
            seg("10", 0.6, 0.6, 3.6, 0.6),         # the same pair again -> deduped
            seg("11", 0.2, 0.2, 0.8, 0.8),         # both ends on A -> self-link, dropped
            seg("12", 0.5, 0.5, 40.0, 40.0)]       # far end matches nothing -> dropped
    conns = L.recover_connectors(segs, [A, B], page="P1")
    assert [(c["from_id"], c["to_id"]) for c in conns] == [("1", "2")]


def test_recover_connectors_keeps_a_labelled_duplicate_over_a_bare_one():
    segs = [seg("9", 0.5, 0.5, 3.5, 0.5), seg("10", 0.5, 0.5, 3.5, 0.5, "syncs")]
    assert [c["label"] for c in L.recover_connectors(segs, [A, B], page="P")] == ["syncs"]


def test_recover_connectors_tolerance_is_relative_to_the_element_size():
    far = [seg("9", -1.5, 0.5, 5.5, 0.5)]           # each end 1.5 boxes away from A / B
    assert L.recover_connectors(far, [A, B], page="P") == []                       # factor 1.0 -> too far
    assert len(L.recover_connectors(far, [A, B], page="P", tolerance_factor=2.0)) == 1


def test_recover_connectors_without_elements_or_segments_is_empty():
    assert L.recover_connectors([], [A, B], page="P") == []
    assert L.recover_connectors([seg("9", 0, 0, 1, 1)], [], page="P") == []


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f(); print("ok", _n)
    print("ALL TESTS PASSED")
