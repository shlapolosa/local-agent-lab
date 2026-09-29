"""Step 5's view: the CAFÉ technology capability map (the A0 poster), impacted L3s RAG-filled.

Ported from the `cafe-capability-heatmap` skill (CAFÉ skills bundle, 29 Sep 2026), minus the
workbook reader and the browser: `render(data, inp)` returns the page. Every L3 stays on the page,
faded unless impacted, so the impact reads against the whole map.

`inp`: `{"use_case", "title", "date", "capabilities": [{"id", "status", "note"?} |
{"name", "parent_l2", "status"}]}` — a name with a parent L2 is a PROPOSED capability, drawn red
dashed (a capability-map delta). status: missing (red) · new (green) · consumed (amber, C) ·
updated (amber, U). Retired ids resolve to their successor; unknown ids are listed on the page and
returned, never dropped. The business-map variant stays in the skill until step 3 needs it.
"""
from __future__ import annotations

import datetime

from lab.core.usecase.views.common import EDGE, FILL, TAG, esc, norm_status, retired_map

__all__ = ["render"]

L1COL = {"BUS": "#8a5a00", "SEM": "#2f6f4f", "KNW": "#0f766e", "COG": "#5b3fa3", "MOD": "#7a3fa3", "APP": "#1f5fa8",
         "DAT": "#2d5d8a", "TEC": "#475569", "XCT": "#9f2f4f", "RCV": "#8a3ffc", "PPL": "#b4530e", "BND": "#6b5a44"}
PH = ['Design', 'Build', 'Run', 'Operate']




def build_model(data):
    t = data['tech']['tables']
    l1 = t['technology-capability-l1']; l2 = t['technology-capability-l2']; l3 = t['technology-capability-l3']
    l3_by_l2 = {}
    for r in l3:
        l3_by_l2.setdefault(r['l2'], []).append(r)
    tree = [{'l1': a, 'l2s': [{'l2': b, 'l3s': l3_by_l2.get(b['id'], [])} for b in l2 if b['l1'] == a['id']]} for a in l1]
    return tree, {r['id']: r for r in l3}, {r['id']: r for r in l2}, retired_map(t.get('retired-capability-ids'))


def resolve(inp, l3idx, l2idx, retired):
    impacts, proposed, notes, unresolved = {}, [], [], []
    for e in inp.get('capabilities', []):
        st = norm_status(e.get('status')); cid = str(e.get('id') or '').strip()
        if cid in l3idx:
            impacts[cid] = dict(e, status=st)
        elif cid in retired and retired[cid] in l3idx:
            impacts[retired[cid]] = dict(e, status=st, id=retired[cid]); notes.append(f"{cid} is retired — shown as {retired[cid]}")
        elif e.get('parent_l2') in l2idx:
            proposed.append(dict(e, status=st))
        else:
            unresolved.append(cid or e.get('name', '(unnamed)'))
    return impacts, proposed, notes, unresolved


