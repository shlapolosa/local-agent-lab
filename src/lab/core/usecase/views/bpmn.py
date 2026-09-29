"""Step 10's view: the workflow as a BPMN-style flow whose tasks are L3 capabilities.

Ported from the `cafe-bpmn-flow` skill (CAFÉ skills bundle, 29 Sep 2026), minus the browser:
`render(spec, l3=...)` returns the page (an SVG in HTML). Swimlanes, tasks labelled with their
capability, exclusive/parallel gateways, start and end events, sequence and message flows, and
optional MVP → transitional → target phase colouring.

`spec`: `{"title", "lanes": [{id, label}], "phases"?: {...}, "nodes": [{id, type, lane, name?,
cap?, note?, phase?, col?, row?, kind?, label?, text?, span?}], "edges": [{from, to, type?, label?,
route?}]}` — see the skill's SKILL.md for the full contract. `l3` maps an L3 id to its row, so a
task naming only `cap` is labelled from the pinned map. The skill's author builds the spec by hand;
here the pipeline derives it from step 10's graph (`lab.workloads.usecase.views`).
"""
from __future__ import annotations

import copy
import html
import re

from lab.core.usecase.views.common import ViewError

__all__ = ["render"]

esc = html.escape

#: A message flow's colour lands in an SVG ATTRIBUTE, where escaping text is not enough: a caller's
#: `"/><script>` would close the attribute. So a colour is a hex colour or it is the default.
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}")


def _colour(value, default="#b3261e") -> str:
    return value if isinstance(value, str) and _HEX.fullmatch(value) else default

PHASE = {'mvp': ('#e9e7e1', '#5f5a50'), 'transitional': ('#f8d79b', '#a86b00'), 'target': ('#f0b2a8', '#b3261e'), None: ('#ffffff', '#6b7280')}
LANE_TINT = ['#fbfaf6', '#f6f4fd', '#f1f9f6', '#f4f8fc', '#fcf6f3', '#f7f7f7']
CW, RH, LBL, X0, TOP = 205.0, 104.0, 40.0, 12.0, 70.0
TW, TH, GW, ER = 168.0, 58.0, 50.0, 14.0


def auto_layout(spec):
    nodes = {n['id']: n for n in spec['nodes']}
    succ = {}
    for e in spec.get('edges', []):
        if e.get('type', 'sequence') == 'sequence': succ.setdefault(e['from'], []).append(e['to'])
    depth = {}
    msg_src = {}
    for e in spec.get('edges', []):
        if e.get('type', 'sequence') != 'sequence': msg_src.setdefault(e['to'], []).append(e['from'])
    targets = {t for v in succ.values() for t in v}
    starts = [n for n in nodes if n not in targets and n not in msg_src] or list(nodes)
    frontier = [(s, 0) for s in starts]
    while frontier:
        nid, d = frontier.pop(0)
        if depth.get(nid, -1) >= d or d > len(nodes): continue
        depth[nid] = d
        frontier += [(t, d + 1) for t in succ.get(nid, [])]
    for _ in range(3):   # nodes reached only by message flows sit under their source's column
        for nid in nodes:
            if nid not in depth and nid in msg_src:
                src = [depth.get(m) for m in msg_src[nid] if m in depth or 'col' in nodes[m]]
                src = [d if d is not None else nodes[m]['col'] for d, m in zip(src, msg_src[nid])]
                if src:
                    depth[nid] = min(src); fr = [(t, depth[nid] + 1) for t in succ.get(nid, [])]
                    while fr:
                        t, d = fr.pop(0)
                        if depth.get(t, -1) < d <= len(nodes): depth[t] = d; fr += [(u, d + 1) for u in succ.get(t, [])]
    used = {}
    for n in spec['nodes']:
        if 'col' not in n: n['col'] = depth.get(n['id'], 0)
        if 'row' not in n:
            r = 0
            while (n['lane'], n['col'], r) in used: r += 1
            n['row'] = r
        used[(n['lane'], n['col'], n['row'])] = n['id']


