"""archimate_notation — every element type's corner icon and body shape is well-formed SVG and the
type-specific branches (service capsule, event notch, chevron, wavy edge, 3-D node, dashed grouping,
junction dot, banded objects, page-corner artifact) are visibly distinct; relationship line styles.
Run: .venv/bin/python tests/unit/core/archimate/test_notation.py   (also pytest-compatible)"""
import xml.etree.ElementTree as ET


from lab.core.archimate import engine as E
from lab.core.archimate import notation as N


def _wf(snippet):
    """Well-formed check: wrap in an <svg> root and parse."""
    return ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{snippet}</svg>')


def test_every_icon_is_well_formed_and_unique_per_drawing():
    drawn = {}
    for t in N.ICONS:
        svg = N.icon(t, 10, 20)
        assert svg, t
        root = _wf(svg)
        assert len(root) >= 1, t
        drawn.setdefault(svg, []).append(t)
    # types that deliberately share a glyph (collaboration, process, function, interaction, object)
    shared = {tuple(sorted(v)) for v in drawn.values() if len(v) > 1}
    assert ("ApplicationCollaboration", "BusinessCollaboration", "TechnologyCollaboration") in shared
    assert ("BusinessObject", "DataObject") in shared
    # derived icons extend their base glyph
    assert N.icon("Contract", 0, 0).startswith(N.icon("BusinessObject", 0, 0))
    assert N.icon("Outcome", 0, 0).startswith(N.icon("Goal", 0, 0))
    assert N.icon("Constraint", 0, 0).startswith(N.icon("Requirement", 0, 0))
    # icons are positioned relative to the anchor
    assert N.icon("Goal", 0, 0) != N.icon("Goal", 5, 5)
    # types whose shape carries the meaning have no corner icon
    for t in ("ApplicationService", "BusinessEvent", "ValueStream", "Grouping", "Junction", "ApplicationInterface"):
        assert N.icon(t, 0, 0) == "", t


def test_every_taxonomy_type_renders_a_shape():
    for t in E._TYPES:
        svg = N.shape(t, 5, 5, 100, 50, "#fff")
        root = _wf(svg)
        assert len(root) >= 1, t
        assert ('fill="#fff"' in svg) == (t not in ("Junction", "AndJunction", "OrJunction")), t   # junction = solid dot


def test_shape_branches():
    svc = N.shape("ApplicationService", 0, 0, 100, 60, "#abc")
    assert "<rect" in svc and 'rx="14"' in svc
    assert 'rx="10.0"' in N.shape("BusinessService", 0, 0, 100, 30, "#abc")     # rx = min(14, h/3)
    ev = N.shape("BusinessEvent", 0, 0, 100, 40, "#abc")
    assert "<polygon" in ev and "10.0,20.0" in ev                                 # notch = min(12, h/4)
    vs = N.shape("ValueStream", 0, 0, 100, 60, "#abc")
    assert "<polygon" in vs and "16,30.0" in vs and vs != ev                       # chevron = min(16, h/3)
    for t in ("Representation", "Deliverable"):
        assert N.shape(t, 0, 0, 100, 60, "#abc").startswith('<path d="M0,0 h100 v52 q')
    node = N.shape("Node", 0, 0, 100, 60, "#abc")
    assert node.count("<") == 3 and "<polyline" in node and "<line" in node        # 3-D box: face + two edges
    assert 'stroke-dasharray="6 4"' in N.shape("Grouping", 0, 0, 100, 60, "#abc")
    for t in ("Junction", "AndJunction", "OrJunction"):
        assert N.shape(t, 0, 0, 30, 30, "#abc") == '<circle cx="15.0" cy="15.0" r="15.0" fill="#333"/>'
    art = N.shape("Artifact", 0, 0, 100, 60, "#abc")
    assert "<polygon" in art and "<polyline" in art
    obj = N.shape("DataObject", 0, 0, 100, 60, "#abc")
    assert obj.count("<line") == 1 and 'y1="14"' in obj
    con = N.shape("Contract", 0, 0, 100, 60, "#abc")
    assert con.count("<line") == 2 and 'y1="24"' in con
    assert N.shape("ApplicationComponent", 1, 2, 3, 4, "#abc") == '<rect x="1" y="2" width="3" height="4" fill="#abc" stroke="#5c6e82"/>'
    assert N.shape("NotAType", 0, 0, 1, 1, "#abc").startswith("<rect")             # unknown -> plain box


def test_label_dy_and_rel_style():
    assert N.label_dy("DataObject") == N.label_dy("BusinessObject") == N.label_dy("Contract") == 8
    assert N.label_dy("ApplicationComponent") == N.label_dy("Artifact") == 0
    assert N.rel_style("Composition") == ("", "diaF", None)
    assert N.rel_style("Association") == ("", None, None)
    assert N.rel_style("Junction") == ("", None, "arrF")                             # not a line type -> default arrow
    _wf(N.MARKER_DEFS)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
