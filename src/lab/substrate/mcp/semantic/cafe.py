"""The CAFÉ solution view: a draw.io (+ SVG) projection of a use-case model.

The ADAPTER over the `drawio-cafe` skill (`skills/drawio-cafe`, the same files registered in
LiteLLM and COPYed into the image), reached the only way a top-level skill module can be: its
directory on `sys.path`. That import seam is deliberate and confined to this module — nothing else
in `lab` imports a skill's engine.

Two halves, kept apart so the mapping is tested without drawing anything:
- `solution_spec(spec)` — PURE. Our ArchiMate spec -> the skill's solution spec. Draws OURS ONLY
  (`include_comps: ["none"]`): every ApplicationComponent carrying a `cafe.zone` property becomes
  a custom component in that CAFÉ zone (`gw` is the skill's `z_edge`), edges are the Serving /
  Flow / Triggering / Access relations between two placed components, and the archetype is the one
  the composition put on the model's root (`cafe.archetype`). A component without a zone (an
  incumbent found by the landscape match, a building block somebody else owns) is reported as
  `unplaced`, never guessed into a zone. No element documentation is copied into the drawing.
- `render(spec, basename)` — the skill's own pipeline, file-free: validate, build, render banded,
  post-process, and the SVG preview; returns both as text.
"""
from __future__ import annotations

import functools
import re
import sys
from typing import Any, Mapping

from lab.platform import config

__all__ = ["EDGE_KINDS", "ZONE_IDS", "catalogue", "engine", "render", "solution_spec"]

#: Corpus zone id -> the skill's zone id: every zone is `z_<id>` except the gateway, which the skill
#: calls the edge. Frozen here (and held equal to the engine's by a test) so the PURE half needs no
#: engine to run.
ZONE_IDS = {z: f"z_{z}" for z in ("exp", "cog", "knw", "mod", "too", "data", "ext",
                                  "ident", "obs", "plat")} | {"gw": "z_edge"}


@functools.lru_cache(maxsize=1)
def engine():
    """The skill's two modules, imported on FIRST USE — never at server start, so a missing or
    renamed skill directory fails the one tool that draws, not the ~25 others this server serves.
    `append`, not `insert(0)`: the skill's top-level names must not shadow an installed package."""
    skill = str(config.SKILLS_DIR / "drawio-cafe")
    if skill not in sys.path:
        sys.path.append(skill)
    try:
        import drawio_cafe, drawio_cafe_svg                         # noqa: E401  (the skill)
    except ImportError as exc:
        raise RuntimeError(f"the drawio-cafe skill is not importable from {skill}: {exc}") from exc
    return drawio_cafe, drawio_cafe_svg
#: ArchiMate relation between two placed components -> the CAFÉ edge kind it is drawn as.
EDGE_KINDS = {"Serving": "request", "Flow": "request", "Triggering": "event", "Access": "data",
              "Realization": "request"}


def _cid(eid: str) -> str:
    return "c_" + re.sub(r"[^a-z0-9]+", "_", eid.lower()).strip("_")


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def catalogue() -> dict[str, str]:
    """Normalised CAFÉ component name -> the reference architecture's own id for it.

    Our corpus components were EXTRACTED from the same artifact this skill draws, so a component
    the design selected is usually the catalogue's own component under the same name. Reusing that
    id is what lets the reference architecture's edges between them survive into the drawing: with
    `include_comps: ["none"]` the canonical tiles stay out, but a canonical edge whose BOTH ends are
    components this design selected is a connection the published architecture asserts, not one we
    invented. Without it the view is a parts list — measured run 5, 15 Sep 2026: fifteen tiles, no
    lines."""
    drawio_cafe, _ = engine()
    return {_norm(c[2]): c[0] for c in drawio_cafe.COMPS}


