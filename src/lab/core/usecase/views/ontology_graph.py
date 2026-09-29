"""Step 9's view: the use case's match against the CAFÉ ontology, as a D3 force-directed graph.

Ported from the `cafe-ontology-graph` skill (CAFÉ skills bundle, 29 Sep 2026), minus the workbook
reader and the browser: `render(data, inp)` returns ONE self-contained, interactive HTML page (D3
inlined, so it works offline). Concepts are nodes carrying their full record; relationships are
labelled edges. Green matched · amber partial, or enhancement (dashed) · red dashed gap (needed,
not in the ontology — the ontology delta) · grey context.

`inp`: `{"use_case", "title", "date", "context"?: neighbours|module|all|none, "concepts": [{"id",
"status", "note"?, "name"?, "module"?, "kind"?, "definition"?}], "relationships": [{"subject",
"predicate", "object", "status"?}]}`. Relationships that already exist between two matched or
partial concepts are added automatically. A red node is a PROPOSAL: the Ontology Council admits it.
"""
from __future__ import annotations

import html
import re
from importlib import resources

from lab.core.usecase.views.common import ViewError, script_json

__all__ = ["render"]

STATUS = {'matched': 'matched', 'match': 'matched', 'green': 'matched', 'partial': 'partial', 'amber': 'partial',
          'enhancement': 'enhancement', 'enhance': 'enhancement', 'gap': 'gap', 'missing': 'gap', 'red': 'gap'}


