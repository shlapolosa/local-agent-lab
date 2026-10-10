"""The D3 adapter: a `TopologyView` as an interactive force graph, in ONE self-contained HTML file.

The sibling of `viz_svg`, and the two divide by what they are good at rather than by preference. The SVG
renderer places nodes in rings — deterministic, scriptless, and the right picture for ONE record, which is
a handful of nodes around a focus. This one simulates, so it is the right picture when the view is wide
enough that the interesting fact is which nodes CLUSTER: records sharing a subject, a concept several
records are about, a corner of the vocabulary nothing reaches. Neither knows what a rung is beyond the
shared palette; both satisfy `lab.core.viz.GraphRenderer`, and `FABRIC_RENDERER` picks.

EVERYTHING IS INLINE, and that is a measured requirement. Probed live in the tenant on 10 Oct 2026: a page
written into the SharePoint library ran its inline script and rendered script-drawn SVG, and was refused an
external one — `cdnjs.cloudflare.com` did not load. A CDN link would therefore render an empty box in the
one place the fabric publishes its pages, silently. So D3 comes from the lab's own vendored copy
(`lab.core.assets`), and a test asserts the page fetches nothing.

No store, no network, no Redis: a view in, bytes out.
"""
from __future__ import annotations

import html as _html
import json

from lab.core import assets
from lab.core.viz import ARTIFACT, CONCEPT, MEANING, PROPOSED, VOCABULARY, Rendered, TopologyView, colour

__all__ = ["D3HtmlRenderer", "build"]

#: `</script>` inside a JSON string ends the SCRIPT, not the string — the browser's tokeniser never sees the
#: JSON. Titles come from documents people write, so this is reachable, not theoretical.
_BREAKOUT = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026", " ": "\\u2028", " ": "\\u2029"}


#: facets that NARROW a picture, in the order a person reaches for them. `records` is deliberately absent:
#: it is a concept's own weight, which SIZES a node — offering it as a filter would ask somebody to pick a
#: number out of a list of numbers.
_FILTERABLE = ("source", "state", "document_type")
#: what a filter is called in front of a person. The facet name is the domain's word; this is English.
_FILTER_LABEL = {"source": "Source", "state": "State", "document_type": "Type"}


def _payload(view: TopologyView) -> str:
    """The view as JSON safe to embed in a `<script>`."""
    data = {
        "nodes": [{"id": n.id, "label": n.label, "kind": n.kind, "status": n.status, "note": n.note,
                   "focus": n.id == view.focus,
                   "records": int(n.facet("records") or 0),
                   "facets": {k: v for k, v in n.facets if k in _FILTERABLE},
                   "fill": colour(n.status)[0], "stroke": colour(n.status)[1]} for n in view.nodes],
        "edges": [{"source": e.source, "target": e.target, "label": e.label, "status": e.status,
                   "stroke": colour(e.status)[1],
                   "dashed": e.status in (PROPOSED, VOCABULARY)} for e in view.edges],
        # One predicate across the whole view means the label says nothing a reader did not already know —
        # and written on every edge it is the ink that made the first corpus picture unreadable.
        "labelEdges": len({e.label for e in view.edges}) > 1,
        "bipartite": _both_kinds(view),
    }
    out = json.dumps(data, ensure_ascii=False)
    for bad, safe in _BREAKOUT.items():
        out = out.replace(bad, safe)
    return out


def _both_kinds(view: TopologyView) -> bool:
    """Whether this picture holds records AND concepts — the only case where separating them, or hiding
    one, is a control rather than a way to make the picture worse."""
    kinds = {n.kind for n in view.nodes}
    return ARTIFACT in kinds and CONCEPT in kinds


def _modes(view: TopologyView) -> str:
    """Records alone · the vocabulary alone · the join. Offered only when the view HAS both, because a
    single record's picture is already one focus and a handful of nodes."""
    if not _both_kinds(view):
        return ""
    buttons = "".join(
        f'<button data-mode="{key}"{" class=on" if key == "about" else ""}>{label}</button>'
        for key, label in (("about", "About"), ("records", "Records"), ("vocabulary", "Vocabulary")))
    return f'<div class="modes" role="group" aria-label="view">{buttons}</div>'


