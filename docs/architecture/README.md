# Architecture views — and the rule for keeping them true

Two views of the same lab, both diagram-as-code. **`var/` is git-ignored, so the rendered files live
here**; the generators live in `scripts/` and are the source of truth.

| view | what it answers | source |
|---|---|---|
| `worktree-heatmap` | what is actually BUILT, component by component | `scripts/worktree_heatmap.py` |
| `lab_cafe` | the same lab in CAFÉ A3 vocabulary — the Azure target it claims parity with | `scripts/lab_cafe.solution.json` |
| `reference-layer` | the reference corpus and the use-case intake pipeline in DETAIL — the area the reference-layer redesign touched, updated as its components land | `scripts/reference_layer_diagram.py` |

Regenerate both:

```bash
.venv/bin/python scripts/worktree_heatmap.py
.venv/bin/python skills/drawio-cafe/drawio_cafe.py --solution scripts/lab_cafe.solution.json \
    --out var/out/architecture
.venv/bin/python scripts/drawio_to_png.py var/out/architecture/worktree-heatmap.drawio
cp var/out/architecture/* docs/architecture/
```

## The colours are evidence, and that is the whole point

- **GREEN** — deployed AND exercised end to end: `deploy/railway.py substrate images` lists it on the
  current build, and something drove the real path (a live run, a governed tool call, a test that
  exercises it rather than a double).
- **AMBER** — built and reachable, with a NAMED limitation. The description says which.
- **GREY** — not built, and absent was VERIFIED rather than assumed.

A heatmap whose colours cannot be argued with is decoration. So when you move a component, edit its
`fill=` and its description **in the same line** — the colour and the reason travel together, or the
diagram becomes a picture of what somebody once hoped.

At the last regeneration: **58 green · 17 amber · 8 grey** across 83 components.

## Expanding your own area

This is a HIGH-LEVEL view and it will stay one — 83 components is already at the edge of readable.
Each worktree should keep its own detailed view of the area it actually touches, in its own tree,
and leave this one alone:

```
docs/architecture/<area>.drawio        the detail
docs/architecture/<area>.png
scripts/<area>_diagram.py              its generator
```

Update yours as you finish things, not at the end. The reason is the reason for the whole file: a
diagram drawn once at the start of a piece of work describes the plan, and a diagram updated as
components land describes the system. Only one of those is worth reading.

## Two rendering facts worth knowing before you copy this

**`drawio_c4` banded mode ignores per-component `fill`.** `_render_banded` builds its nodes from
`(cid, zid, title, desc)` and never reads the fill; the A* path does `f = fill or zfill[zid]`. A
heatmap in banded mode renders perfectly and means nothing. Found by counting `fillColor` in the
output XML and getting 20 where 83 were declared.

**`drawio-cafe` has no per-component fill at all.** The zone palette is fixed by the framework and
`kind` only toggles a dashed border, so status there is carried in the description text. That is a
property of CAFÉ being a closed vocabulary, not an oversight.

**PNGs are rendered by `scripts/drawio_to_png.py`** — there is no `drawio` CLI, `rsvg-convert`,
`inkscape`, `cairosvg` or ImageMagick on this machine. It reads the mxGraph geometry directly, so it
cannot disagree with draw.io except in typography.
