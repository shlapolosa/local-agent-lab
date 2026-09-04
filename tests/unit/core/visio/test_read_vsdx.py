"""src/lab/core/visio/read_vsdx — page selection, multi-page enumeration, connector endpoint
resolution (Begin/End, order-of-appearance fallback, dangling ends), text-less shapes, Lucidchart
type_hint evidence, GEOMETRIC connector recovery for a Lucidchart export (no <Connects> at all) and
the CLI. Offline: every fixture is a tiny OOXML .vsdx zipped IN the test.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/core/visio/test_read_vsdx.py"""
import io
import json
import os
import runpy
import sys
import tempfile
import zipfile
from contextlib import redirect_stdout

import pytest
from xml.sax.saxutils import escape, quoteattr

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
SCRIPTS = os.path.join(ROOT, "src", "lab", "core", "visio")
SCRIPT = os.path.join(SCRIPTS, "read_vsdx.py")

from fixtures.vsdx import boxed, connect, connector, lucid_line, page_xml, shape, write_vsdx  # noqa: E402

from lab.core.visio import read_vsdx as R  # noqa: E402

NS = "http://schemas.microsoft.com/office/visio/2012/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


# OOXML authoring lives in tests/fixtures/vsdx.py — shared with the renderer's integration test
def fixture(tmp):
    """Page A: 3 captioned shapes, 1 text-less shape, 4 connectors:
         c10 Begin->1 End->2 (labelled, resolved)   c11 unlabelled cells, 2 rows (order fallback)
         c12 Begin only (dangling -> dropped)        c13 End->99 Begin->1 (99 absent -> to=None)
       Page B: 1 shape, Lucidchart-style masters (type_hint evidence)."""
    a = page_xml(
        [shape(1, "Gateway", "Component"), shape(2, "Ledger", "Data Store"), shape(3, "Portal"),
         shape(4, None), connector(10, "routes"), connector(11), connector(12, "dangling"), connector(13)],
        [connect(10, 1, "BeginX"), connect(10, 2, "EndX"),
         connect(11, 3, "Foo"), connect(11, 1, "Bar"),
         connect(12, 1, "BeginX"),
         connect(13, 99, "EndX"), connect(13, 1, "BeginX")])
    b = page_xml([shape(1, "VM", "com.lucidchart.VirtualMachineAzure2021.109"), shape(2, "ER link", "ExpressRoute")], [])
    return write_vsdx(os.path.join(tmp, "two-pages.vsdx"), [("Page A", a), ("Page B", b)])


# ---------------------------------------------------------------- tests
def test_all_pages_shapes_connectors_and_hints():
    with tempfile.TemporaryDirectory() as tmp:
        out = R.read_vsdx(fixture(tmp))
    assert out["file"] == "two-pages.vsdx" and out["page"] is None
    assert out["pages"] == ["Page A", "Page B"]
    assert out["lucidchart"] is True                         # Page B carries a com.lucidchart.* master
    by_text = {s["text"]: s for s in out["shapes"]}
    assert set(by_text) == {"Gateway", "Ledger", "Portal", "VM", "ER link"}   # text-less shape 4 dropped
    assert by_text["Gateway"]["master"] == "Component" and by_text["Gateway"]["type_hint"] is None
    assert by_text["Gateway"]["page"] == "Page A" and by_text["Gateway"]["id"] == "1"
    assert by_text["VM"]["type_hint"] == "Node"
    assert by_text["ER link"]["type_hint"] == "CommunicationNetwork"   # bare child master, trusted in a Lucidchart file
    conns = {(c["from_id"], c["to_id"]): c for c in out["connectors"]}
    assert set(conns) == {("1", "2"), ("3", "1"), ("1", "99")}, conns   # c12 (Begin only) dropped
    assert conns[("1", "2")] == {"from_id": "1", "from": "Gateway", "to_id": "2", "to": "Ledger",
                                 "label": "routes", "page": "Page A"}
    assert conns[("3", "1")]["from"] == "Portal" and conns[("3", "1")]["label"] == ""   # order-of-appearance fallback
    assert conns[("1", "99")]["to"] is None and conns[("1", "99")]["from"] == "Gateway"


