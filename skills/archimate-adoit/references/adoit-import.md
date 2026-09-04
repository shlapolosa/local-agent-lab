# Importing into ADOIT

## What ADOIT does with the file

ADOIT (with the ArchiMate Application Library — the default in ADOIT:CE) imports ArchiMate
Model Exchange files as follows:

- **Elements** → objects in the **Object Catalogue**
- **Relationships** → relations between those objects
- **Views** → models in the **Model Catalogue** (layout, coordinates and bendpoints carry over)
- **Duplicates**: if a model/object of the same name exists, originals are preserved and the new
  ones land in **new groups under the same name** — imports never overwrite. Delete stale import
  groups after re-imports to avoid catalogue clutter.

## Minimum fields the file must carry

The engine emits all of these; listed here so hand-edits don't break imports:

| Node | Required |
|---|---|
| `<model>` | `identifier`, ArchiMate 3.0 namespace, `<name>` |
| `<element>` | `identifier`, `xsi:type` (exact ArchiMate type name), `<name>` (ADOIT catalogues by name) |
| `<relationship>` | `identifier`, `source`, `target`, `xsi:type` |
| `<view>` | `identifier`, `xsi:type="Diagram"`, `<name>` |
| view `<node>` | `identifier`, `elementRef`, `x`, `y`, `w`, `h` |
| `<connection>` | `identifier`, `relationshipRef`, `source`, `target` (view-node ids, not element ids) |

Identifiers must be XML NCNames — the engine prefixes everything with `id-`; keep your element
ids alphanumeric/dash/underscore. View coordinates and bendpoints must be **nonNegativeInteger**
(the engine normalizes automatically since Aug 2026). To validate before importing:
`xmllint --noout --schema archimate3_Diagram.xsd <file>` with the three XSDs
(`archimate3_Diagram/View/Model.xsd`) from opengroup.org/xsd/archimate/3.1/ — Archi enforces
this schema strictly; ADOIT is more lenient.

## Import steps (ADOIT:CE web client)

1. Log in at `https://adoit-ce.boc-cloud.com` (credentials in the project `.env`).
2. Menu → **Import/Export** → **ArchiMate Model Exchange File** (requires import permission;
   in CE this sits on the hamburger menu of the Explorer / Object Catalogue).
3. Upload the `.archimate.xml`, confirm. Elements land in the Object Catalogue, views in the
   Model Catalogue.

## Post-import checklist

- **Interfaces as icons**: the exchange format has no standard flag for box-vs-icon
  representation. The engine emits interface nodes at 30×30 (square, icon-sized), which ADOIT
  renders in symbol form. If any interface still shows as a box: select it on the view →
  representation toggle (Notebook/context menu) → **symbol/icon**. ADOIT remembers the choice
  per object across models.
- **Layout survived**: open the imported view and confirm rows/lanes match the SVG preview
  generated next to the XML. If ADOIT re-laid-out the view (some versions offer auto-layout on
  import — decline it), re-import and choose to keep geometry.
- **Colours**: the engine writes standard ArchiMate layer fills; ADOIT may apply its own notation
  styling instead. That is fine — semantics, not styling, is what must survive.

## ADOIT REST — what works and what the write path is (verified Sep 2026)

The tenant runs a full ADOIT 18 with a working REST 2.0 API (`GET /rest/2.0/version` →
`productVersion 18.0.0`). **Reads work** — `GET /repos/{repo}/search?query=<json>` (a non-empty
filter is required) and `GET /repos/{repo}/objects/{id}` — and are exposed as the read-only tools
`adoit_search` / `adoit_object`; the workflow uses them to detect existing objects and reuse their
ids. (The earlier "403 service not present" note came from a wrong-method/wrong-path probe, not
from the edition.)

**Writes are blocked at the hosted-CE edge**: `POST/PATCH/DELETE /objects` answer "URL not
available" before reaching the application. So the write path is the **two-file human import**,
each file with one purpose:

1. **Excel object file** (`adoit_excel_render` → Object Catalogue → Import objects from Excel):
   CREATES and UPDATES objects, matched by **name** (created if new, updated if present).
2. **ArchiMate Model Exchange XML** (`archimate_render` → Import/Export → ArchiMate Model Exchange
   File): imports the **views/diagrams**; reused ADOIT ids are emitted as `id_<uuid>` so the view
   references the existing objects instead of duplicating them.

Both files are staged by `adoit_request_import` and released only on a human **approve**. The
granular REST write facade (create/patch/relate/delete) exists but is **dormant behind
`ADOIT_REST_WRITE=false`**; flip it only on a licensed/self-hosted tenant (or the Azure target)
where the edge allows writes — then the same approval releases the REST changeset instead.