def solution_spec(spec: Mapping[str, Any], known: Mapping[str, str] | None = None) -> tuple[dict, dict]:
    """(the skill's solution spec, {placed, unplaced}). Refuses a model with no archetype — the
    composition step puts it on the root, and a drawing based on a guessed archetype would show a
    canonical shape the design never chose."""
    elements = [e for e in spec.get("elements") or [] if isinstance(e, Mapping)]
    archetype = next(((e.get("props") or {}).get("cafe.archetype") for e in elements
                      if (e.get("props") or {}).get("cafe.archetype")), "")
    if not archetype:
        raise ValueError("the model carries no `cafe.archetype` — the composition (step 22) sets it "
                         "from the topology; a solution view cannot be drawn without one")
    index = dict(known or {})
    placed: dict[str, str] = {}
    unplaced: list[str] = []
    custom: list[dict] = []
    catalogued = 0
    for e in elements:
        if e.get("type") != "ApplicationComponent":
            continue
        props = e.get("props") or {}
        zone = ZONE_IDS.get(str(props.get("cafe.zone") or ""))
        if not zone:
            unplaced.append(e["id"])
            continue
        name = str(e.get("name") or e["id"])
        # The catalogue's own id where this IS a catalogue component, so its published edges are
        # drawn; a minted one (and the extension warning that goes with it) only for what the
        # reference architecture does not carry.
        known_cid = index.get(_norm(name))
        cid = placed[e["id"]] = known_cid or _cid(e["id"])
        catalogued += 1 if known_cid else 0
        custom.append({"cid": cid, "zone": zone, "title": name,
                       "desc": str(props.get("cafe.families") or ""),
                       "kind": "boundary" if known_cid else "m4-extension"})
    edges = [{"from": placed[r["src"]], "to": placed[r["tgt"]], "kind": EDGE_KINDS[r["type"]]}
             for r in spec.get("relations") or []
             if r.get("type") in EDGE_KINDS and r.get("src") in placed and r.get("tgt") in placed]
    title = str(spec.get("name") or "use case")
    return ({"title": f"CAFÉ solution view — {title}", "use_case": title, "base_archetype": archetype,
             "include_comps": ["none"], "custom_comps": custom, "edges": edges},
            {"placed": sorted(placed), "unplaced": sorted(unplaced), "catalogued": catalogued})


def render(spec: Mapping[str, Any]) -> dict:
    """The drawing and its preview, as text, plus what was placed. The skill's ERRORs refuse; its
    WARNs (every m4-extension prompts a catalogue update) are returned, not printed."""
    drawio_cafe, drawio_cafe_svg = engine()
    solution, report = solution_spec(spec, catalogue())
    issues = drawio_cafe.validate_solution_spec(solution)
    errors = [i for i in issues if i.startswith("ERROR")]
    if errors:
        raise ValueError("; ".join(errors))
    diagram = drawio_cafe.build_diagram_from_solution(solution)
    xml = diagram.render(layout="banded", outline_bands=True, animate_async=True, strict=False)
    xml = drawio_cafe.cafe_postprocess(xml, diagram._cafe_kind_by_pair, dark=True,
                                       custom_cids_marked=getattr(diagram, "_cafe_custom_cids", []))
    svg = drawio_cafe_svg.drawio_to_svg(xml, title=solution["title"], theme="dark")
    warnings = [i for i in issues if not i.startswith("ERROR")][:10]
    drawn = len(getattr(diagram, "_cafe_kind_by_pair", {}) or {})
    if len(report["placed"]) > 1 and not drawn:
        # A drawing of disconnected tiles is a parts list, and it looks like an architecture.
        warnings.append(f'{len(report["placed"])} components, no connections drawn — neither the '
                        f'model nor the reference architecture carries an edge between any two of '
                        f'them, so this view shows what was selected, not how it fits together')
    return {"drawio": xml, "svg": svg, "placed": report["placed"], "unplaced": report["unplaced"],
            "catalogued": report["catalogued"], "edges": drawn,
            "violations": len(getattr(diagram, "violations", ()) or ()), "warnings": warnings}