def test_page_selector_hit_is_case_and_space_insensitive():
    with tempfile.TemporaryDirectory() as tmp:
        path = fixture(tmp)
        out = R.read_vsdx(path, page="  page b ")
    assert out["page"] == "  page b " and out["pages"] == ["Page A", "Page B"]   # every page still enumerated
    assert {s["text"] for s in out["shapes"]} == {"VM", "ER link"}
    assert out["connectors"] == [] and all(s["page"] == "Page B" for s in out["shapes"])


def test_page_selector_miss_parses_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        out = R.read_vsdx(fixture(tmp), page="Page Z")
    assert out["pages"] == ["Page A", "Page B"] and out["shapes"] == [] and out["connectors"] == []
    assert out["lucidchart"] is True                         # the pre-pass is file-wide, not page-scoped


def test_native_file_has_no_lucidchart_evidence():
    with tempfile.TemporaryDirectory() as tmp:
        path = write_vsdx(os.path.join(tmp, "native.vsdx"),
                          [("Only", page_xml([shape(1, "DB", "Database.70"), shape(2, "Azure SQL", "Microsoft Azure SQL Database")], []))])
        out = R.read_vsdx(path)
    hints = {s["text"]: s["type_hint"] for s in out["shapes"]}
    assert out["lucidchart"] is False
    assert hints == {"DB": None, "Azure SQL": "DataObject"}    # generic native stays untyped; Azure-branded is evidence


def test_page_match_and_helper_fallbacks():
    assert R._page_match("Page-1", None) and R._page_match(" page-1 ", "PAGE-1") and not R._page_match(None, "x")

    class Broken:
        @property
        def text(self):
            raise RuntimeError("no text")

        @property
        def master_shape(self):
            raise RuntimeError("no master")

    class Plain:
        text = "  hello  "
        master_shape = type("M", (), {"text": None, "name": "Stencil"})()

    assert R._txt(Broken()) == "" and R._master(Broken()) is None
    assert R._txt(Plain()) == "hello" and R._master(Plain()) == "Stencil"


# ---------------------------------------------------------------- Lucidchart geometric recovery
def lucid_fixture(tmp):
    """A Lucidchart export in miniature: NO <Connects> at all, three typed icons (one of them NESTED
    inside a grouping block, so absolute coordinates need the group offset), and three lines —
       L20 Portal -> DB (labelled, both ends just OUTSIDE the boxes)
       L21 DB -> Nested VM (its end lands inside BOTH the grouping block and the nested icon:
                            the smaller box must win, which needs the group offset folded in)
       L22 into nothing (dropped).
    """
    nested = boxed(4, "Nested VM", "com.lucidchart.VirtualMachineAzure2021.4", 1.0, 0.0, 1.0, 1.0)
    shapes = [
        boxed(1, "Portal", "com.lucidchart.WebAppAzure2021.1", 0.0, 0.0),
        boxed(2, "DB", "com.lucidchart.SqlDatabaseAzure2021.2", 4.0, 0.0),
        boxed(3, "Zone", "com.lucidchart.FreehandBlock.3", 8.0, 0.0, 3.0, 3.0, children=nested),
        lucid_line(20, 1.05, 0.5, 3.95, 0.5, "writes"),
        lucid_line(21, 5.05, 0.5, 9.5, 0.5),
        lucid_line(22, 0.5, 0.5, 40.0, 40.0),
    ]
    return write_vsdx(os.path.join(tmp, "lucid.vsdx"), [("Cloud", page_xml(shapes, []))])


def test_lucidchart_lines_become_connectors_and_are_not_elements():
    with tempfile.TemporaryDirectory() as tmp:
        out = R.read_vsdx(lucid_fixture(tmp))
    assert out["lucidchart"] is True
    # the labelled line shape ("writes") is a CONNECTOR, never an element
    assert {s["text"] for s in out["shapes"]} == {"Portal", "DB", "Zone", "Nested VM"}
    pairs = {(c["from"], c["to"]): c for c in out["connectors"]}
    assert set(pairs) == {("Portal", "DB"), ("DB", "Nested VM")}
    assert pairs[("Portal", "DB")]["label"] == "writes"
    # provenance: every recovered link says so, and how tight the geometric match was
    assert all(c["recovered"] == "geometry" and c["match_distance"] <= 0.05 for c in pairs.values())
    assert all(c["page"] == "Cloud" for c in pairs.values())


