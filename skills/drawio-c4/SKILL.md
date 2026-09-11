---
name: drawio-c4
description: >
  Render a banded C4 solution/container architecture as an editable draw.io (mxGraph) file. Use this
  skill whenever the user asks for a solution architecture diagram, C4 container diagram, deployment
  diagram, trust-zone/layered-tier diagram, or anything they want to open and edit in draw.io /
  diagrams.net — even if they don't name a tool. Declare full-width trust-zone bands, components, and
  typed edges; the engine lays out and routes (banded mode: barycenter ordering + channel router with
  side-gutter buses; A* mode: orthogonal obstacle-avoiding). Pure Python stdlib, no dependencies. For
  CAFÉ-vocabulary reference architectures use drawio-cafe instead. Also triggered by /drawio-c4.
---

# drawio-c4

Generate **clean, banded C4 solution-architecture diagrams** as draw.io diagram-as-code. You declare the
*layers/trust-zones*, the *components* in each, and the *typed relationships*; the engine decides the
layout and routing so the result obeys hard invariants — no manual coordinate fiddling.

Companion to **archimate-view** (which targets ArchiMate Model Exchange XML). Use **drawio-c4** when the
ask is a **C4 container / solution / deployment** diagram in the banded style (trust boundaries, gateway
tiers, persistence, external partners, platform services), editable in draw.io.

## What the engine guarantees
- **Banded layout** — full-width zones stacked top→down (auto-stacked by height); components in centred
  rows per band (multiple rows per band supported via `row=`).
- **Orthogonal routing (A*)** that **never crosses a component box** and keeps clearance off borders.
- **No diagonals; no trunking** — connectors are vertical/horizontal, meet boxes at **top/bottom-centre**,
  each long run gets its own lane.
- **Vertical stub rule** — every edge runs a short vertical before any bend (never traces a box edge).
- **Junction connectors** — a cross-band fan-in/out (many→one or one→many) collapses to a **dot** centred
  on all connected items, drawn as a **symmetric comb** (equal verticals, straight middle) where clear;
  falls back to A* for long multi-layer spans.
- **Self-check** — `render()` populates `d.violations` (H1 overlap / H2 box-crossing / H3 diagonal);
  `render(strict=True)` raises on any.

## How to use (workflow)
1. From the user's input, identify the **layers/trust-zones** (top→down), the **components** in each, and
   the **typed edges** (sync / async / cross-trust / identity — or your own keys + styles).
2. Write a short generator:
   ```python
   import sys; sys.path.insert(0, "<this skill's installed directory>")  # folder containing drawio_c4.py
   from drawio_c4 import C4Diagram
   d = C4Diagram("Title", width=1820)
   d.zone("z_client", "Client Surfaces", stroke="#D79B00", fill="#FFF6E6", height=118, comp_fill="#FFE6CC")
   d.zone("z_trust",  "PARTNER TRUST BOUNDARY", stroke="#C9A100", fill="#FBE9A0", height=46, dashed=False, center=True)
   d.component("c1", "z_client", "Name", "desc line 1\ndesc line 2", row=0)
   d.edge("c1", "c2", "sync")                         # sync|async|xtrust|identity
   d.legend([("Synchronous", "strokeColor=#1A1A1A;"), ("Async", "strokeColor=#777777;dashed=1;dashPattern=6 6;")])
   open("solution.drawio","w").write(d.render(strict=False))
   ```
3. Run it; `xmllint --noout solution.drawio` to confirm well-formed. Read `d.violations` (aim for `[]`).
   A dense diagram with a few long-span fans may leave some edges on A* (still clean) — that's fine.
4. Write the `.drawio` to `/mnt/user-data/outputs/` and present it with `present_files`; tell the user
   to open it in **https://app.diagrams.net**. Keep your generator script in `/home/claude/` — it is the
   diagram-as-code source; edit the zone/component/edge lists and re-run to regenerate. If `xmllint` is
   unavailable, validate with `python3 -c "import xml.etree.ElementTree as ET; ET.parse('f.drawio')"`.

