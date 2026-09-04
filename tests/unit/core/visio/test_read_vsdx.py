"""visio-reader/scripts/read_vsdx — page selection, multi-page enumeration, connector endpoint
resolution (Begin/End, order-of-appearance fallback, dangling ends), text-less shapes, Lucidchart
type_hint evidence and the CLI. Offline: every fixture is a tiny OOXML .vsdx zipped IN the test.
Run: .venv/bin/python tests/unit/core/visio/test_read_vsdx.py   (also pytest-compatible)"""
import io
import json
import os
import runpy
import sys
import tempfile
import zipfile
from contextlib import redirect_stdout
from xml.sax.saxutils import escape, quoteattr

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
SCRIPTS = os.path.join(ROOT, "src", "lab", "core", "visio")
SCRIPT = os.path.join(SCRIPTS, "read_vsdx.py")

from lab.core.visio import read_vsdx as R  # noqa: E402

NS = "http://schemas.microsoft.com/office/visio/2012/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


# ---------------------------------------------------------------- minimal OOXML .vsdx authoring
def shape(sid, text, master="Rectangle"):
    """A 2-D element shape. text=None -> no <Text> element at all (a text-less shape)."""
    m = quoteattr(master)
    cells = '<Cell N="PinX" V="1"/><Cell N="PinY" V="1"/><Cell N="Width" V="1"/><Cell N="Height" V="1"/>'
    txt = f"<Text>{escape(text)}</Text>" if text is not None else ""
    return f'<Shape ID="{sid}" NameU={m} Name={m} Type="Shape">{cells}{txt}</Shape>'


def connector(sid, label=""):
    cells = '<Cell N="BeginX" V="0"/><Cell N="BeginY" V="0"/><Cell N="EndX" V="1"/><Cell N="EndY" V="1"/>'
    txt = f"<Text>{escape(label)}</Text>" if label else "<Text/>"
    return f'<Shape ID="{sid}" NameU="Dynamic connector" Name="Dynamic connector" Type="Shape">{cells}{txt}</Shape>'


def connect(conn_id, to_id, cell):
    """One <Connect> row: cell is 'BeginX' | 'EndX' | anything else (unlabelled end)."""
    return f'<Connect FromSheet="{conn_id}" FromCell="{cell}" FromPart="9" ToSheet="{to_id}" ToCell="PinX" ToPart="3"/>'


def page_xml(shapes, connects):
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<PageContents xmlns="{NS}" xml:space="preserve">'
            f'<Shapes>{"".join(shapes)}</Shapes><Connects>{"".join(connects)}</Connects></PageContents>')


def write_vsdx(path, pages):
    """pages: [(name, page_xml)] -> a .vsdx the `vsdx` library opens like a genuine Visio file."""
    overrides = "".join(f'<Override PartName="/visio/pages/page{i + 1}.xml" ContentType="application/vnd.ms-visio.page+xml"/>'
                        for i in range(len(pages)))
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/visio/document.xml" ContentType="application/vnd.ms-visio.drawing.main+xml"/>'
          '<Override PartName="/visio/pages/pages.xml" ContentType="application/vnd.ms-visio.pages+xml"/>'
          f'{overrides}'
          '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
          '</Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/document" Target="visio/document.xml"/>'
                 '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
                 '</Relationships>')
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<VisioDocument xmlns="{NS}" xmlns:r="{RNS}" '
                f'xml:space="preserve"><DocumentSettings/><Colors/><FaceNames/><StyleSheets/></VisioDocument>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/pages" Target="pages/pages.xml"/>'
                '</Relationships>')
    page_items = "".join(f'<Page ID="{i}" NameU={quoteattr(n)} Name={quoteattr(n)}><PageSheet/><Rel r:id="rId{i + 1}"/></Page>'
                         for i, (n, _) in enumerate(pages))
    pages_part = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Pages xmlns="{NS}" xmlns:r="{RNS}" '
                  f'xml:space="preserve">{page_items}</Pages>')
    pages_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                  '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                  + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.microsoft.com/visio/2010/relationships/page" '
                            f'Target="page{i + 1}.xml"/>' for i in range(len(pages))) + '</Relationships>')
    app = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
           '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
           f'<Application>Microsoft Visio</Application><Pages>{len(pages)}</Pages></Properties>')
    parts = {"[Content_Types].xml": ct, "_rels/.rels": root_rels, "docProps/app.xml": app,
             "visio/document.xml": document, "visio/_rels/document.xml.rels": doc_rels,
             "visio/pages/pages.xml": pages_part, "visio/pages/_rels/pages.xml.rels": pages_rels}
    for i, (_, px) in enumerate(pages):
        parts[f"visio/pages/page{i + 1}.xml"] = px
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return path


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