def test_nested_shape_matches_on_absolute_page_coordinates():
    """The nested VM sits at 8+1=9.0..10.0 absolute, inside the Zone block at 8.0..11.0. A line
    ending at 9.5 is inside BOTH; the smaller box wins, and it is only AT 9.5 because the group's
    offset was folded into the child's box (locally the child sits at 1.0)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = R.read_vsdx(lucid_fixture(tmp))
    nested = [c for c in out["connectors"] if c["to"] == "Nested VM"]
    assert len(nested) == 1 and nested[0]["from"] == "DB"


def test_the_parse_reports_what_the_recovery_could_not_match():
    """A partial recovery must never read like a sparse diagram: the parse carries the counts."""
    with tempfile.TemporaryDirectory() as tmp:
        out = R.read_vsdx(lucid_fixture(tmp))
    assert out["recovery"] == {"lines": 3, "recovered": 2, "unmatched_endpoint": 1,
                               "self_link": 0, "duplicate": 0, "skipped_transformed_groups": 0}


def test_a_native_parse_carries_no_recovery_key_at_all():
    with tempfile.TemporaryDirectory() as tmp:
        px = page_xml([boxed(1, "A", "Rectangle", 0.0, 0.0)], [])
        out = R.read_vsdx(write_vsdx(os.path.join(tmp, "native.vsdx"), [("P", px)]))
    assert "recovery" not in out


def test_a_rotated_group_is_skipped_rather_than_mis_placed():
    """The child-origin formula only holds for an unrotated group. A rotated one would still match
    SOME endpoint and emit a confidently WRONG relation — so its subtree is dropped and counted."""
    with tempfile.TemporaryDirectory() as tmp:
        nested = boxed(4, "Nested VM", "com.lucidchart.VirtualMachineAzure2021.4", 1.0, 0.0, 1.0, 1.0)
        shapes = [boxed(1, "Portal", "com.lucidchart.WebAppAzure2021.1", 0.0, 0.0),
                  boxed(3, "Zone", "com.lucidchart.FreehandBlock.3", 8.0, 0.0, 3.0, 3.0,
                        children=nested, angle=1.5708),
                  lucid_line(20, 0.5, 0.5, 9.5, 0.5)]
        out = R.read_vsdx(write_vsdx(os.path.join(tmp, "rot.vsdx"), [("P", page_xml(shapes, []))]))
    assert out["recovery"]["skipped_transformed_groups"] == 1
    assert out["recovery"]["unmatched_endpoint"] == 1 and out["connectors"] == []
    assert "Nested VM" in {s["text"] for s in out["shapes"]}   # still REPORTED, just not matchable


def test_the_same_pair_on_two_pages_is_recovered_on_BOTH():
    """Shape ids repeat across pages of one workbook (the Sahatna pages are near-copies), so the
    native-duplicate filter must be scoped to the page — a file-wide one drops real links."""
    with tempfile.TemporaryDirectory() as tmp:
        def page():
            return page_xml([boxed(1, "Portal", "com.lucidchart.WebAppAzure2021.1", 0.0, 0.0),
                             boxed(2, "DB", "com.lucidchart.SqlDatabaseAzure2021.2", 4.0, 0.0),
                             lucid_line(20, 1.05, 0.5, 3.95, 0.5)], [])
        out = R.read_vsdx(write_vsdx(os.path.join(tmp, "twin.vsdx"), [("Prod", page()), ("Dev", page())]))
    assert [(c["page"], c["from"], c["to"]) for c in out["connectors"]] == [
        ("Prod", "Portal", "DB"), ("Dev", "Portal", "DB")]
    assert out["recovery"]["recovered"] == 2 and out["recovery"]["duplicate"] == 0


def test_recovery_tolerance_is_configurable_and_can_reject_everything():
    with tempfile.TemporaryDirectory() as tmp:
        out = R.read_vsdx(lucid_fixture(tmp), tolerance_factor=0.0)
    assert out["connectors"] == []                       # nothing within a zero tolerance
    assert {s["text"] for s in out["shapes"]} == {"Portal", "DB", "Zone", "Nested VM"}   # lines still not elements


def test_native_connectors_win_over_a_recovered_duplicate():
    """A Lucidchart file that ALSO has a native <Connect> for a pair keeps the native connector only."""
    with tempfile.TemporaryDirectory() as tmp:
        shapes = [boxed(1, "Portal", "com.lucidchart.WebAppAzure2021.1", 0.0, 0.0),
                  boxed(2, "DB", "com.lucidchart.SqlDatabaseAzure2021.2", 4.0, 0.0),
                  lucid_line(20, 1.05, 0.5, 3.95, 0.5, "geometric")]
        px = page_xml(shapes, [connect(20, 1, "BeginX"), connect(20, 2, "EndX")])
        out = R.read_vsdx(write_vsdx(os.path.join(tmp, "mixed.vsdx"), [("P", px)]))
    assert len(out["connectors"]) == 1
    assert out["connectors"][0]["label"] == "geometric" and "recovered" not in out["connectors"][0]


def test_a_native_file_is_never_geometrically_recovered():
    """No Lucidchart evidence -> the second pass does not run, and behaviour is byte-identical."""
    with tempfile.TemporaryDirectory() as tmp:
        px = page_xml([boxed(1, "A", "Rectangle", 0.0, 0.0), boxed(2, "B", "Rectangle", 4.0, 0.0),
                       connector(20, "unlinked")], [])
        out = R.read_vsdx(write_vsdx(os.path.join(tmp, "native.vsdx"), [("P", px)]))
    assert out["lucidchart"] is False and out["connectors"] == []
    assert {s["text"] for s in out["shapes"]} == {"A", "B", "unlinked"}


def test_a_line_missing_endpoint_geometry_is_skipped_not_guessed():
    """A `com.lucidchart.Line.*` shape with no End cells carries no endpoint to match — it is
    dropped from the recovery (and, having no geometry, is not an element box either)."""
    with tempfile.TemporaryDirectory() as tmp:
        broken = ('<Shape ID="20" NameU="com.lucidchart.Line.20" Name="com.lucidchart.Line.20" Type="Shape">'
                  '<Cell N="BeginX" V="1.05"/><Cell N="BeginY" V="0.5"/><Text>half a line</Text></Shape>')
        px = page_xml([boxed(1, "Portal", "com.lucidchart.WebAppAzure2021.1", 0.0, 0.0),
                       boxed(2, "DB", "com.lucidchart.SqlDatabaseAzure2021.2", 4.0, 0.0), broken], [])
        out = R.read_vsdx(write_vsdx(os.path.join(tmp, "half.vsdx"), [("P", px)]))
    assert out["connectors"] == []
    assert {s["text"] for s in out["shapes"]} == {"Portal", "DB", "half a line"}


def test_page_index_resolves_a_page_name_to_its_position():
    names = ["secure-baseline", "sahatna-hld", "VBackground-1"]
    assert R.page_index(names, None) == 0                      # no selector -> the first page
    assert R.page_index(names, " SAHATNA-HLD ") == 1           # same case/space rules as the parser
    assert R.page_index(names, "VBackground-1") == 2
    with pytest.raises(ValueError, match="no page named"):
        R.page_index(names, "Nope")


def test_page_names_lists_every_drawable_page():
    with tempfile.TemporaryDirectory() as tmp:
        assert R.page_names(fixture(tmp)) == ["Page A", "Page B"]


def test_cell_reader_tolerates_missing_and_unparsable_cells():
    class NoCell:
        def cell_value(self, name):
            raise RuntimeError("no such cell")

    class Blank:
        def cell_value(self, name):
            return {"PinX": "", "Width": "notanumber"}.get(name)

    assert R._cellf(NoCell(), "PinX") is None
    assert R._cellf(Blank(), "PinX") is None and R._cellf(Blank(), "Width") is None


def test_cli_prints_json_and_usage_error():
    with tempfile.TemporaryDirectory() as tmp:
        path = fixture(tmp)
        argv = sys.argv
        try:
            sys.argv = [SCRIPT, path]
            buf = io.StringIO()
            with redirect_stdout(buf):
                runpy.run_path(SCRIPT, run_name="__main__")
            doc = json.loads(buf.getvalue())
            assert doc["pages"] == ["Page A", "Page B"] and len(doc["shapes"]) == 5
            sys.argv = [SCRIPT]
            try:
                runpy.run_path(SCRIPT, run_name="__main__")
            except SystemExit as e:
                assert e.code == 2
            else:
                raise AssertionError("usage error must exit 2")
        finally:
            sys.argv = argv


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