def page(tree, impacts, proposed, notes, unresolved, inp, version, s, cols=6):
    cnt = {k: sum(1 for v in impacts.values() if v['status'] == k) for k in FILL}
    cnt['missing'] += len(proposed)
    total = sum(len(b['l3s']) for a in tree for b in a['l2s'])
    css = f"""
@page{{size:1189mm 841mm;margin:0}}*{{box-sizing:border-box}}html,body{{margin:0}}
body{{width:1189mm;height:841mm;padding:14mm 16mm 12mm;font-family:'DejaVu Sans',Arial,sans-serif;color:#1c2330;background:#fff;font-size:{9.2*s}pt;line-height:1.28;position:relative}}
.top{{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:1.2mm solid #1c2330;padding-bottom:4mm;margin-bottom:5mm;gap:12mm}}
h1{{font-size:{32*s}pt;margin:0;line-height:1.05}}.sub{{font-size:{12*s}pt;color:#4b5563;margin-top:2mm}}
.legend{{font-size:{9.5*s}pt;color:#374151;max-width:600mm;line-height:1.6}}
.sw{{display:inline-block;padding:0 2mm;border-radius:1mm;border:.4mm solid;margin:0 1mm;font-weight:700}}
.chip{{display:inline-block;font:700 {7.4*s}pt 'DejaVu Sans Mono',monospace;border:.3mm solid #9ca3af;color:#9ca3af;border-radius:.8mm;padding:0 .8mm;margin-left:.5mm}}
.chip.on{{background:#1c2330;border-color:#1c2330;color:#fff}}
.cols{{column-count:{cols};column-gap:6mm;column-fill:auto;height:calc(841mm - 26mm - {50*s}mm)}}
.l1{{break-inside:auto;margin:0 0 5mm;border:.5mm solid var(--c);border-radius:2.5mm;padding:2.6mm 2.6mm 1.6mm;background:#fff;-webkit-box-decoration-break:clone;box-decoration-break:clone}}
.keep{{break-inside:avoid}}.l1h{{display:flex;align-items:baseline;gap:2.5mm;margin-bottom:.8mm}}
.l1id{{font:700 {11*s}pt 'DejaVu Sans Mono',monospace;color:#fff;background:var(--c);padding:.3mm 1.6mm;border-radius:1mm}}
.l1n{{font-size:{15*s}pt;font-weight:700;color:var(--c)}}.l1c{{margin-left:auto;font-size:{8*s}pt;color:#6b7280}}
.l1d{{font-size:{8.6*s}pt;color:#374151;margin:0 0 2mm}}
.l2{{break-inside:avoid;border-top:.4mm solid var(--c);padding-top:1.6mm;margin-top:1.6mm}}
.l2h{{display:flex;align-items:baseline;gap:2mm}}.l2id{{font:700 {8.5*s}pt 'DejaVu Sans Mono',monospace;color:var(--c)}}
.l2n{{font-size:{11*s}pt;font-weight:700}}
.l2k{{margin-left:auto;font-size:{7.4*s}pt;font-weight:700;color:#1c2330;background:#eef0f3;border-radius:.8mm;padding:0 1.2mm;white-space:nowrap}}
.l2d{{font-size:{8.2*s}pt;color:#4b5563;margin:.3mm 0 1.2mm}}
.g{{display:grid;grid-template-columns:1fr 1fr;gap:1.4mm}}
.b{{border:.3mm solid #d7dde5;border-left:1mm solid var(--c);border-radius:1mm;padding:1.3mm 1.6mm 1.2mm;background:#fafbfc}}
.b.muted{{opacity:.38}}
.b.hit{{border:.6mm solid var(--e);border-left:1.6mm solid var(--e);background:var(--f)}}
.b.prop{{border:.7mm dashed #b3261e;background:#f5b1b1}}
.bh{{display:flex;justify-content:space-between;align-items:center}}.bid{{font:700 {8*s}pt 'DejaVu Sans Mono',monospace;color:var(--c)}}
.tag{{font:700 {7*s}pt 'DejaVu Sans Mono',monospace;color:#fff;background:var(--e);border-radius:.6mm;padding:0 1mm;margin-left:1mm}}
.bn{{font-weight:700;font-size:{9.4*s}pt;margin:.4mm 0 .5mm;line-height:1.15}}.bd{{font-size:{8*s}pt}}
.bw{{font-size:{7.5*s}pt;color:#374151;margin-top:.7mm}}.bnote{{font-size:{7.8*s}pt;font-weight:700;margin-top:.7mm;color:#1c2330}}
.panel{{border:.5mm solid #b3261e;background:#fff5f5;border-radius:1.5mm;padding:1.5mm 2.5mm;font-size:{8.5*s}pt;margin-top:2mm}}
.foot{{position:absolute;bottom:5mm;left:16mm;right:16mm;font-size:{7.5*s}pt;color:#6b7280;display:flex;justify-content:space-between}}
"""
    parts = []
    for a in tree:
        c = a['l1']['id']; col = L1COL.get(c, '#475569')
        n3 = sum(len(b['l3s']) for b in a['l2s'])
        ids = {b['l2']['id'] for b in a['l2s']}
        hit1 = sum(1 for b in a['l2s'] for r in b['l3s'] if r['id'] in impacts) + sum(1 for p in proposed if p['parent_l2'] in ids)
        parts.append(f'<div class="l1" style="--c:{col}"><div class="keep"><div class="l1h"><span class="l1id">{esc(str(c))}</span>'
                     f'<span class="l1n">{esc(str(a["l1"]["name"]))}</span><span class="l1c">{len(a["l2s"])} L2 · {n3} L3'
                     f'{" · <b>" + str(hit1) + " impacted</b>" if hit1 else ""}</span></div>'
                     f'<div class="l1d">{esc(str(a["l1"].get("description") or ""))}</div>')
        for k, b in enumerate(a['l2s']):
            lid = b['l2']['id']; props = [p for p in proposed if p['parent_l2'] == lid]
            hits = [impacts[r['id']]['status'] for r in b['l3s'] if r['id'] in impacts] + [p['status'] for p in props]
            badge = ''
            if hits:
                badge = (f'<span class="l2k">{len(hits)} impacted · {hits.count("new")} new · '
                         f'{hits.count("consumed") + hits.count("updated")} amber · {hits.count("missing")} missing</span>')
            parts.append(f'<div class="l2"><div class="l2h"><span class="l2id">{esc(str(lid))}</span><span class="l2n">{esc(str(b["l2"]["name"]))}</span>{badge}</div>'
                         f'<div class="l2d">Accountable: {esc(str(b["l2"].get("accountable") or ""))}</div><div class="g">')
            for r in b['l3s']:
                ph = str(r.get('phases') or '')
                chips = ''.join(f'<span class="chip{" on" if p in ph else ""}">{p[0]}</span>' for p in PH)
                imp = impacts.get(r['id'])
                if imp:
                    st = imp['status']
                    cls = f'b hit" style="--f:{FILL[st]};--e:{EDGE[st]}'
                    tag = f'<span class="tag">{TAG[st]}</span>'
                    note = f'<div class="bnote">{esc(str(imp["note"]))}</div>' if imp.get('note') else ''
                else:
                    cls, tag, note = 'b muted', '', ''
                parts.append(f'<div class="{cls}"><div class="bh"><span class="bid">{esc(str(r["id"]))}{tag}</span><span>{chips}</span></div>'
                             f'<div class="bn">{esc(str(r["name"]))}</div><div class="bd">{esc(str(r.get("description") or ""))}</div>'
                             f'<div class="bw"><b>When: </b>{esc(str(r.get("when_exercised") or ""))}</div>{note}</div>')
            for p in props:
                parts.append(f'<div class="b prop" style="--e:{EDGE["missing"]}"><div class="bh"><span class="bid">PROPOSED<span class="tag">MISSING</span></span></div>'
                             f'<div class="bn">{esc(str(p.get("name", "(unnamed)")))}</div><div class="bd">{esc(str(p.get("note", "")))}</div>'
                             f'<div class="bw">Not on the capability map — raise a capability-map delta.</div></div>')
            parts.append('</div></div>')
            if k == 0:
                parts.append('</div>')
        parts.append('</div>')
    extra = ''
    if unresolved or notes:
        extra = ('<div class="panel">' + (f'<b>Unresolved IDs (not rendered):</b> {esc(", ".join(unresolved))}<br>' if unresolved else '')
                 + (f'<b>Resolved:</b> {esc("; ".join(notes))}' if notes else '') + '</div>')
    title = inp.get('title') or 'Capability impact'
    date = inp.get('date') or datetime.date.today().isoformat()
    top = (f'<div class="top"><div><h1>{esc(title)}</h1><div class="sub">{esc(str(inp.get("use_case", "")))} · Technology capability impact · '
           f'{len(impacts) + len(proposed)} of {total} L3s impacted · {cnt["new"]} new · {cnt["consumed"] + cnt["updated"]} consumed or updated · '
           f'{cnt["missing"]} missing · {date}</div>{extra}</div>'
           f'<div class="legend"><span class="sw" style="background:{FILL["missing"]};border-color:{EDGE["missing"]}">Red · missing</span> required, nothing provides it '
           f'<span class="sw" style="background:{FILL["new"]};border-color:{EDGE["new"]}">Green · new</span> introduced by the solution '
           f'<span class="sw" style="background:{FILL["consumed"]};border-color:{EDGE["consumed"]}">Amber · C consumed / U updated</span> existing, reused or changed. '
           f'Faded blocks are not impacted. Red dashed blocks are proposed capabilities not yet on the map. Phase chips: D Design · B Build · R Run · O Operate.</div></div>')
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body>{top}<div class="cols">{"".join(parts)}</div>'
            f'<div class="foot"><span>CAFÉ technology capability map {esc(str(version))} · capability impact heatmap</span>'
            f'<span>Statuses supplied by the capability-match step (E0.3)</span></div></body></html>')


def render(data, inp, *, scale=1.0, cols=6) -> dict:
    """The page, and what a caller reports: counts, and the ids that resolved to nothing."""
    tree, l3idx, l2idx, retired = build_model(data)
    impacts, proposed, notes, unresolved = resolve(inp, l3idx, l2idx, retired)
    html = page(tree, impacts, proposed, notes, unresolved, inp, data['tech']['version'], scale, cols)
    return {"html": html, "summary": {
        "map_version": data['tech']['version'], "impacted": len(impacts), "proposed": len(proposed),
        "by_status": {k: sum(1 for v in impacts.values() if v['status'] == k) for k in FILL},
        "unresolved": unresolved, "resolved_notes": notes}}
