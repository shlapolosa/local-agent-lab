"""Generate a genuine minimal Visio .vsdx fixture from the lab's own ArchiMate model.

The round-trip test input: `architecture/lab_model.json` (governance-plane view subset) →
a hand-authored OPC/OOXML `.vsdx` that the `vsdx` library can open like any real Visio upload
(shapes carry `<Text>`; connectors are 1-D shapes linked to endpoints via the page `<Connects>`
section, exactly as Visio writes them). The final ArchiMate output of the workflow should recover
this model — proving BA→Architect→ArchiMate fidelity.

We author the zip directly (rather than copy-from-template) so the fixture is self-contained and
schema-faithful: no dependency on a bundled template, and it forces `read_vsdx.py` to parse real
Visio XML. Usage: `.venv/bin/python -m processes.visio_to_archimate.make_sample_vsdx`
"""
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

NS = "http://schemas.microsoft.com/office/visio/2012/main"
ROOT = Path(__file__).resolve().parents[2]
LAB_MODEL = ROOT / "architecture" / "lab_model.json"
OUT = Path(__file__).resolve().parent / "visio-in" / "lab-system.vsdx"
VIEW_ID = "governance-plane"          # the subset a BA would actually receive as a Visio

# --- ArchiMate type -> a Visio master hint (what a human's stencil would label the shape).
# The BA agent (not this generator) bridges master->intent; the hint is a soft signal only.
MASTER_HINT = {
    "ApplicationComponent": "Component", "ApplicationService": "Service",
    "ApplicationInterface": "Interface", "ApplicationFunction": "Function",
    "DataObject": "Data Store", "Node": "Node", "Device": "Device",
    "SystemSoftware": "System Software", "TechnologyService": "Service",
    "TechnologyInterface": "Interface", "BusinessActor": "Actor",
    "BusinessRole": "Role", "BusinessProcess": "Process", "BusinessService": "Service",
}


def _cell(n, v):
    return f'<Cell N="{n}" V="{v}"/>'


def _shape_xml(sid, name, master_hint, x, y, w=1.6, h=0.8):
    cells = "".join([_cell("PinX", x), _cell("PinY", y), _cell("Width", w),
                     _cell("Height", h), _cell("LocPinX", w / 2), _cell("LocPinY", h / 2)])
    # NameU carries the stencil/master label; Text carries the human-typed caption.
    mh = quoteattr(master_hint)
    return (f'<Shape ID="{sid}" NameU={mh} Name={mh} Type="Shape">'
            f'{cells}<Text>{escape(name)}</Text></Shape>')


def _connector_xml(sid, label, bx, by, ex, ey):
    cells = "".join([_cell("BeginX", bx), _cell("BeginY", by), _cell("EndX", ex),
                     _cell("EndY", ey), _cell("PinX", (bx + ex) / 2), _cell("PinY", (by + ey) / 2),
                     _cell("Width", abs(ex - bx) or 0.01), _cell("Height", abs(ey - by) or 0.01)])
    txt = f"<Text>{escape(label)}</Text>" if label else "<Text/>"
    return f'<Shape ID="{sid}" NameU="Dynamic connector" Name="Dynamic connector" Type="Shape">{cells}{txt}</Shape>'


def _connect_rows(conn_id, from_id, to_id):
    return (f'<Connect FromSheet="{conn_id}" FromCell="BeginX" FromPart="9" '
            f'ToSheet="{from_id}" ToCell="PinX" ToPart="3"/>'
            f'<Connect FromSheet="{conn_id}" FromCell="EndX" FromPart="12" '
            f'ToSheet="{to_id}" ToCell="PinX" ToPart="3"/>')


def build_page_xml(elements, relations):
    """elements: [{id,type,name}]  relations: [{type,src,tgt}] restricted to the subset."""
    id_to_sheet = {}
    shapes, connects = [], []
    # lay out elements on a simple grid (geometry is irrelevant to the round-trip, but valid)
    cols = 4
    for i, el in enumerate(elements):
        sheet = i + 1
        id_to_sheet[el["id"]] = sheet
        col, row = i % cols, i // cols
        x = 1.5 + col * 3.0
        y = 10.0 - row * 1.6
        hint = MASTER_HINT.get(el["type"], "Component")
        shapes.append(_shape_xml(sheet, el["name"], hint, x, y))
    # connectors after all element sheets, so ids never collide
    cid = len(elements) + 100
    for r in relations:
        s, t = id_to_sheet.get(r["src"]), id_to_sheet.get(r["tgt"])
        if not s or not t:
            continue
        shapes.append(_connector_xml(cid, r["type"], 1, 1, 2, 2))
        connects.append(_connect_rows(cid, s, t))
        cid += 1
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<PageContents xmlns="{NS}" xml:space="preserve">'
            f'<Shapes>{"".join(shapes)}</Shapes>'
            f'<Connects>{"".join(connects)}</Connects></PageContents>'), id_to_sheet


def _parts(page_xml):
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/visio/document.xml" ContentType="application/vnd.ms-visio.drawing.main+xml"/>'
          '<Override PartName="/visio/pages/pages.xml" ContentType="application/vnd.ms-visio.pages+xml"/>'
          '<Override PartName="/visio/pages/page1.xml" ContentType="application/vnd.ms-visio.page+xml"/>'
          '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
          '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
          '</Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/document" Target="visio/document.xml"/>'
                 '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/core-properties" Target="docProps/core.xml"/>'
                 '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
                 '</Relationships>')
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                f'<VisioDocument xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xml:space="preserve">'
                f'<DocumentSettings/><Colors/><FaceNames/><StyleSheets/></VisioDocument>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/pages" Target="pages/pages.xml"/>'
                '</Relationships>')
    pages = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
             f'<Pages xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xml:space="preserve">'
             f'<Page ID="0" NameU="Lab System" Name="Lab System" ViewScale="-1" ViewCenterX="5" ViewCenterY="5">'
             f'<PageSheet><Cell N="PageWidth" V="17"/><Cell N="PageHeight" V="11"/></PageSheet>'
             f'<Rel r:id="rId1"/></Page></Pages>')
    pages_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                  '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                  '<Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/page" Target="page1.xml"/>'
                  '</Relationships>')
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:title>Lab System</dc:title><dc:creator>make_sample_vsdx</dc:creator></cp:coreProperties>')
    app = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
           '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
           '<Application>Microsoft Visio</Application><Pages>1</Pages></Properties>')
    return {
        "[Content_Types].xml": ct,
        "_rels/.rels": root_rels,
        "docProps/core.xml": core,
        "docProps/app.xml": app,
        "visio/document.xml": document,
        "visio/_rels/document.xml.rels": doc_rels,
        "visio/pages/pages.xml": pages,
        "visio/pages/_rels/pages.xml.rels": pages_rels,
        "visio/pages/page1.xml": page_xml,
    }


def main():
    model = json.loads(LAB_MODEL.read_text())
    by_id = {e["id"]: e for e in model["elements"]}
    view = next(v for v in model["views"] if v["id"] == VIEW_ID)
    ids = set(view["elements"])
    elements = [by_id[i] for i in view["elements"] if i in by_id]
    relations = [r for r in model["relations"] if r["src"] in ids and r["tgt"] in ids]

    page_xml, _ = build_page_xml(elements, relations)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in _parts(page_xml).items():
            z.writestr(name, data)
    print(f"wrote {OUT}")
    print(f"  view={VIEW_ID}  shapes={len(elements)}  connectors={len(relations)}")
    return OUT


if __name__ == "__main__":
    main()
