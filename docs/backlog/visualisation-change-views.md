# Visualisation: change views and impact heatmaps — BACKLOG (not dropped, for later)

**Status:** parked on 24 Oct 2026, at the user's direction: "as a start just stick to the views
visio_to_archimate produces today". The work is preserved as a patch:
`docs/backlog/visualisation-change-views.patch`.
- Base: `arch/to-be-seam` @ 5b75e4c.
- Apply with `git apply docs/backlog/visualisation-change-views.patch`.
- Its tests pass on that base (582 across core/archimate, core/usecase and the golden/import
  governance tests), and the existing goldens are unchanged.

## What the patch does

- **`lab.core.archimate.impact` is the ONE impact vocabulary and colour scale.** It is exported as
  `lab.core.archimate.CHANGES` and `CAPABILITY_STATUSES`.
- **`engine.from_spec(spec, changes=None)`:**
  - `changes = {element_id: status}` colours every view by change, in both the Exchange XML fill and
    the SVG. The SVG gets a legend, and removed elements are drawn dashed.
  - It adds two views after the standard ones:
    - `as-is` = consumed + updated + removed
    - `to-be` = consumed + updated + new
  - Unknown element ids or statuses are refused by name. An element with no status counts as
    `consumed`.
  - With no `changes`, output is byte-identical to before.
- **The CAFÉ heatmap colours** (`lab.core.usecase.views.common.FILL/EDGE`) now come from the same
  scale. Their values are unchanged.

## Decisions (user, 24 Oct 2026)

- **One vocabulary, in this order:**
  - `CHANGES = ("new", "updated", "consumed", "removed")` for elements.
  - Capabilities use the same words plus `missing`: `("new", "updated", "consumed", "missing")`.
  - This is a shared contract: intake imports it, and the order is pinned by a test, which is a
    deliberate parity exception.
- **One colour scale with the CAFÉ heatmaps:** green new, amber consumed/updated (updated a darker
  shade on element views), red missing (capabilities only), grey removed (also dashed).
- **`changes` travels BESIDE the spec.** `contracts/archimate-spec.schema.json` stays at 1.0.0, so
  the channels that vendor it are unaffected.
- **Heatmaps come from the modelling envelope's M-8 references:** `references.capabilities[]` /
  `realisations[]`, each with element_id, map, map_version, capability_id and status. The rendering
  goes through the existing CAFÉ renderers (`semantic_view_capabilities` / `_realisations`), under
  the run's pin.
- **Intake's M-10 carries the `changes` map** in the envelope.

## Unfinished

- **Not threaded through adoit-mcp yet:** `archimate_render(…, changes=…)` and `_render_model`.
- **No mapper yet** from envelope references to heatmap inputs, and no semantic view tool accepting
  that shape.
- **No golden yet** for a spec with `changes` (e.g. `contracts/goldens/specs/change-impact.json`),
  and no contract bumps (ea-tools 1.2.0, semantic-tools if a signature changes).
- **No docs** in `docs/features/ea.md` ("Visualisation contract").
- **Re-check the colours** against the dataviz palette guidance before shipping.
