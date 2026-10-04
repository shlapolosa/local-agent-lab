# EA modelling — ADOIT, ArchiMate, the Visio reference workload

*Feature notes split out of the root `CLAUDE.md` on 4 Oct 2026, verbatim. Shared rules (method, quality bar, invariants, cloud shape, identity, gateway, approvals, observability) stay in the root file.*

## ADOIT MCP Server (own-built)

The ADOIT EA integration wraps the ADOIT REST API (Community Edition has no built-in MCP), built on the existing internal Python ArchiMate library (61 element types, role-based architect agents). FastMCP exposes typed create/read/update tools; validation runs against the library before any repository write. Read/query tools may be shared across processes; write tools are ACL-restricted to a dedicated EA Modeling Agent. ADOIT credentials live in `.env` (`ADOIT_USERNAME`/`ADOIT_PASSWORD`, plus `ADOIT_BASE_URL` and `ADOIT_REPO_ID`), alongside `OLLAMA_API_KEY`.

**The tenant runs ADOIT 18 (`GET /rest/2.0/version` → `productVersion 18.0.0`) but is BOC's hosted
Community Edition (`adoit-ce.boc-cloud.com`). REST *reads* work; REST *writes* are BLOCKED at the CE
edge (verified live Sep 3 2026).** Search and object read over REST work fully and power the
existing-architecture-aware step. But `POST/PATCH/DELETE /objects` return a BOC edge **block page**
("URL not available on this server") even though `OPTIONS` advertises the verbs and the same
credentials/IP read fine — it is a hosted-CE edge policy, not auth, not IP allowlist, not the request
body. So **true in-place REST writes are not available on this tenant**; the write path is human-gated
**file-import** (below). The granular REST write facade (`adoit_rest.create_object/patch_object/
delete_object/create_relation`, bodies verified against the tenant OpenAPI + BOC examples) is built but
**dormant behind `.env` `ADOIT_REST_WRITE`** (default false) — flip it only on a full/licensed ADOIT or
the Azure/Foundry target. The verified read surface (`src/lab/substrate/mcp/adoit/adoit_rest.py`):
- **Search** — `GET /rest/2.0/repos/{repo}/search?query=<url-encoded JSON>` (Basic auth). Query =
  `{"filters":[{"className":"C_APPLICATION_COMPONENT"} | {"attrName":"NAME","op":"OP_LIKE","value":"x"}],
   "scope":{"repoObjects":true,"models":true,"modObjects":true}}` — **a non-empty filter is required**
  (empty → 400). Items: `{id,name,type,artefactType(REPOSITORY_OBJECT|DIAGRAM|MODINST),metaName(C_*),
  groupId,modelId,modelName}`. Exposed as the read-only tool **`ea_search(name_like, class_name, scope, limit)`**.
- **Object detail** — `GET /rest/2.0/repos/{repo}/objects/{objId}` → attributes + relation slots
  (`{name, metaName(RC_*), targets:[{id,name,metaName,direction}]}`). Tool **`ea_object(object_id)`**.
- **Write (edge-blocked on CE)** — `OPTIONS` advertises `POST /objects` and `PATCH,DELETE /objects/{id}`,
  but the actual verbs return the CE edge block page. className/relclass maps are deterministic
  (CamelCase ↔ `C_UPPER_SNAKE`; relation ↔ `RC_UPPER_SNAKE`). The facade is ready for a write-capable tenant.

**Write path = human-gated file-import, TWO files, TWO purposes** (`ea_import_instructions`):
- **OBJECTS → Excel object-import** (the adapter's PRIVATE object-import file → `.xlsx`, `src/lab/substrate/mcp/adoit/adoit_excel.py`,
  bundled ENGLISH tenant template in `src/lab/substrate/mcp/adoit/templates/`). ADOIT's "Import objects from Excel"
  both **creates and updates** objects, matching each row on its **NAME** (found once → UPDATE in place,
  absent → CREATE, found twice → error). One sheet per element type; the generator fills the tenant's
  own template. **Relationships** are written on the source object's row in the `<Relation> (->TargetSheet)`
  column, value = target name (`;`-joined for several); ADOIT-specific roles (RACI/Vendor/Predecessor)
  are left unset. Both maps are **derived from the template at runtime** by normalized name-match
  (`_norm`) — the EN template's sheet names ARE the ArchiMate types ("Application Component", "Course of
  Action") and its relation labels ARE the ArchiMate relation names — so there is no hardcoded map to
  drift (swapping locales re-derives the sheet map; only non-English relation *labels* need `REL_ALIAS`).
  This is why object **names must stay unique** — the existing-aware step's job.
- **VIEWS → ArchiMate Model Exchange XML** (`archimate_render` → `.archimate.xml`). Imports the
  diagram/geometry. NOTE: ArchiMate import **always creates** objects in a new group — it does NOT
  match on identifier (verified: even with the native `id_<uuid>` identifier it duplicated). So it is
  the *views* path; the Excel file is what keeps objects de-duplicated and updatable. (The engine
  still emits ADOIT-native `id_<uuid>` identifiers — `_ident()` in `archimate_engine.py` — for valid
  XML and forward-compat with a tenant that does match on identifier.)

