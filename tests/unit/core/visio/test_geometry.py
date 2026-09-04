"""src/lab/core/visio/geometry.py — PURE connector recovery from line geometry: endpoint -> nearest
element bounding box, the tolerance scaled to the drawing, and the `Recovery.stats` audit trail that
keeps a partial recovery from reading like a sparse diagram. Plain Box/Segment values in, connector
dicts out — no vsdx, no I/O, no vendor.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/core/visio/test_geometry.py"""
import pytest

from lab.core.visio import geometry as G


def box(i, text, x0, y0, x1, y1):
    return G.Box(id=i, text=text, x0=x0, y0=y0, x1=x1, y1=y1)


def seg(i, bx, by, ex, ey, label=""):
    return G.Segment(id=i, label=label, bx=bx, by=by, ex=ex, ey=ey)


#   A = [0,0]-[1,1]      B = [3,0]-[4,1]      C (container) = [-1,-1]-[5,2]
A, B, CONTAINER = box("1", "Alpha", 0, 0, 1, 1), box("2", "Beta", 3, 0, 4, 1), box("3", "Zone", -1, -1, 5, 2)


def test_box_distance_is_zero_inside_and_euclidean_outside():
    assert G.box_distance(0.5, 0.5, A) == 0.0            # inside
    assert G.box_distance(1.0, 0.5, A) == 0.0            # on the edge
    assert G.box_distance(2.0, 0.5, A) == 1.0            # straight out to the right
    assert G.box_distance(4.0, 4.0, A) == pytest.approx((3 ** 2 + 3 ** 2) ** 0.5)   # diagonal corner


def test_median_min_edge_scales_the_tolerance_to_the_drawing():
    assert G.median_min_edge([A, B]) == 1.0
    assert G.median_min_edge([]) == 0.0                  # nothing to scale to


def test_nearest_box_prefers_the_smallest_box_at_equal_distance():
    # the endpoint is inside BOTH the element and its container -> the element (smaller area) wins
    hit = G.nearest_box(0.5, 0.5, [CONTAINER, A], tolerance=1.0)
    assert hit is not None and hit[0].id == "1" and hit[1] == 0.0


def test_nearest_box_returns_none_beyond_the_tolerance():
    assert G.nearest_box(10.0, 10.0, [A, B], tolerance=1.0) is None
    assert G.nearest_box(2.0, 0.5, [A, B], tolerance=0.5) is None       # 1.0 away, tolerance 0.5
    assert G.nearest_box(2.0, 0.5, [A, B], tolerance=1.0)[0].id == "1"  # exactly at the tolerance
    assert G.nearest_box(0.5, 0.5, [], tolerance=1.0) is None


def test_recover_connectors_links_endpoints_to_the_nearest_elements():
    rec = G.recover_connectors([seg("9", 1.05, 0.5, 2.95, 0.5, "TCP 443")], [A, B], page="P1")
    assert rec.connectors == [{"from_id": "1", "from": "Alpha", "to_id": "2", "to": "Beta", "label": "TCP 443",
                      "page": "P1", "recovered": "geometry", "match_distance": 0.05}]


def test_recover_connectors_drops_unresolvable_self_and_duplicate_links():
    segs = [seg("9", 0.5, 0.5, 3.5, 0.5),          # A -> B
            seg("10", 0.6, 0.6, 3.6, 0.6),         # the same pair again -> deduped
            seg("11", 0.2, 0.2, 0.8, 0.8),         # both ends on A -> self-link, dropped
            seg("12", 0.5, 0.5, 40.0, 40.0)]       # far end matches nothing -> dropped
    rec = G.recover_connectors(segs, [A, B], page="P1")
    assert [(c["from_id"], c["to_id"]) for c in rec.connectors] == [("1", "2")]


def test_recover_connectors_keeps_a_labelled_duplicate_over_a_bare_one():
    segs = [seg("9", 0.5, 0.5, 3.5, 0.5), seg("10", 0.5, 0.5, 3.5, 0.5, "syncs")]
    assert [c["label"] for c in G.recover_connectors(segs, [A, B], page="P").connectors] == ["syncs"]


def test_recover_connectors_tolerance_is_relative_to_the_element_size():
    far = [seg("9", -1.5, 0.5, 5.5, 0.5)]           # each end 1.5 boxes away from A / B
    assert G.recover_connectors(far, [A, B], page="P").connectors == []                       # factor 1.0 -> too far
    assert len(G.recover_connectors(far, [A, B], page="P", tolerance_factor=2.0).connectors) == 1


def test_recovery_stats_count_every_line_that_yielded_no_link():
    """The audit trail: a reader must be able to tell 'few links drawn' from 'few links matched'."""
    segs = [seg("9", 0.5, 0.5, 3.5, 0.5),          # A -> B
            seg("10", 0.6, 0.6, 3.6, 0.6),         # the same pair again -> duplicate
            seg("11", 0.2, 0.2, 0.8, 0.8),         # both ends on A -> self-link
            seg("12", 0.5, 0.5, 40.0, 40.0)]       # far end matches nothing
    rec = G.recover_connectors(segs, [A, B], page="P1")
    assert len(rec.connectors) == 1
    assert rec.stats == {"lines": 4, "recovered": 1, "unmatched_endpoint": 1,
                         "self_link": 1, "duplicate": 1}


def test_recovery_with_nothing_to_match_reports_every_line_unmatched():
    rec = G.recover_connectors([seg("9", 0, 0, 1, 1)], [], page="P")
    assert rec.connectors == [] and rec.stats["lines"] == 1 and rec.stats["unmatched_endpoint"] == 1
    empty = G.recover_connectors([], [A], page="P")
    assert empty.connectors == [] and empty.stats["lines"] == 0


def test_recoveries_merge_into_a_whole_file_total():
    one = G.Recovery([{"x": 1}], {"lines": 3, "recovered": 1})
    two = G.Recovery([{"x": 2}], {"lines": 2, "recovered": 1, "self_link": 1})
    both = one.merged(two)
    assert both.connectors == [{"x": 1}, {"x": 2}]
    assert both.stats == {"lines": 5, "recovered": 2, "self_link": 1}
    assert one.stats == {"lines": 3, "recovered": 1}          # merging never mutates an operand
    assert G.Recovery().connectors == [] and G.Recovery().stats == {}
