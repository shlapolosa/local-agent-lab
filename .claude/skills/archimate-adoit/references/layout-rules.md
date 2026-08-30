# Layout Ruleset (engine spec)

What `scripts/archimate_engine.py` enforces and why. Adapted from the health-service-idp
consolidated ruleset, extended with the channel-routing ideas from its C4 engine. You rarely need
to fight these rules — when a view looks wrong, the fix is almost always better *modelling*
(missing relationship, wrong relationship direction, missing container), not manual coordinates.

## Vertical order (layer preservation)

- **A1 Layer bands**: Motivation → Strategy → Business → Application → Technology/Physical →
  Implementation, top→down. A view spanning one layer has one band; never interleave layers.
- **A2 Aspect rows within a band** (top→down): Service → Interface → Behaviour → Active structure
  → Passive structure. Services are the offer, so they sit above the components that realize
  them; data sinks to the bottom of the band.
- **A4 Dependency beats aspect** (automatic): whatever is *served or realized* floats above its
  server/realizer. This lifts consuming actors/hosts to the top — the canonical "Customer on
  top" layered reading. Pin a node with `rank=` only when you deliberately want to override.

## Horizontal order & spacing (the "drawn by someone careful" rules)

- **B1**: within a row, declared order first, then barycenter sweeps cut edge crossings.
- **C-equal**: ONE `HGAP` between all siblings in a row; every row centred on the widest row;
  ONE `LANE_SP` between all parallel connector lanes; ports fanned at equal fractions of the box
  edge. Uniform spacing everywhere is what makes generated output look hand-finished — do not
  introduce per-node tweaks.

## Routing (orthogonal, parallel, equally spaced)

- **E1 Orthogonal only** — horizontal/vertical segments, never diagonal.
- **E-channel**: all horizontal runs between two rows share a *channel* — a stack of lanes with
  equal `LANE_SP` spacing, centred in the row gap. Runs share a lane only when their x-extents
  don't overlap (min clearance `MIN_SEP`), so parallel lines stay parallel and never merge.
- **E-stub**: every connector leaves its box straight for ≥ `STUB` px before any bend.
- **E-fan**: connectors sharing a box edge get distinct, equally spaced anchor points, sorted by
  where the other end is — no two lines depart from the same point, no crossings at the box edge.
- **E-snap**: a near-aligned adjacent-row edge (< `SNAP` px offset) snaps to one straight
  vertical — the ideal connector.
- **E-gutter**: edges spanning more than one row gap route through side gutters (equally spaced
  columns outside the content) instead of threading between boxes.

## Containers & interfaces

- **D0 Prefer drawn relationships over nesting.** Embedding an element inside another hides the
  relationship the nesting stands for, and the mapping views live off visible relationships.
  Default: no containers. Reserve nesting for genuine co-location (middleware inside its host)
  where a drawn line would be pure clutter — the model still carries the explicit relationship.
- **D1**: *when* nesting is used, the Composition/Aggregation it depicts is not additionally
  drawn as a line (`auto_edges()` handles this).
- **D3**: only leaf boxes are obstacles; a line may enter a container to reach a child.
- **Interfaces render as icons** (30×30 square nodes → symbol form in ADOIT/Archi), sitting in
  their own sub-row directly above the components that expose them.

## Hard invariants (render fails loudly / reports violations)

- **H1** no two leaf boxes overlap.
- **H2** no connector segment crosses a leaf box it doesn't terminate on.
- **H3** every connector ≥ minimum length (no stubby illegible lines).
- **H4** every Serving/Realization points upward on the canvas.
- **H-ortho** no diagonal segments.

`Model.to_xml(strict=True)` (the default) raises on any violation. When that happens, read the
violation list: H4 usually means a relationship's direction is modelled backwards; H1/H2 in
practice mean two nodes were force-ranked into an impossible arrangement with `rank=`.
