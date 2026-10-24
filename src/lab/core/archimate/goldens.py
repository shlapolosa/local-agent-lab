"""GOLDEN layout fixtures — what the engine draws for a spec, as files a port reproduces byte for byte
(FR-11, user decision 24 Oct 2026). A channel that ports the deterministic half of the engine (view
composition, layout, routing, ids, Exchange XML) proves itself against these, and a change to the layout
shows up here as a diff — `tests/governance/test_archimate_goldens_are_current.py` fails until the
goldens are re-rendered and `spec_schema.VERSION` is bumped.

Per spec: `layout.json` (every view: canvas, nodes x/y/w/h with their parent, connections with every
point), `model.archimate.xml` (the Open Group Model Exchange file) and one `<view>.svg` per view.

WHAT A PORT MUST MIRROR, found by reading engine.py (no randomness, clock or uuid in the layout):
  * ROUNDING — Python's round() is round-half-to-EVEN (2.5 -> 2, 3.5 -> 4), applied to x positions,
    canvas width, row y offsets and every emitted coordinate. JS Math.round is half-UP: mirror the
    banker's rule or coordinates drift by one pixel on exact halves.
  * ORDER — dicts iterate in insertion order: nodes in placement order, connections in the order the
    model's relations were declared (auto_edges walks `relations`), views in declaration order with the
    standard catalogue after the explicit views. Sorts are STABLE (Python's sort is stable; so is JS
    Array.prototype.sort since ES2019).
  * STANDARD VIEWS place their elements in sorted(id) order — code-point order of the id strings.
    JS's default sort compares UTF-16 code units, which differs only for characters outside the BMP;
    compare with a code-point comparator to be exact.
  * SETS — the only set in the layout path (`layer_view`'s selection) is consumed through sorted(), so
    nothing depends on hash order; PYTHONHASHSEED does not change the output (tested).
  * FLOATS — barycenters and port fractions are IEEE-754 doubles in both languages; the same operations
    in the same order give the same values.
"""
from __future__ import annotations

import json

from lab.core.archimate.engine import from_spec

__all__ = ["render"]


def _pt(v) -> int:
    return round(v)


def _layout(model) -> dict:
    views = []
    for v in model.views:
        views.append({
            "id": v.vid, "title": v.title, "canvas": {"w": v.canvas_w, "h": v.canvas_h},
            "nodes": [{"id": e, "x": _pt(v.pos[e][0]), "y": _pt(v.pos[e][1]), "w": n["w"], "h": n["h"],
                       "parent": n["parent"], "container": n["container"], "icon": n["icon"]}
                      for e, n in v.nodes.items()],
            "connections": [{"k": ei["k"], "relation": ei["rid"], "src": ei["s"], "tgt": ei["t"],
                             "points": [[_pt(x), _pt(y)] for x, y in ei["pts"]]} for ei in v._E],
        })
    return {"model": model.mid, "views": views}


def render(spec: dict) -> dict[str, str]:
    """{filename: text} for one spec — deterministic, no I/O. Strict: a layout-invariant violation
    raises, because a golden that breaks the engine's own rules would teach a port the wrong thing."""
    model = from_spec(spec)
    xml = model.to_xml(strict=True)                  # lays out every view
    files = {"layout.json": json.dumps(_layout(model), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
             "model.archimate.xml": xml if xml.endswith("\n") else xml + "\n"}
    for v in model.views:
        files[f"{v.vid}.svg"] = v.to_svg()
    return files