def geometry(spec):
    lanes = spec['lanes']; rows = {l['id']: 1 for l in lanes}
    nodes_lane = {n['id']: n['lane'] for n in spec['nodes']}
    for n in spec['nodes']: rows[n['lane']] = max(rows[n['lane']], int(n.get('row', 0)) + 1)
    y, ly = TOP, {}
    for l in lanes:
        extra = 30 if any(e.get('route') == 'below' and nodes_lane.get(e['from']) == l['id'] for e in spec.get('edges', [])) else 0
        h = rows[l['id']] * RH + 14 + extra; ly[l['id']] = (y, h); y += h
    maxcol = max(float(n['col']) + float(n.get('span', 1)) for n in spec['nodes'])
    width = X0 + LBL + 20 + maxcol * CW + 20
    for n in spec['nodes']:
        top, _ = ly[n['lane']]
        cx = X0 + LBL + 20 + float(n['col']) * CW + CW / 2
        cy = top + 7 + float(n.get('row', 0)) * RH + RH / 2
        t = n['type']
        if t == 'task': w, h = TW, TH
        elif t == 'gateway': w, h = GW, GW
        elif t in ('start', 'end', 'intermediate'): w, h = 2 * ER, 2 * ER
        elif t == 'annotation':
            span = float(n.get('span', 2)); w, h = span * CW - 30, RH - 28; cx = X0 + LBL + 20 + float(n['col']) * CW + span * CW / 2
        else: w, h = TW, TH
        n['_b'] = (cx - w / 2, cy - h / 2, w, h, cx, cy)
    return ly, width, y


def ports(n):
    x, y, w, h, cx, cy = n['_b']
    return {'left': (x, cy), 'right': (x + w, cy), 'top': (cx, y), 'bottom': (cx, y + h)}


def route(s, t, mode, off):
    ps, pt = ports(s), ports(t)
    sx, sy = s['_b'][4], s['_b'][5]; tx, ty = t['_b'][4], t['_b'][5]
    if mode == 'auto':
        if abs(sy - ty) < 1: mode = 'h'
        elif abs(sx - tx) < 1: mode = 'v'
        elif s['lane'] == t['lane']: mode = 'vh'
        else: mode = 'hv'
    if mode == 'h': return [ps['right'], pt['left']] if tx > sx else [ps['left'], pt['right']]
    if mode == 'v': return [ps['bottom'], pt['top']] if ty > sy else [ps['top'], pt['bottom']]
    if mode == 'hv':
        a = ps['right'] if tx > sx else ps['left']; b = pt['top'] if ty > sy else pt['bottom']
        return [a, (b[0], a[1]), b]
    if mode == 'vh':
        a = ps['bottom'] if ty > sy else ps['top']; b = pt['left'] if tx > sx else pt['right']
        return [a, (a[0], b[1]), b]
    if mode == 'vhv':
        a = ps['bottom'] if ty > sy else ps['top']; b = pt['top'] if ty > sy else pt['bottom']
        my = (a[1] + b[1]) / 2 + off
        return [a, (a[0], my), (b[0], my), b]
    if mode == 'hvh':
        a = ps['right'] if tx > sx else ps['left']; b = pt['left'] if tx > sx else pt['right']
        mx = (a[0] + b[0]) / 2 + off
        return [a, (mx, a[1]), (mx, b[1]), b]
    if mode in ('below', 'above'):
        k = 'bottom' if mode == 'below' else 'top'; a, b = ps[k], pt[k]
        yy = (max(a[1], b[1]) + 14 + off) if mode == 'below' else (min(a[1], b[1]) - 14 - off)
        return [a, (a[0], yy), (b[0], yy), b]
    if mode == 'right':
        a, b = ps['right'], pt['right']; xx = max(a[0], b[0]) + 24 + off
        return [a, (xx, a[1]), (xx, b[1]), b]
    raise ValueError(f'unknown route {mode}')


def wrap(txt, n):
    out, cur = [], ''
    for w in str(txt).split():
        if len(cur) + len(w) + 1 > n and cur: out.append(cur); cur = w
        else: cur = (cur + ' ' + w).strip()
    if cur: out.append(cur)
    return out


