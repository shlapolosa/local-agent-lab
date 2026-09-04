"""Minimal OOXML `.vsdx` authoring — real Visio files the `vsdx` library opens, built in-process so
every Visio test is OFFLINE and needs no binary fixture checked in. Shared (not test-to-test
imports) because both the parser tests and the renderer's host-gated integration test need a
multi-page workbook.
"""
from xml.sax.saxutils import escape, quoteattr
import zipfile

NS = "http://schemas.microsoft.com/office/visio/2012/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


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


def boxed(sid, text, master, x, y, w=1.0, h=1.0, children="", angle=0):
    """A 2-D shape placed at (x, y) with size (w, h) — bottom-left anchored (LocPin 0,0).
    `children` nests sub-shapes, whose own coordinates are RELATIVE to this shape's origin.
    `angle` rotates it, which invalidates that plain offset for the children (see M6)."""
    m = quoteattr(master)
    cells = (f'<Cell N="PinX" V="{x}"/><Cell N="PinY" V="{y}"/><Cell N="Width" V="{w}"/>'
             f'<Cell N="Height" V="{h}"/><Cell N="LocPinX" V="0"/><Cell N="LocPinY" V="0"/>'
             f'<Cell N="Angle" V="{angle}"/>')
    txt = f"<Text>{escape(text)}</Text>" if text is not None else ""
    kids = f"<Shapes>{children}</Shapes>" if children else ""
    return f'<Shape ID="{sid}" NameU={m} Name={m} Type="{"Group" if children else "Shape"}">{cells}{txt}{kids}</Shape>'


def lucid_line(sid, bx, by, ex, ey, label=""):
    """A Lucidchart line: endpoint geometry only, NO <Connect> row anywhere (that is the whole point)."""
    cells = (f'<Cell N="PinX" V="{bx}"/><Cell N="PinY" V="{by}"/><Cell N="Width" V="{ex - bx}"/>'
             f'<Cell N="Height" V="{ey - by}"/><Cell N="BeginX" V="{bx}"/><Cell N="BeginY" V="{by}"/>'
             f'<Cell N="EndX" V="{ex}"/><Cell N="EndY" V="{ey}"/>')
    txt = f"<Text>{escape(label)}</Text>" if label else "<Text/>"
    m = quoteattr(f"com.lucidchart.Line.{sid}")
    return f'<Shape ID="{sid}" NameU={m} Name={m} Type="Shape">{cells}{txt}</Shape>'


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