def build(onto, inp, context):
    T = onto['tables']
    C = {c['id']: c for c in T['ontology-concepts']}
    mods = {m['id']: m['name'] for m in T.get('ontology-modules', [])}
    R = T['ontology-relationships']
    nodes, notes, unresolved = {}, {}, []
    for e in inp.get('concepts', []):
        st = STATUS.get(str(e.get('status', 'matched')).lower())
        if not st: raise ViewError(f"unknown status {e.get('status')} for {e.get('id')}")
        cid = str(e.get('id'))
        if cid in C:
            rec = dict(C[cid]); rec['ontology_status'] = C[cid].get('status'); rec['status'] = st
        elif st == 'gap':
            rec = {'id': cid, 'name': e.get('name', cid), 'module': e.get('module', ''), 'kind': e.get('kind', ''),
                   'definition': e.get('definition', ''), 'authoritative_source': 'not in the ontology — ontology delta', 'status': 'gap', 'proposed': True}
        else:
            unresolved.append(cid); continue
        if e.get('note'): rec['note'] = e['note']
        nodes[cid] = rec
    focus = set(nodes)
    edges, seen = [], set()
    for e in inp.get('relationships', []):
        s, p, o = e.get('subject'), e.get('predicate'), e.get('object')
        exists = any(r['subject'] == s and r['predicate'] == p and r['object'] == o for r in R)
        st = STATUS.get(str(e.get('status') or ('matched' if exists else 'gap')).lower(), 'gap')
        for x in (s, o):
            if x not in nodes and x in C: nodes[x] = dict(C[x], ontology_status=C[x].get('status'), status='context')
            elif x not in nodes: unresolved.append(x)
        if s in nodes and o in nodes:
            edges.append({'source': s, 'target': o, 'predicate': p, 'status': st, 'note': e.get('note', ''), 'cardinality': e.get('cardinality', '')}); seen.add((s, p, o))
    for r in R:   # existing relationships among the matched set
        s, p, o = r['subject'], r['predicate'], r['object']
        if s in focus and o in focus and (s, p, o) not in seen and nodes[s]['status'] != 'gap' and nodes[o]['status'] != 'gap':
            st = 'matched' if nodes[s]['status'] == 'matched' and nodes[o]['status'] == 'matched' else 'partial'
            edges.append({'source': s, 'target': o, 'predicate': p, 'status': st, 'cardinality': r.get('cardinality', ''), 'note': r.get('note') or ''}); seen.add((s, p, o))
    if context in ('neighbours', 'module', 'all'):
        for r in R:
            s, p, o = r['subject'], r['predicate'], r['object']
            take = (context == 'all') or (context == 'neighbours' and (s in focus) != (o in focus)) or \
                   (context == 'module' and ({s, o} & focus) and all(C.get(x, {}).get('module') in {nodes[f].get('module') for f in focus} for x in (s, o)))
            if take and (s, p, o) not in seen:
                for x in (s, o):
                    if x not in nodes and x in C: nodes[x] = dict(C[x], ontology_status=C[x].get('status'), status='context')
                if s in nodes and o in nodes:
                    edges.append({'source': s, 'target': o, 'predicate': p, 'status': 'context', 'cardinality': r.get('cardinality', ''), 'note': r.get('note') or ''}); seen.add((s, p, o))
    for c in C.values():   # parent (is-a) links
        if c['id'] in nodes and c.get('parent') and c['parent'] in nodes:
            st = 'matched' if nodes[c['id']]['status'] in ('matched',) and nodes[c['parent']]['status'] == 'matched' else 'context'
            edges.append({'source': c['id'], 'target': c['parent'], 'predicate': 'is a', 'status': st, 'isa': True})
    ind = {}
    for l in T.get('ontology-indicator-links', []): ind.setdefault(l['concept'], []).append(l['from'])
    for n in nodes.values():
        n['indicators'] = '; '.join(ind.get(n['id'], []))
        n['module_name'] = mods.get(n.get('module'), n.get('module', ''))
    return list(nodes.values()), edges, sorted(set(unresolved)), mods


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>__TITLE__</title>
<style>
:root{--g:#1e7b34;--gf:#bfe6c6;--a:#a86b00;--af:#ffd98c;--r:#b3261e;--rf:#f5b1b1;--c:#9ca3af;--cf:#eef0f3}
*{box-sizing:border-box}html,body{margin:0;height:100%;font-family:'DejaVu Sans',Arial,sans-serif;color:#1c2330;background:#fff}
#hdr{position:absolute;left:16px;top:10px;right:360px}#hdr h1{font-size:19px;margin:0}#hdr .sub{font-size:12px;color:#4b5563;margin-top:3px}
#legend{position:absolute;left:16px;bottom:12px;font-size:11.5px;background:rgba(255,255,255,.92);border:1px solid #e5e7eb;border-radius:6px;padding:6px 10px}
.sw{display:inline-block;width:12px;height:12px;border-radius:50%;vertical-align:-2px;margin:0 4px 0 10px;border:2px solid}
#panel{position:absolute;right:0;top:0;bottom:0;width:340px;border-left:1px solid #e5e7eb;background:#fbfcfd;padding:14px 16px;overflow:auto;font-size:12.5px}
#panel h2{font-size:16px;margin:0 0 4px}#panel .k{color:#6b7280;font-size:11px;text-transform:uppercase;letter-spacing:.04em;margin-top:9px}
#panel .pill{display:inline-block;border-radius:10px;padding:1px 8px;font-size:11px;font-weight:700;border:1.5px solid}
#search{width:100%;padding:6px 8px;border:1px solid #d1d5db;border-radius:6px;margin-bottom:10px;font-size:12.5px}
.counts span{display:inline-block;margin-right:10px;font-weight:700}
svg{position:absolute;left:0;top:0}
.lbl{font-size:10.5px;pointer-events:none;paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round}
.elbl{font-size:8.5px;fill:#4b5563;pointer-events:none;paint-order:stroke;stroke:#fff;stroke-width:2.5px}
.dim{opacity:.12}
</style></head><body>
<div id="hdr"><h1>__TITLE__</h1><div class="sub">__SUB__</div></div>
<div id="legend"><span class="sw" style="background:var(--gf);border-color:var(--g)"></span>matched
<span class="sw" style="background:var(--af);border-color:var(--a)"></span>partial / enhancement (dashed)
<span class="sw" style="background:var(--rf);border-color:var(--r)"></span>gap — not in the ontology
<span class="sw" style="background:var(--cf);border-color:var(--c)"></span>context &nbsp;·&nbsp; edge colour follows the same key · ▷ is-a</div>
<div id="panel"><input id="search" placeholder="Search concepts…"><div class="counts" id="counts"></div><div id="detail"><p style="color:#6b7280">Click a concept to see its full record. Drag to move, scroll to zoom.</p></div></div>
<script>__D3__</script>
<script>
const DATA=__DATA__;
const STATIC=location.search.includes('static');
const W=window.innerWidth-(STATIC?0:340),H=window.innerHeight;
const col={matched:['#bfe6c6','#1e7b34'],partial:['#ffd98c','#a86b00'],enhancement:['#ffd98c','#a86b00'],gap:['#f5b1b1','#b3261e'],context:['#eef0f3','#9ca3af']};
const nodes=DATA.nodes.map(d=>Object.assign({},d)),links=DATA.edges.map(d=>Object.assign({},d));
const deg={};links.forEach(l=>{deg[l.source]=(deg[l.source]||0)+1;deg[l.target]=(deg[l.target]||0)+1});
const mods=[...new Set(nodes.map(n=>n.module||''))];const mx=d3.scaleBand().domain(mods).range([W*0.12,W*0.88]);
const r=d=>(d.status==='context'?6:10)+Math.min(8,(deg[d.id]||0)*0.8);
const svg=d3.select('body').append('svg').attr('width',W).attr('height',H);
const defs=svg.append('defs');
Object.entries(col).forEach(([k,[f,s]])=>{defs.append('marker').attr('id','a-'+k).attr('viewBox','0 -5 10 10').attr('refX',10).attr('markerWidth',6).attr('markerHeight',6).attr('orient','auto').append('path').attr('d','M0,-5L10,0L0,5').attr('fill',s);
 defs.append('marker').attr('id','i-'+k).attr('viewBox','0 -6 12 12').attr('refX',12).attr('markerWidth',9).attr('markerHeight',9).attr('orient','auto').append('path').attr('d','M0,-6L12,0L0,6Z').attr('fill','#fff').attr('stroke',s)});
const g=svg.append('g');
const zoom=d3.zoom().scaleExtent([0.2,4]).on('zoom',e=>g.attr('transform',e.transform));
if(!STATIC) svg.call(zoom);
const sim=d3.forceSimulation(nodes).force('link',d3.forceLink(links).id(d=>d.id).distance(l=>l.status==='context'?75:135).strength(0.55))
 .force('charge',d3.forceManyBody().strength(d=>d.status==='context'?-160:-650)).force('collide',d3.forceCollide(d=>r(d)+30))
 .force('x',d3.forceX(d=>mx(d.module||'')+mx.bandwidth()/2).strength(0.06)).force('y',d3.forceY(H/2+20).strength(0.07)).stop();
for(let i=0;i<500;i++) sim.tick();

const link=g.append('g').selectAll('path').data(links).join('path').attr('fill','none')
 .attr('stroke',d=>col[d.status][1]).attr('stroke-width',d=>d.status==='context'?1:2).attr('opacity',d=>d.status==='context'?0.6:0.9)
 .attr('stroke-dasharray',d=>d.status==='gap'?'6 4':d.status==='enhancement'?'3 3':d.isa?'2 3':null)
 .attr('marker-end',d=>`url(#${d.isa?'i':'a'}-${d.status})`);
const elbl=g.append('g').selectAll('text').data(links.filter(l=>l.status!=='context'&&!l.isa)).join('text').attr('class','elbl').attr('text-anchor','middle').text(d=>d.predicate);
const node=g.append('g').selectAll('g').data(nodes).join('g').style('cursor','pointer');
node.append('circle').attr('r',r).attr('fill',d=>col[d.status][0]).attr('stroke',d=>col[d.status][1]).attr('stroke-width',d=>d.status==='context'?1.2:2.4)
 .attr('stroke-dasharray',d=>d.proposed?'4 3':d.status==='enhancement'?'3 2':null);
node.append('text').attr('class','lbl').attr('dy',d=>r(d)+12).attr('text-anchor','middle').style('font-weight',d=>d.status==='context'?400:700)
 .style('fill',d=>d.status==='context'?'#6b7280':'#1c2330').text(d=>d.name||d.id);
function pos(){link.attr('d',d=>{const dx=d.target.x-d.source.x,dy=d.target.y-d.source.y,L=Math.hypot(dx,dy)||1,rt=r(d.target)+3;
  return `M${d.source.x},${d.source.y}L${d.target.x-dx/L*rt},${d.target.y-dy/L*rt}`});
 elbl.attr('x',d=>(d.source.x+d.target.x)/2).attr('y',d=>(d.source.y+d.target.y)/2-3);node.attr('transform',d=>`translate(${d.x},${d.y})`)}
pos();
{const xs=nodes.map(d=>d.x),ys=nodes.map(d=>d.y);const x0=Math.min(...xs)-60,x1=Math.max(...xs)+60,y0=Math.min(...ys)-30,y1=Math.max(...ys)+40;
 const k=Math.min((W-40)/(x1-x0),(H-130)/(y1-y0),1.8);const t=d3.zoomIdentity.translate((W-(x1-x0)*k)/2-x0*k,70+(H-130-(y1-y0)*k)/2-y0*k).scale(k);
 g.attr('transform',t);if(!STATIC) svg.call(zoom.transform,t);}
if(!STATIC){sim.on('tick',pos);node.call(d3.drag().on('start',(e,d)=>{if(!e.active)sim.alphaTarget(0.2).restart();d.fx=d.x;d.fy=d.y})
 .on('drag',(e,d)=>{d.fx=e.x;d.fy=e.y}).on('end',(e,d)=>{if(!e.active)sim.alphaTarget(0);d.fx=null;d.fy=null}));}
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function show(d){const [f,s]=col[d.status];const rel=links.filter(l=>l.source.id===d.id||l.target.id===d.id);
 const row=(k,v)=>v?`<div class="k">${k}</div><div>${esc(v)}</div>`:'';
 document.getElementById('detail').innerHTML=`<h2>${esc(d.name||d.id)}</h2><span class="pill" style="background:${f};border-color:${s};color:${s}">${d.status}${d.proposed?' · proposed':''}</span>`+
 row('Id',d.id)+row('Module',d.module_name)+row('Kind',d.kind)+row('Parent',d.parent)+row('Definition',d.definition)+row('Use-case note',d.note)+
 row('Authoritative source',d.authoritative_source)+row('Platforms',d.platforms)+row('FHIR',d.fhir)+row('Guild reference',d.guild_reference)+
 row('Used by (questions and indicators)',[d.used_by,d.indicators].filter(Boolean).join('; '))+row('Status in ontology',d.proposed?'not in the ontology — ontology delta':d.ontology_status)+
 `<div class="k">Relationships (${rel.length})</div>`+rel.map(l=>`<div>${esc(l.source.name||l.source.id)} <b>${esc(l.predicate)}</b> ${esc(l.target.name||l.target.id)} <span style="color:${col[l.status][1]}">● ${l.status}</span></div>`).join('');
 node.classed('dim',n=>n!==d&&!rel.some(l=>l.source===n||l.target===n));link.classed('dim',l=>!rel.includes(l));elbl.classed('dim',l=>!rel.includes(l))}
node.on('click',(e,d)=>{e.stopPropagation();show(d)});svg.on('click',()=>{node.classed('dim',false);link.classed('dim',false);elbl.classed('dim',false)});
const cnt=k=>nodes.filter(n=>n.status===k).length;
document.getElementById('counts').innerHTML=`<span style="color:#1e7b34">${cnt('matched')} matched</span><span style="color:#a86b00">${cnt('partial')+cnt('enhancement')} partial/enh.</span><span style="color:#b3261e">${cnt('gap')} gap</span><span style="color:#6b7280">${cnt('context')} context</span>`;
document.getElementById('search').addEventListener('input',e=>{const q=e.target.value.toLowerCase();node.classed('dim',n=>q&&!((n.name||'')+n.id).toLowerCase().includes(q))});
window.__done=true;
</script></body></html>"""


def _d3() -> str:
    return resources.files("lab.core.usecase.views").joinpath("assets/d3.min.js").read_text()


def render(data, inp, *, context=None) -> dict:
    """The page and what a caller reports: counts by status, and ids that resolved to nothing."""
    onto = data['ontology']
    context = context or inp.get('context', 'neighbours')
    nodes, edges, unresolved, mods = build(onto, inp, context)
    counts = {k: sum(n['status'] == k for n in nodes) for k in ('matched', 'partial', 'enhancement', 'gap', 'context')}
    sub = (f'{inp.get("use_case", "")} · ontology {onto["version"]} · {counts["matched"]} matched · {counts["partial"] + counts["enhancement"]} partial or enhancement · '
           f'{counts["gap"]} gap · context: {context} · {inp.get("date", "")}')
    # ONE pass: chained replaces would let a title containing `__DATA__` pull the data into the
    # heading, because the title is substituted first and then searched again.
    parts = {'TITLE': html.escape(inp.get('title') or 'Ontology match'), 'SUB': html.escape(sub),
             'D3': _d3(), 'DATA': script_json({'nodes': nodes, 'edges': edges})}
    page = re.sub(r'__(TITLE|SUB|D3|DATA)__', lambda m: parts[m[1]], PAGE)
    return {"html": page, "summary": {"ontology_version": onto['version'], "counts": counts,
                                      "edges": len(edges), "unresolved": unresolved}}