def draw(spec, l3):
    for n in spec['nodes']:
        cap = str(n.get('cap') or '')
        if n['type'] == 'task' and cap in l3 and not n.get('name'): n['name'] = l3[cap]['name']
    auto_layout(spec)
    ly, width, height = geometry(spec)
    nodes = {n['id']: n for n in spec['nodes']}
    phases = spec.get('phases') or {}
    legend_h = 40 if phases else 10
    H = height + legend_h + 20
    o = [f'<rect width="{width}" height="{H}" fill="#fff"/>',
         '<defs><marker id="seq" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10 Z" fill="#1c2330"/></marker>'
         '<marker id="msg" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0 L10 5 L0 10" fill="none" stroke="#b3261e" stroke-width="1.4"/></marker>'
         '<marker id="mst" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6"><circle cx="5" cy="5" r="3.5" fill="#fff" stroke="#b3261e" stroke-width="1.2"/></marker></defs>']
    o.append(f'<text x="{width/2}" y="34" font-family="DejaVu Sans" font-size="19" font-weight="700" fill="#1c2330" text-anchor="middle">{esc(spec.get("title",""))}</text>')
    if spec.get('subtitle'):
        o.append(f'<text x="{width/2}" y="54" font-family="DejaVu Sans" font-size="11" fill="#4b5563" text-anchor="middle">{esc(spec["subtitle"])}</text>')
    for k, l in enumerate(spec['lanes']):
        y, h = ly[l['id']]
        o.append(f'<rect x="{X0}" y="{y}" width="{width-X0-8}" height="{h}" fill="{LANE_TINT[k % len(LANE_TINT)]}" stroke="#6b7280" stroke-width="0.9"/>')
        o.append(f'<rect x="{X0}" y="{y}" width="{LBL}" height="{h}" fill="#fff" stroke="#6b7280" stroke-width="0.9"/>')
        o.append(f'<text x="{X0+LBL/2+4}" y="{y+h/2}" transform="rotate(-90 {X0+LBL/2+4} {y+h/2})" font-family="DejaVu Sans" font-size="11.5" font-weight="700" fill="#4b5563" text-anchor="middle">{esc(l["label"])}</text>')
    # edges first so nodes sit on top
    for e in spec.get('edges', []):
        s, t = nodes[e['from']], nodes[e['to']]
        pts = route(s, t, e.get('route', 'auto'), float(e.get('offset', 0)))
        d = 'M ' + ' L '.join(f'{a:.1f} {b:.1f}' for a, b in pts)
        typ = e.get('type', 'sequence')
        if typ == 'message':
            col = _colour(e.get('color'))
            o.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="1.3" stroke-dasharray="6 4" marker-end="url(#msg)" marker-start="url(#mst)"/>')
        elif typ == 'association':
            o.append(f'<path d="{d}" fill="none" stroke="#6b7280" stroke-width="1" stroke-dasharray="2 3"/>'); col = '#6b7280'
        else:
            col = '#1c2330'
            o.append(f'<path d="{d}" fill="none" stroke="#1c2330" stroke-width="1.3" marker-end="url(#seq)"/>')
        if e.get('label'):
            segs = list(zip(pts, pts[1:])); a, b = max(segs, key=lambda sg: abs(sg[0][0] - sg[1][0]) + abs(sg[0][1] - sg[1][1]))
            if e.get('label_at') == 'start': a, b = segs[0]
            if e.get('label_at') == 'end': a, b = segs[-1]
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            horiz = abs(a[1] - b[1]) < 1
            seg = abs(a[0] - b[0]) if horiz else 180
            lines = wrap(e['label'], max(14, int(seg / 6.0) - 2))
            under = e.get('label_side') == 'below' or (e.get('route') == 'below' and e.get('label_side') != 'above')
            for j, ln in enumerate(lines):
                if horiz and under:
                    o.append(f'<text x="{mx}" y="{my + 12 + j*11}" font-family="DejaVu Sans" font-size="9.5" fill="{col if typ=="message" else "#4b5563"}" text-anchor="middle">{esc(ln)}</text>')
                elif horiz:
                    o.append(f'<text x="{mx}" y="{my - 6 - (len(lines)-1-j)*11}" font-family="DejaVu Sans" font-size="9.5" fill="{col if typ=="message" else "#4b5563"}" text-anchor="middle">{esc(ln)}</text>')
                else:
                    o.append(f'<text x="{mx + 6}" y="{my + 3 + j*11}" font-family="DejaVu Sans" font-size="9.5" fill="{col if typ=="message" else "#4b5563"}">{esc(ln)}</text>')
    for n in spec['nodes']:
        x, y, w, h, cx, cy = n['_b']; t = n['type']; fill, stroke = PHASE.get(n.get('phase'), PHASE[None])
        if t == 'task':
            o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="{fill if n.get("phase") else "#e9e7e1"}" stroke="{stroke if n.get("phase") else "#5f5a50"}" stroke-width="1.3"/>')
            nm = wrap(n.get('name', n['id']), 21); sub = ' · '.join(x for x in [str(n.get('cap') or ''), str(n.get('note') or '')] if x)
            total = len(nm) * 13 + (12 if sub else 0); ty = cy - total / 2 + 11
            for ln in nm[:2]:
                o.append(f'<text x="{cx}" y="{ty}" font-family="DejaVu Sans" font-size="11.5" font-weight="700" fill="#1c2330" text-anchor="middle">{esc(ln)}</text>'); ty += 13
            if sub: o.append(f'<text x="{cx}" y="{ty+1}" font-family="DejaVu Sans" font-size="9" fill="{stroke if n.get("phase") in ("transitional","target") else "#5f5a50"}" text-anchor="middle">{esc(sub[:40])}</text>')
        elif t == 'gateway':
            g_fill = fill if n.get('phase') else '#e9e7e1'; g_st = stroke if n.get('phase') else '#5f5a50'
            o.append(f'<path d="M{cx} {y} L{x+w} {cy} L{cx} {y+h} L{x} {cy} Z" fill="{g_fill}" stroke="{g_st}" stroke-width="1.3"/>')
            sym = {'exclusive': '×', 'parallel': '+', 'inclusive': '○', 'event': '⬠'}.get(n.get('kind', 'exclusive'), '×')
            o.append(f'<text x="{cx}" y="{cy+5}" font-family="DejaVu Sans" font-size="16" fill="{g_st}" text-anchor="middle">{sym}</text>')
            if n.get('label'):
                side = n.get('label_side', 'left'); lines = wrap(n['label'], 16)
                for j, ln in enumerate(lines):
                    if side == 'left': o.append(f'<text x="{x-6}" y="{cy - (len(lines)-1)*5.5 + j*11 + 3}" font-family="DejaVu Sans" font-size="9.5" fill="#4b5563" text-anchor="end">{esc(ln)}</text>')
                    elif side == 'right': o.append(f'<text x="{x+w+6}" y="{cy - (len(lines)-1)*5.5 + j*11 + 3}" font-family="DejaVu Sans" font-size="9.5" fill="{g_st}" text-anchor="start">{esc(ln)}</text>')
                    else: o.append(f'<text x="{cx}" y="{y-6-(len(lines)-1-j)*11}" font-family="DejaVu Sans" font-size="9.5" fill="#4b5563" text-anchor="middle">{esc(ln)}</text>')
        elif t == 'start':
            o.append(f'<circle cx="{cx}" cy="{cy}" r="{ER}" fill="#fff" stroke="#2f7d32" stroke-width="2"/>')
        elif t == 'end':
            o.append(f'<circle cx="{cx}" cy="{cy}" r="{ER}" fill="#fff" stroke="#b3261e" stroke-width="4"/>')
        elif t == 'intermediate':
            o.append(f'<circle cx="{cx}" cy="{cy}" r="{ER}" fill="#fff" stroke="#1c2330" stroke-width="1.3"/><circle cx="{cx}" cy="{cy}" r="{ER-3}" fill="none" stroke="#1c2330" stroke-width="1.3"/>')
        elif t == 'annotation':
            o.append(f'<path d="M{x+10} {y} L{x} {y} L{x} {y+h} L{x+10} {y+h}" fill="none" stroke="#6b7280" stroke-width="1.2"/>')
            lines = wrap(n.get('text', ''), int(w / 6.2))
            ty = cy - len(lines) * 6 + 9
            for ln in lines[:5]:
                o.append(f'<text x="{x+16}" y="{ty}" font-family="DejaVu Sans" font-size="10" fill="#4b5563">{esc(ln)}</text>'); ty += 12
    if phases:
        lx, yy = X0 + 40, height + 26
        for key in ('mvp', 'transitional', 'target'):
            if key not in phases: continue
            fill, stroke = PHASE[key]
            o.append(f'<rect x="{lx}" y="{yy-10}" width="26" height="16" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>')
            o.append(f'<text x="{lx+34}" y="{yy+2}" font-family="DejaVu Sans" font-size="10.5" fill="#1c2330">{esc(phases[key])}</text>')
            lx += 34 + len(phases[key]) * 6.4 + 50
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{H:.0f}" viewBox="0 0 {width:.1f} {H:.1f}">{"".join(o)}</svg>', width, H


def render(spec, *, l3=None) -> dict:
    """The page and the counts. Unknown lanes or node ids are refused by name, as the skill does."""
    spec = copy.deepcopy(spec)                  # the drawing annotates its nodes; not the caller's
    ids = [n['id'] for n in spec['nodes']]
    bad = [e for e in spec.get('edges', []) if e['from'] not in ids or e['to'] not in ids]
    lanes = {ln['id'] for ln in spec['lanes']}
    badl = [n['id'] for n in spec['nodes'] if n['lane'] not in lanes]
    if bad or badl:
        raise ViewError(f"unknown references — edges {bad}, nodes with an unknown lane {badl}")
    svg, w, h = draw(spec, l3 or {})
    tasks = [n for n in spec['nodes'] if n['type'] == 'task']
    page = (f'<!doctype html><html><head><meta charset="utf-8"><style>html,body{{margin:0}}'
            f'svg{{display:block}}</style></head><body>{svg}</body></html>')
    return {"html": page, "summary": {
        "tasks": len(tasks), "gateways": sum(n['type'] == 'gateway' for n in spec['nodes']),
        "by_phase": {k: sum(n.get('phase') == k for n in tasks) for k in ('mvp', 'transitional', 'target')},
        "size_px": [round(w), round(h)]}}