def _filters(view: TopologyView) -> str:
    """Built from the facets the view ACTUALLY contains, so a filter never offers a choice that matches
    nothing. Two thirds of the first corpus picture was the lab's own test output; being unable to say
    "only what a person wrote" is what made it unreadable rather than merely busy."""
    blocks = []
    for name in _FILTERABLE:
        values = view.facet_values(name)
        if len(values) < 2:                 # one value narrows nothing; none means nobody recorded it
            continue
        chips = "".join(f'<button data-facet="{name}" data-value="{_html.escape(v)}" class=on>'
                        f'{_html.escape(v)}</button>' for v in values)
        blocks.append(f'<span class="filter"><b>{_FILTER_LABEL.get(name, name)}</b>{chips}</span>')
    return f'<div class="filters">{"".join(blocks)}</div>' if blocks else ""


def _legend(view: TopologyView) -> str:
    """Built from the VIEW, not the palette: a legend that explains rungs this picture does not contain
    teaches a person a distinction they cannot see, which is worse than no legend."""
    items = []
    for status in view.statuses:
        fill, stroke, words = colour(status)
        items.append(f'<li><i style="background:{fill};border-color:{stroke}"></i>'
                     f'{_html.escape(words)}</li>')
    return "".join(items)


_SCRIPT = """
const W = innerWidth, H = Math.max(420, innerHeight - 180);
const svg = d3.select('#g').attr('viewBox', [0, 0, W, H]);
const root = svg.append('g');
svg.call(d3.zoom().scaleExtent([0.15, 4]).on('zoom', e => root.attr('transform', e.transform)));

const off = {};                       // facet -> Set of values the viewer has switched OFF
let mode = 'about';

const isRecord = d => d.kind === 'artifact';
// A concept grows with what it holds: the first corpus picture drew a concept holding half the
// catalogue the same size as one holding a single record, which is the one thing it had to show.
const r = d => d.focus ? 13 : isRecord(d) ? 8 : Math.min(26, 7 + Math.sqrt(d.records || 0) * 3.2);

function visible(d) {
  if (mode === 'records' && !isRecord(d)) return false;
  if (mode === 'vocabulary' && isRecord(d)) return false;
  for (const f in off) if (off[f].has((d.facets || {})[f])) return false;
  return true;
}

const link = root.append('g').attr('class', 'links');
const elabel = root.append('g').attr('class', 'elabels');
const nodeg = root.append('g').attr('class', 'nodes');
let sim;

function draw() {
  const nodes = DATA.nodes.filter(visible);
  const keep = new Set(nodes.map(n => n.id));
  const edges = DATA.edges
    .map(e => ({...e, source: e.source.id || e.source, target: e.target.id || e.target}))
    .filter(e => keep.has(e.source) && keep.has(e.target));
  d3.select('#count').text(nodes.length + ' shown · ' + edges.length + ' links');

  const edge = link.selectAll('line').data(edges, d => d.source + '>' + d.target + d.label)
    .join('line').attr('stroke', d => d.stroke).attr('stroke-width', 1.4).attr('opacity', 0.6)
    .attr('stroke-dasharray', d => d.dashed ? '5 4' : null);
  const el = elabel.selectAll('text').data(DATA.labelEdges ? edges : [],
      d => d.source + '>' + d.target + d.label)
    .join('text').attr('font-size', 10).attr('fill', '#7a8793').attr('text-anchor', 'middle')
    .text(d => d.label);

  const node = nodeg.selectAll('g').data(nodes, d => d.id).join(enter => {
    const g = enter.append('g').style('cursor', 'grab');
    g.append('circle').attr('stroke-width', 2);
    g.append('title');
    g.append('text').attr('y', 4).attr('fill', '#1f2a37');
    return g;
  });
  node.select('circle').attr('r', r).attr('fill', d => d.fill).attr('stroke', d => d.stroke);
  node.select('title').text(d => d.label + (d.note ? ' — ' + d.note : ''));
  node.select('text').attr('x', d => r(d) + 6)
    .attr('font-size', d => d.focus || !isRecord(d) ? 13 : 11)
    .attr('font-weight', d => isRecord(d) ? 400 : 600)
    .text(d => d.label);
  node.call(d3.drag()
    .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.25).restart(); d.fx = d.x; d.fy = d.y; })
    .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
    .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));

  if (sim) sim.stop();
  sim = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(edges).id(d => d.id).distance(d => d.dashed ? 150 : 100).strength(0.45))
    .force('charge', d3.forceManyBody().strength(d => d.focus ? -900 : isRecord(d) ? -220 : -520))
    .force('collide', d3.forceCollide(d => r(d) + 24));

  // BIPARTITE in the join: concepts in a band on the right, records on the left. The question the join
  // answers is what is about what — which a hairball hides and two columns make readable at a glance.
  if (DATA.bipartite && mode === 'about') {
    sim.force('x', d3.forceX(d => isRecord(d) ? W * 0.3 : W * 0.78).strength(0.22))
       .force('y', d3.forceY(H / 2).strength(0.04));
  } else {
    sim.force('centre', d3.forceCenter(W / 2, H / 2));
  }

  sim.on('tick', () => {
    edge.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    el.attr('x', d => (d.source.x + d.target.x) / 2).attr('y', d => (d.source.y + d.target.y) / 2 - 4);
    node.attr('transform', d => `translate(${d.x},${d.y})`);
  });
}

document.querySelectorAll('[data-mode]').forEach(b => b.onclick = () => {
  mode = b.dataset.mode;
  document.querySelectorAll('[data-mode]').forEach(o => o.classList.toggle('on', o === b));
  draw();
});
document.querySelectorAll('[data-facet]').forEach(b => b.onclick = () => {
  const f = b.dataset.facet, v = b.dataset.value;
  (off[f] = off[f] || new Set()).has(v) ? off[f].delete(v) : off[f].add(v);
  b.classList.toggle('on');
  draw();
});
draw();
"""