The repo already holds a real ~134-object landscape. The workflow is **existing-architecture-aware**:
a `resolve_existing` node searches ADOIT, an agent decides NEW vs UPDATE + matches BA elements to
existing object ids, the Architect **reuses those ids** (no duplicates) and folders by domain, and
the reviewer confirms update-vs-new at the approval gate; the run stages BOTH the Excel object file
and the ArchiMate views file for import.

## Architecture Modelling

Use the project skill `archimate-adoit` (`skills/archimate-adoit/`) for all ArchiMate
modelling and ADOIT export: it bundles a deterministic layout engine (orthogonal parallel
routing, layer bands, interfaces as icons), the ArchiMate 3.1 vocabulary, and the ADOIT:CE
import procedure. Keep generator scripts under `scripts/` so views are regenerable.
The engine originates from `~/Development/health-service-idp` (archi_layout.py / drawio_c4.py).

- **BA inputs = a diagram + optional requirements documents, BY REFERENCE, read ONLY through the
  gateway.** A person submits them on the review app's **Submit** mode (or `python -m
  lab.substrate.review.uploads upload <files>`): files land in the **upload store**
  (`UPLOADS_URL` — a Railway Bucket in the cloud, the Postgres artifact store locally; refs are
  `art://<id>/<name>`) and an explicit **Run** publishes a durable `workflow:requests` event
  (`src/lab/platform/workflows.py`, Redis Streams) that the long-lived `wf-visio` host
  (`src/lab/workloads/visio_to_archimate/consumer.py`) consumes, writing status/trace/approval back.
  **A workload holds NO object-store credentials**: refs are read through the gateway's
  **storage-mcp** (`src/lab/substrate/mcp/storage/server.py`, read-only: `storage_read_vsdx`,
  `storage_read_document`, `storage_get`, `storage_extract_figures`, `storage_list/info`), granted
  per team and metered/traced like any tool; the BA's spec is stored via `semantic_store_spec`.
  **Three input KINDS, and for a `.vsdx` TWO representations** — do not conflate them. A **`.vsdx`** is
  structured OOXML parsed deterministically AND (when the host can render) rasterised to a page image,
  so the BA RECONCILES structure with vision: the parse wins on element identity/text/native
  connectors, vision wins on grouping/containment and missing connectors, conflicts become
  `openQuestions`. Rendering is an OPTIONAL capability (`storage_render_vsdx`, LibreOffice + a
  rasteriser on the storage-mcp host, `SOFFICE_BIN` in `.env`): absent, the run degrades to
  structure-only AND SAYS SO in the BA message — it never fails. Only the rendered page carries an
  image, and the message names which page that is.
  **A Lucidchart export has NO `<Connects>` section at all** (verified on the real file — the old
  "empty instance geometry" note was a library limitation, not the file), but every
  `com.lucidchart.Line.*` shape carries `BeginX/Y`–`EndX/Y` in page coordinates. `lab.core.visio.geometry`
  recovers `from`/`to` by matching each endpoint to the nearest element bounding box: tolerance is
  **1.0 × the median element min-edge** (pages are inches at an arbitrary author scale, so an absolute
  length is meaningless), group offsets folded in, and rotated/flipped subtrees are SKIPPED and counted
  — a mis-placed relation survives the approval gate looking plausible, a missing one does not.
  Recovered links carry `recovered: "geometry"` + `match_distance`, and the parse carries a `recovery`
  block counting lines that yielded nothing, which the BA must raise in `openQuestions`. Measured:
  Sahatna **0 → 44 connectors, 244 → 214 shapes**; Malaffi native output byte-identical.
  A **diagram IMAGE** (png/jpg —
  no XML) is fetched by the deterministic BA node via `storage_get` and attached inline to the
  BA's message, read with vision (kimi-k3 / kimi-k2.7-code / glm-flash declare `vision` on Ollama
  Cloud; image parts pass through the gateway both as message content and as MCP ImageContent —
  verified; `supports_vision` is set in `litellm-config.yaml`); a **requirements document**
  (docx/pdf/md/txt) becomes text via `storage_read_document`, and its **embedded figures** are
  extracted server-side (`storage_extract_figures`) and attached as "figure N embedded in <doc>".
  Image sizing is enforced in ONE place (`src/lab/platform/docparse.py`): **≤1600 px** for images and
  document figures, **≤2400 px for a whole rendered page** (1600 px on a 16-inch page is ~100 dpi —
  captions unreadable, defeating the point); PNG/JPEG, <2 KB / <64 px decorations dropped, ≤8 figures/doc and documented in the `visio-reader` skill. Local
  paths still work for dev (parsed by the same helpers). Gotcha: fastmcp derives an outputSchema
  from a tool's return annotation — image-returning tools must have NONE, or clients fail with
  "outputSchema defined but no structured output returned". Requirements are evidence, not new
  boxes: a requirements-only element is added only if plainly part of THIS system (marked
  `source: requirements`), otherwise it is an `openQuestion`. Per-element **`provenance`
  `{source, representation}` is REQUIRED** by `ba_output.schema.json` and by the `[D]` gate (which
  expands the bare-string shorthand to the object form; both BA modes share one normaliser).