## API (`drawio_c4.C4Diagram`)
- `C4Diagram(title, width=1820, edge_styles=None, junction_colors=None)`
- `zone(zid, label, stroke, fill, height, comp_fill=None, dashed=True, center=False)` — a full-width band.
  Use `dashed=False, center=True` for a thin trust-boundary banner.
- `component(cid, zid, title, desc="", row=0, col=None, fill=None)` — a box in a band; `row=1` adds a
  second inner row (e.g. an orchestrator/adapter row).
- `edge(s, t, kind)` — `kind` keys an entry in `edge_styles` (defaults: sync/async/xtrust/identity).
- `legend(items)` — list of `(label, mxgraph_edge_style)`.
- `render(strict=False) -> xml` — A* mode; sets `d.violations`, `d.JUN` (junctions).

## Banded mode (recommended for solution architecture)
A second, ported layout/render path that is usually the better choice for **solution / value-path**
diagrams. Same `zone()` / `component()` / `edge()` / `legend()` declarations, plus three banded-only
declarations, then `render(layout="banded")`. Bands are **uniform full-width** in declaration order
(per-zone `height` is ignored in this mode — uniform `NODEH`/`LANE` constants are used).

Banded mode uses **barycenter node ordering** (crossing reduction across bands) and a **channel
router**: ports are ordered by heading, parallel runs are packed into non-overlapping tracks per
band-gap (greedy interval colouring), and long multi-band edges are pushed into **side-gutter buses**
(vertical lanes outside the bands) so they never cut through the interior. It also draws **dotted
system boundaries** encompassing band groups, a **trust-boundary strip** in an enlarged gap, **per-band
security context** notes, **component descriptions**, and **animated async edges** (`flowAnimation=1`).

Banded-only declarations:
- `system(label, zone_ids, color="#5A5A5A")` — a dotted boundary box that **encompasses** the listed
  bands (a deployable system / trust zone). Declare several; drawn behind the bands (strokeWidth 3.5,
  dashPattern `3 7`).
- `trust_boundary(label, after_zone, fill="#FBE9A0", stroke="#C9A100")` — a gold dashed strip placed
  in an **enlarged gap AFTER** the named zone (the band immediately following gets the extra top room).
- `security(zone_id, text)` — a per-band security-context note rendered **right-aligned** in the band
  header (🔒 prefix).

Render:
- `render(layout="banded", outline_bands=True, animate_async=True, strict=False) -> xml`
  - `outline_bands=True` ⇒ band container is **border-only** (no fill), bold colored title + security
    note. `outline_bands=False` ⇒ a light **tinted fill** of the band stroke colour.
  - `animate_async=True` ⇒ every `async`-type edge carries `flowAnimation=1` (marching dashes show
    flow direction in app.diagrams.net). Set `False` to keep them static.
  - sets `d.violations` (node overlaps) and `d._animated_count`.
  - default `layout="astar"` keeps the existing A* behaviour — existing callers are unaffected.

```python
d = C4Diagram("Title", width=1500)
d.zone("z_client", "Client Surfaces", stroke="#D79B00", comp_fill="#FFE6CC")
d.zone("z_gw", "API Gateway", stroke="#3A7CA5", comp_fill="#D7E8F2")
d.component("web", "z_client", "Web App", "SPA · React")
d.component("apim", "z_gw", "Azure APIM", "JWT · rate-limit")
d.system("EDGE", ["z_client", "z_gw"], "#D79B00")
d.trust_boundary("PARTNER TRUST BOUNDARY · mTLS / OAuth2", "z_gw")
d.security("z_gw", "OIDC · JWT mint")
d.edge("web", "apim", "sync"); d.edge("apim", "web", "async")   # async -> animated
open("solution.drawio","w").write(d.render(layout="banded", outline_bands=True, animate_async=True))
```
The code block above is a runnable minimal demo.

## Notes
- The four default edge types map to: **sync** (solid black), **async** (dashed grey), **xtrust** (solid
  red, 2px), **identity** (dotted purple). Pass `edge_styles={...}` to add/override.
- Default renderer is draw.io; the same model is the source of truth — keep it in the repo next to the
  diagram.