class D3HtmlRenderer:
    """One page, one inlined library, no network. Satisfies `lab.core.viz.GraphRenderer`."""

    name = "d3"
    media_type = "text/html; charset=utf-8"
    suffix = ".html"

    def render(self, view: TopologyView) -> Rendered:
        esc = _html.escape
        page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(view.title)}</title>
<style>
 :root {{ color-scheme: light }}
 * {{ box-sizing: border-box }}
 body {{ margin:0; font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
         color:#1f2a37; background:#fff }}
 header {{ padding:18px 24px 10px }}
 h1 {{ margin:0; font-size:21px; font-weight:650 }}
 .sub {{ color:#5b6b7a; font-size:13px; margin-top:3px }}
 ul.legend {{ display:flex; flex-wrap:wrap; gap:8px 20px; list-style:none; margin:12px 0 0; padding:0;
              font-size:12.5px; color:#44525e }}
 ul.legend i {{ display:inline-block; width:11px; height:11px; border-radius:50%; border:2px solid;
                margin-right:7px; vertical-align:-1px }}
 .hint {{ padding:0 24px; color:#7a8793; font-size:12px }}
 .modes, .filters {{ display:flex; flex-wrap:wrap; gap:8px 16px; align-items:center; padding:10px 24px 0 }}
 .filter {{ display:flex; align-items:center; gap:6px }}
 .filter b {{ font-weight:600; font-size:12px; color:#5b6b7a; margin-right:2px }}
 button {{ font:inherit; font-size:12.5px; padding:4px 11px; border:1px solid #cfd8dd; border-radius:999px;
           background:#fff; color:#5b6b7a; cursor:pointer }}
 button.on {{ background:#1f2a44; border-color:#1f2a44; color:#fff }}
 .modes button {{ font-weight:550 }}
 #count {{ color:#7a8793; font-size:12px; padding:0 24px }}
 svg {{ display:block; width:100%; touch-action:none }}
 @media (max-width:640px) {{ header {{ padding:14px 16px 8px }} .hint {{ padding:0 16px }} }}
</style></head>
<body>
<header>
  <h1>{esc(view.title)}</h1>
  <div class="sub">{esc(view.subtitle)}{(' · as of ' + esc(view.as_of)) if view.as_of else ''}</div>
  <ul class="legend">{_legend(view)}</ul>
</header>
{_modes(view)}
{_filters(view)}
<p class="hint">Drag a node to move it · scroll to zoom · hover for detail. The colour of a node says how
the fabric knows it; a concept grows with how much of the corpus it holds. Redrawn from the graph on
every publish. <span id="count"></span></p>
<svg id="g" height="640" role="img" aria-label="{esc(view.title)} and what it is connected to"></svg>
<script>{assets.d3()}</script>
<script>const DATA = {_payload(view)};{_SCRIPT}</script>
</body></html>
"""
        return Rendered(content=page.encode("utf-8"), media_type=self.media_type, suffix=self.suffix)


def build(**overrides) -> D3HtmlRenderer:
    """The composition root's factory. Nothing to configure — the palette is the fabric's shared
    vocabulary and the layout is the simulation's — so an option is a caller's mistaken belief, and
    saying so beats accepting a setting that would never take effect."""
    if overrides:
        raise TypeError(f"the d3 renderer takes no options; got {sorted(overrides)}")
    return D3HtmlRenderer()
