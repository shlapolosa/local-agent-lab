"""Step 22's views: the CAFÉ logical reference architecture and physical reference implementation
(the H pattern — layers as rows, security and governance pillars) showing only a solution's scope.

Ported from the `cafe-scoped-reference-architecture` skill (CAFÉ skills bundle, 29 Sep 2026), minus
the workbook reader and the browser: `render(data, inp)` returns BOTH pages, each an SVG in HTML.
No RAG colours: only in-scope blocks are drawn, and a layer with nothing in scope collapses to a
labelled strip. Model providers keep their residency lanes, because where a model runs is
architecturally significant.

`inp`: `{"use_case", "title", "date", "components": [cmp-… | code], "building_blocks"?: [...],
"pattern"?: "P1".."P5", "ghost"?: bool}`. Logical building blocks are DERIVED from the components
through the catalogue's component → building-block column.

The layout picks its design width by mutating the module's `W`, as the skill does. A lock makes
that safe in a long-lived server rather than rewriting every drawing function around a parameter.
"""
from __future__ import annotations

import datetime
import math
import re
import threading

from lab.core.usecase.views.common import esc

__all__ = ["render"]

_LOCK = threading.Lock()

L1COL = {"BUS": "#8a5a00", "SEM": "#2f6f4f", "KNW": "#0f766e", "COG": "#5b3fa3", "MOD": "#7a3fa3", "APP": "#1f5fa8",
         "DAT": "#2d5d8a", "TEC": "#475569", "XCT": "#9f2f4f", "RCV": "#8a3ffc", "PPL": "#b4530e", "BND": "#6b5a44"}
ZCOL = {'SEC': '#b91c1c', 'GOV': '#9f2f4f', 'EX': '#8a3ffc', 'GW': '#475569', 'AG': '#5b3fa3', 'KN': '#0f766e', 'TL': '#1f5fa8',
        'MP': '#7a3fa3', 'DT': '#2d5d8a', 'BN': '#9a7a5a', 'ME': '#7a3fa3', 'PF': '#64748b'}
PHYS_TITLE = {'SEC': 'Security pillar', 'GOV': 'Governance & assurance pillar', 'EX': 'Experience & received agents', 'GW': 'Edge & AI gateway',
              'AG': 'Agent plane', 'KN': 'Knowledge & semantic', 'TL': 'Tools, actions & integration', 'MP': 'Model providers by residency',
              'DT': 'Data', 'BN': 'Boundary — traditional systems', 'ME': 'Model engineering', 'PF': 'Platform foundation'}
LOG_TITLE = {'SEC': 'Security pillar', 'GOV': 'Governance & assurance pillar', 'EX': 'Layer 1 · Experience & access', 'GW': 'Layer 2 · Access & mediation',
             'AG': 'Layer 3 · Agent plane', 'KN': 'Layer 4 · Knowledge services', 'TL': 'Layer 4 · Tool services', 'MP': 'Layer 4 · Model services',
             'DT': 'Layer 5 · Data', 'BN': 'Layer 5 · Integration & traditional systems', 'ME': 'Layer 5 · Model engineering', 'PF': 'Foundation'}
PZONE = {'ex': 'EX', 'gw': 'GW', 'ag': 'AG', 'kn': 'KN', 'tl': 'TL', 'mp': 'MP', 'dt': 'DT', 'bn': 'BN', 'me': 'ME', 'sec': 'SEC', 'gov': 'GOV', 'pf': 'PF'}
AZONE = {'EX': 'EX', 'GW': 'GW', 'AG': 'AG', 'KS': 'KN', 'TS': 'TL', 'MS': 'MP', 'DS': 'DT', 'IN': 'BN', 'ME': 'ME', 'SC': 'SEC', 'GV': 'GOV', 'FD': 'PF'}
BCOL = {'Device': '#6b7280', 'Tenant · UAE': '#1f5fa8', 'In-country sovereign': '#0f766e', 'Out-of-region': '#b91c1c', 'On-premises': '#9a7a5a'}
ROWS = [['EX'], ['GW'], ['AG'], ['KN', 'TL', 'MP'], ['DT', 'BN', 'ME']]
FLOWS = [('EX', 'GW', 'all AI traffic'), ('GW', 'AG', 'requests'), ('AG', 'GW', 'model calls via gateway'), ('GW', 'MP', 'model call → sensitive-data decision → lane'),
         ('AG', 'KN', 'retrieve'), ('AG', 'TL', 'act'), ('TL', 'BN', 'integrate'), ('KN', 'DT', 'read'), ('TL', 'DT', 'write'), ('ME', 'MP', 'publish models')]
PAGES = {'a4': (297, 210), 'a3': (420, 297), 'a0': (1189, 841)}
W = 400.0                    # design width (units); the SVG scales uniformly to the page
M, PW, GAP, HDR, STRIP = 6.0, 64.0, 4.0, 6.5, 7.0
FS = {'name': 3.3, 'body': 2.5, 'mono': 2.1, 'small': 2.1, 'hdr': 3.2}


def wrap(txt, w, fs, f=0.56):
    n = max(6, int(w / (fs * f))); out, cur = [], ''
    for word in str(txt).split():
        if len(cur) + len(word) + 1 > n and cur: out.append(cur); cur = word
        else: cur = (cur + ' ' + word).strip()
    if cur: out.append(cur)
    return out


class SVG:
    def __init__(s): s.p = []
    def t(s, x, y, txt, fs, wt='400', col='#1c2330', anchor='start', fam='DejaVu Sans', it=False, op=1):
        s.p.append(f'<text x="{x:.2f}" y="{y:.2f}" font-family="{fam}" font-size="{fs:.2f}" font-weight="{wt}" fill="{col}" '
                   f'text-anchor="{anchor}"{" font-style=\"italic\"" if it else ""} opacity="{op}">{esc(str(txt))}</text>')
    def r(s, x, y, w, h, fill='#fff', stroke='#b8c2cf', sw=0.3, rx=1.2, dash=None, op=1):
        s.p.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"'
                   f'{" stroke-dasharray=\"" + dash + "\"" if dash else ""} opacity="{op}"/>')


def glyph(status):
    s = str(status or '')
    return '✓' if s.startswith('green') else '⚠' if s.startswith('amber') else '✕' if s.startswith('red') else '◆' if s.startswith('sovereign') else '•'


# ---------------------------------------------------------------- box content (measure == draw)
def phys_lines(c, w, ghost):
    L = [('hdr', f'{c["code"]} ▸ {c["building_block"]}')]
    L += [('name', ln) for ln in wrap(c['name'], w - 4, FS['name'], 0.6)[:2]]
    if not ghost:
        L += [('body', ln) for ln in wrap(c.get('detail') or '', w - 4, FS['body'])[:3]]
        L += [('mono', ln) for ln in wrap(c.get('l3') or '', w - 4, FS['mono'])[:2]]
        st = str(c.get('uae_north_status') or '')
        if st: L += [('small', ln) for ln in wrap(f'{glyph(st)} {st.split(" — ")[-1]}', w - 4, FS['small'])[:3]]
    return L


def abb_lines(a, w, ghost, l2name):
    L = [('hdr', a['id'])]
    L += [('name', ln) for ln in wrap(a['name'], w - 4, FS['name'], 0.6)[:2]]
    if not ghost:
        L += [('body', ln) for ln in wrap(a.get('responsibility') or '', w - 4, FS['body'])[:3]]
        for l2 in [s.strip() for s in str(a.get('l2') or '').split(';') if s.strip()]:
            L.append(('chip', l2))
    return L


LH = {'hdr': 3.0, 'name': 3.7, 'body': 2.95, 'mono': 2.6, 'small': 2.6, 'chip': 3.1}


def box_h(lines): return 2.2 + sum(LH[k] for k, _ in lines) + 1.2


def draw_box(g, x, y, w, h, lines, col, ghost, badge=None, l2name=None):
    op = 0.3 if ghost else 1
    g.r(x, y, w, h, '#fff', '#b8c2cf', 0.3, 1.0, dash='1.2 0.8' if ghost else None, op=op)
    if not ghost: g.p.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="1.1" height="{h:.2f}" fill="{col}"/>')
    yy = y + 2.2
    for k, txt in lines:
        yy += LH[k]
        if k == 'hdr':
            g.t(x + 2.4, yy - 0.6, txt, FS['mono'], '700', col if not ghost else '#6b7280', fam='DejaVu Sans Mono', op=op)
        elif k == 'name': g.t(x + 2.4, yy - 0.6, txt, FS['name'], '700', op=op)
        elif k == 'body': g.t(x + 2.4, yy - 0.6, txt, FS['body'], '400', '#374151')
        elif k == 'mono': g.t(x + 2.4, yy - 0.6, txt, FS['mono'], '400', '#5b3fa3', fam='DejaVu Sans Mono')
        elif k == 'small': g.t(x + 2.4, yy - 0.6, txt, FS['small'], '400', '#6b7280', it=True)
        elif k == 'chip':
            c2 = L1COL.get(txt.split('-')[0], '#475569'); tw = len(txt) * 1.25 + 1.8
            g.p.append(f'<rect x="{x+2.4:.2f}" y="{yy-2.7:.2f}" width="{tw:.2f}" height="2.5" rx="0.5" fill="{c2}"/>')
            g.t(x + 2.4 + tw / 2, yy - 0.8, txt, 1.8, '700', '#fff', 'middle', 'DejaVu Sans Mono')
            nm = (l2name or {}).get(txt, '')
            room = int((w - tw - 6) / (2.0 * 0.55))
            g.t(x + 3.6 + tw, yy - 0.75, nm if len(nm) <= room else nm[:max(3, room - 1)] + '…', 2.0, '400', '#374151')
    if badge and not ghost and w >= 50:
        bl, bc = badge; tw = len(bl) * 1.05 + 2
        g.r(x + w - tw - 1.5, y + 1.2, tw, 3.0, 'none', bc, 0.3, 0.6); g.t(x + w - tw / 2 - 1.5, y + 3.3, bl, 1.75, '700', bc, 'middle')


# ---------------------------------------------------------------- grid layout inside a zone
def grid_layout(items, zw, minw, measure):
    """Returns (height, placements[(item, dx, dy, w, h)]) for a zone of width zw."""
    n = len(items)
    if n == 0: return 0, []
    cols = max(1, min(n, int((zw - 4 + 2.5) // (minw + 2.5))))
    bw = (zw - 4 - (cols - 1) * 2.5) / cols
    place, dy = [], 0.0
    for r0 in range(0, n, cols):
        row = items[r0:r0 + cols]; hs = [box_h(measure(it, bw)) for it in row]; rh = max(hs)
        for j, it in enumerate(row): place.append((it, 2 + j * (bw + 2.5), dy, bw, rh))
        dy += rh + 2.5
    return dy - 2.5, place


class Layout:
    def __init__(s, items_by_zone, minw, measure, lanes=None):
        s.items, s.minw, s.measure, s.lanes = items_by_zone, minw, measure, lanes
        s.rect, s.place, s.collapsed = {}, [], set()

    def zone_content(s, z, zw):
        its = s.items.get(z, [])
        if z == 'MP' and s.lanes and its:
            return s.lane_content(its, zw)
        h, pl = grid_layout(its, zw, s.minw, s.measure)
        return (HDR + h + 2.5 if its else 0), pl

    def lane_content(s, its, zw):
        route = [c for c in its if s.lanes(c) == 'route']
        pl, dy = [], 0.0
        for c in route:
            h = box_h(s.measure(c, zw - 4)); pl.append((c, 2, dy, zw - 4, h)); dy += h + 2.5
        lanes = [('in', 'In-region · UAE North'), ('sov', 'Sovereign · Core42'), ('oor', 'Out-of-region · PHI-free')]
        groups = [(k, lab, [c for c in its if s.lanes(c) == k]) for k, lab in lanes]
        full = [g for g in groups if g[2]]; empty = [g for g in groups if not g[2]]
        ew = 20.0; avail = zw - 4 - ew * len(empty) - 2 * (len(groups) - 1)
        x, lane_h, lane_boxes = 2.0, 0.0, []
        for k, lab, cs in groups:
            lw = ew if not cs else avail / max(1, len(full))
            h, bl = grid_layout(cs, lw, s.minw * 0.8, s.measure)
            lane_boxes.append((lab, x, lw, bl)); lane_h = max(lane_h, h); x += lw + 2
        s.lane_frames = []
        for lab, lx, lw, bl in lane_boxes:
            s.lane_frames.append((lab, lx, dy, lw, lane_h + 5.5, bool(bl)))
            for (c, bx, by, bw, bh) in bl: pl.append((c, lx + bx - 2, dy + 5 + by, bw, bh))
        return HDR + dy + lane_h + 5.5 + 2.5, pl

    def solve(s, top):
        mx = M + PW + GAP; mw = W - 2 * M - 2 * PW - 2 * GAP; y = top; s.lane_frames_by = {}
        for row in ROWS:
            vis = [z for z in row if s.items.get(z)]
            if not vis:
                s.rect['/'.join(row)] = (mx, y, mw, STRIP); s.collapsed.update(row)
                for z in row: s.rect[z] = (mx, y, mw, STRIP)
                y += STRIP + GAP; continue
            if len(row) == 1:
                h, pl = s.zone_content(row[0], mw); s.rect[row[0]] = (mx, y, mw, h); s._keep(row[0], mx, y, pl); y += h + GAP; continue
            ew = 34.0; empty = [z for z in row if z not in vis]
            weights = {z: max(1, len(s.items[z])) for z in vis}; tot = sum(weights.values())
            avail = mw - ew * len(empty) - GAP * (len(row) - 1)
            widths = {z: (ew if z in empty else max(s.minw + 4, avail * weights[z] / tot)) for z in row}
            over = sum(widths.values()) + GAP * (len(row) - 1) - mw
            if over > 0:
                big = max(vis, key=lambda z: widths[z]); widths[big] -= over
            res = {z: s.zone_content(z, widths[z]) for z in vis}
            rh = max(res[z][0] for z in vis); x = mx
            for z in row:
                s.rect[z] = (x, y, widths[z], rh)
                if z in vis: s._keep(z, x, y, res[z][1])
                else: s.collapsed.add(z)
                x += widths[z] + GAP
            y += rh + GAP
        mid_bottom = y - GAP
        for z, px in (('SEC', M), ('GOV', W - M - PW)):
            h, pl = grid_layout(s.items.get(z, []), PW, PW - 4, s.measure)
            ph = max(mid_bottom - top, HDR + h + 2.5)
            s.rect[z] = (px, top, PW, ph)
            if s.items.get(z): s._keep(z, px, top, pl)
            else: s.collapsed.add(z)
        bottom = max(mid_bottom, s.rect['SEC'][1] + s.rect['SEC'][3], s.rect['GOV'][1] + s.rect['GOV'][3]) + GAP
        its = s.items.get('PF', [])
        if its:
            h, pl = grid_layout(its, W - 2 * M, s.minw, s.measure); ph = HDR + h + 2.5
            s.rect['PF'] = (M, bottom, W - 2 * M, ph); s._keep('PF', M, bottom, pl); bottom += ph + GAP
        else:
            s.rect['PF'] = (M, bottom, W - 2 * M, STRIP); s.collapsed.add('PF'); bottom += STRIP + GAP
        return bottom

    def _keep(s, z, x, y, pl):
        for (it, dx, dy, w, h) in pl: s.place.append((z, it, x + dx, y + HDR + dy, w, h))
        if z == 'MP' and getattr(s, 'lane_frames', None): s.lane_frames_by['MP'] = (x, y, s.lane_frames); s.lane_frames = None


def draw_frames(g, lay, titles):
    done = set()
    for row in ROWS + [['SEC'], ['GOV'], ['PF']]:
        key = '/'.join(row)
        if key in lay.rect and all(z in lay.collapsed for z in row) and len(row) > 1:
            x, y, w, h = lay.rect[key]
            g.r(x, y, w, h, '#f6f7f9', '#d1d5db', 0.3, 1.2, dash='1.5 1')
            g.t(x + 2, y + 4.6, ' · '.join(titles[z] for z in row) + ' — not in scope', 2.3, '700', '#9ca3af'); done.update(row); continue
        for z in row:
            if z in done: continue
            x, y, w, h = lay.rect[z]; done.add(z)
            if z in lay.collapsed:
                g.r(x, y, w, h, '#f6f7f9', '#d1d5db', 0.3, 1.2, dash='1.5 1')
                for j, ln in enumerate(wrap(titles[z] + ' — not in scope', w - 3, 2.1)[:3]): g.t(x + 1.8, y + 4.3 + j * 2.8, ln, 2.1, '700', '#9ca3af')
            else:
                col = ZCOL[z]
                g.r(x, y, w, h, '#fbfcfd', col, 0.45, 1.8)
                g.p.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{HDR-1:.2f}" rx="1.8" fill="{col}"/><rect x="{x:.2f}" y="{y+2.5:.2f}" width="{w:.2f}" height="{HDR-3.5:.2f}" fill="{col}"/>')
                g.t(x + 2, y + 3.9, titles[z], FS['hdr'] * 0.85, '700', '#fff')
    for z, (x, y, frames) in getattr(lay, 'lane_frames_by', {}).items():
        for lab, lx, ly, lw, lh, has in frames:
            g.r(x + lx, y + HDR + ly, lw, lh, '#f3f4f6' if not has else '#f8fafc', '#cbd5e1', 0.25, 1.0)
            for j, ln in enumerate(wrap(lab if has else lab + ' — none', lw - 2, 1.9)[:2]): g.t(x + lx + 1.2, y + HDR + ly + 2.9 + j * 2.4, ln, 1.9, '700', '#374151' if has else '#9ca3af')


def draw_flows(g, lay):
    g.p.insert(0, '<defs><marker id="ar" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="3.5" markerHeight="3.5" orient="auto"><path d="M0 0 L6 3 L0 6 z" fill="#1c2330"/></marker></defs>')
    vis = lambda z: z in lay.rect and z not in lay.collapsed
    def path(pts, lab, lx, ly, dash=False):
        d = 'M ' + ' L '.join(f'{a:.2f} {b:.2f}' for a, b in pts)
        g.p.append(f'<path d="{d}" fill="none" stroke="#1c2330" stroke-width="0.45"{" stroke-dasharray=\"1.5 1\"" if dash else ""} marker-end="url(#ar)"/>')
        if lab: g.t(lx, ly, lab, 1.9, '700', '#1c2330')
    for a, b, lab in FLOWS:
        if not (vis(a) and vis(b)): continue
        ax, ay, aw, ah = lay.rect[a]; bx, by, bw, bh = lay.rect[b]
        if (a, b) == ('GW', 'MP'):
            gx = ax + aw + 2.0
            path([(ax + aw, ay + ah / 2), (gx, ay + ah / 2), (gx, by + bh / 2), (bx + bw, by + bh / 2)], None, 0, 0)
            g.p.append(f'<text transform="rotate(90 {gx+1.2:.2f} {(ay+by+bh)/2:.2f})" x="{gx+1.2:.2f}" y="{(ay+by+bh)/2:.2f}" font-family="DejaVu Sans" font-size="1.8" font-weight="700" fill="#1c2330" text-anchor="middle">{esc(lab)}</text>')
            continue
        lo, hi = max(ax, bx), min(ax + aw, bx + bw)
        up = by < ay
        off = {('GW', 'AG'): -0.18, ('AG', 'GW'): 0.18}.get((a, b), 0)
        if hi - lo > 6:
            xm = (lo + hi) / 2 + off * (hi - lo)
            y1, y2 = (ay, by + bh) if up else (ay + ah, by)
            path([(xm, y1), (xm, y2)], lab, xm + 1.2, (y1 + y2) / 2 + 0.7)
        else:
            y1 = ay + ah; y2 = by; ym = (y1 + y2) / 2
            path([(ax + aw / 2, y1), (ax + aw / 2, ym), (bx + bw / 2, ym), (bx + bw / 2, y2)], lab, min(ax, bx) + 2, ym - 0.6)
    mids = [lay.rect[z] for z in ('EX', 'GW', 'AG') if vis(z)]
    ym = (mids[0][1] + mids[-1][1] + mids[-1][3]) / 2 if mids else None
    if ym:
        for z, (x0, x1) in (('SEC', (M + PW, M + PW + GAP)), ('GOV', (W - M - PW, W - M - PW - GAP))):
            if vis(z): path([(x0, ym), (x1, ym)], None, 0, 0, dash=True)


def lane_of(c):
    name = str(c.get('name', '')).lower(); st = str(c.get('uae_north_status', '')); con = str(c.get('constraint') or '').lower()
    if 'routing' in name or 'router' in str(c.get('detail', '')).lower(): return 'route'
    if st.startswith('sovereign'): return 'sov'
    if any(k in con + ' ' + str(c.get('detail', '')).lower() for k in ('out-of-region', 'non-uae', 'not pinned', 'non-resident', 'subprocessor', 'direct from')): return 'oor'
    return 'in'


def page_html(g, vb_h, page):
    pw, ph = PAGES.get(page, (297, 297 * vb_h / W)) if page != 'fit' else (297, 297 * vb_h / W)
    body = ''.join(g.p)
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>@page{{size:{pw}mm {ph:.1f}mm;margin:0}}html,body{{margin:0;background:#fff}}svg{{display:block}}</style></head>'
            f'<body><svg xmlns="http://www.w3.org/2000/svg" width="{pw}mm" height="{ph:.1f}mm" viewBox="0 0 {W} {vb_h:.2f}" preserveAspectRatio="xMidYMin meet">{body}</svg></body></html>'), (pw, ph)


def header(g, title, sub, lines):
    g.t(M, 8, title, 6.2, '700'); g.t(M, 12.6, sub, 2.4, '400', '#4b5563')
    for j, ln in enumerate(lines): g.t(M, 16.4 + j * 3.1, ln, 2.1, '400', '#374151')
    top = 16.4 + len(lines) * 3.1
    g.p.append(f'<line x1="{M}" y1="{top:.2f}" x2="{W-M}" y2="{top:.2f}" stroke="#1c2330" stroke-width="0.5"/>')
    return top + 2.5


def physical(data, scope, inp, ghost, page):
    comps = data['ra']['tables']['reference-architecture-components']
    items = {}
    for c in comps:
        if ghost or c['id'] in scope: items.setdefault(PZONE[c['zone']], []).append(c)
    g = SVG()
    top = header(g, inp.get('title') or 'Solution scope',
                 f'{inp.get("use_case", "")} · Physical reference implementation — solution scope · {len(scope)} of {len(comps)} components · {inp.get("date") or datetime.date.today().isoformat()}',
                 ['Only in-scope components are shown' + ('; out-of-scope components are ghosted.' if ghost else '; layers with nothing in scope collapse to a labelled strip.'),
                  'Box: component ▸ building block · name · product · L3 IDs · UAE North availability (✓ available · ⚠ partial/preview · ✕ not available · ◆ sovereign).'])
    measure = lambda c, w: phys_lines(c, w, ghost and c['id'] not in scope)
    lay = Layout(items, 56, measure, lanes=lane_of); bottom = lay.solve(top)
    draw_frames(g, lay, PHYS_TITLE)
    for z, c, x, y, w, h in lay.place:
        gh = ghost and c['id'] not in scope
        draw_box(g, x, y, w, h, phys_lines(c, w, gh), ZCOL[z], gh)
    draw_flows(g, lay)
    g.t(W - M, bottom + 1.5, f'CAFÉ physical reference implementation {data["ra"]["version"]} · solution scope view', 1.9, '400', '#6b7280', 'end')
    return page_html(g, bottom + 3.5, page)


def logical(data, abbs, inp, ghost, page):
    t = data['ra']['tables']; A = t['logical-building-blocks']
    l2name = {r['id']: r['name'] for r in data['tech']['tables']['technology-capability-l2']}
    items = {}
    for a in A:
        if ghost or a['id'] in abbs: items.setdefault(AZONE[re.match(r'[A-Z]+', a['id']).group(0)], []).append(a)
    pat = inp.get('pattern'); prow = next((p for p in t.get('reference-architecture-patterns', []) if p['id'] == pat), None)
    g = SVG()
    lines = ['Only in-scope building blocks are shown' + ('; out-of-scope blocks are ghosted.' if ghost else '; layers with nothing in scope collapse to a labelled strip.'),
             'Box: building block · trust boundary · name · responsibility · L2 capabilities realised (colour = L1 domain).']
    if prow: lines.append(f'Pattern {prow["id"]} · {prow["name"]}: {prow["path"]}')
    top = header(g, inp.get('title') or 'Solution scope',
                 f'{inp.get("use_case", "")} · Logical reference architecture — solution scope · {len(abbs)} of {len(A)} building blocks · {inp.get("date") or datetime.date.today().isoformat()}', lines)
    measure = lambda a, w: abb_lines(a, w, ghost and a['id'] not in abbs, l2name)
    lay = Layout(items, 62, measure); bottom = lay.solve(top)
    draw_frames(g, lay, LOG_TITLE)
    for z, a, x, y, w, h in lay.place:
        gh = ghost and a['id'] not in abbs
        bd = str(a.get('trust_boundary') or '')
        draw_box(g, x, y, w, h, abb_lines(a, w, gh, l2name), ZCOL[z], gh, badge=(bd, BCOL.get(bd, '#6b7280')), l2name=l2name)
    draw_flows(g, lay)
    pr = t.get('reference-architecture-principles', [])
    if pr:
        cw = (W - 2 * M) / 5; ph = 2 * 7.2 + 5
        g.r(M, bottom, W - 2 * M, ph, '#f8fafc', '#cbd5e1', 0.25, 1.2); g.t(M + 1.5, bottom + 3.2, 'Architecture principles and constraints', 2.2, '700')
        for j, p in enumerate(pr[:10]):
            x = M + 1.5 + (j % 5) * cw; y = bottom + 6.2 + (j // 5) * 7.2
            g.t(x, y, f'{j+1}.', 1.9, '700', '#5b3fa3')
            for m, ln in enumerate(wrap(p['principle'], cw - 5, 1.8)[:3]): g.t(x + 3, y + m * 2.2, ln, 1.8, '400', '#1f2937')
        bottom += ph + 2
    g.t(W - M, bottom + 1.5, f'CAFÉ logical reference architecture {data["ra"]["version"]} · solution scope view', 1.9, '400', '#6b7280', 'end')
    return page_html(g, bottom + 3.5, page)


def render(data, inp, *, page='a4', ghost=None) -> dict:
    """Both scoped views, `{"logical": html, "physical": html}`, and what a caller reports."""
    t = data['ra']['tables']; comps = t['reference-architecture-components']
    by_code = {c['code']: c['id'] for c in comps if c.get('code')}; by_id = {c['id']: c for c in comps}
    retired = {r['id']: re.match(r'([A-Z]{2,3}-\d{2})', str(r['resolves_to'] or '')) for r in t.get('reference-architecture-retired-components', [])}
    scope, notes, unresolved = set(), [], []
    for ref in inp.get('components', []):
        ref = str(ref).strip()
        if ref in by_id: scope.add(ref)
        elif ref in by_code: scope.add(by_code[ref])
        elif ref in retired and retired[ref] and retired[ref].group(1) in by_code:
            scope.add(by_code[retired[ref].group(1)]); notes.append(f'{ref} retired — shown as {retired[ref].group(1)}')
        else: unresolved.append(ref)
    abb_ids = {x['id'] for x in t['logical-building-blocks']}
    abbs = {by_id[c]['building_block'] for c in scope if by_id[c].get('building_block')} | {b for b in inp.get('building_blocks', []) if b in abb_ids}
    unresolved += [b for b in inp.get('building_blocks', []) if b not in abb_ids]
    ghost = bool(inp.get('ghost')) if ghost is None else ghost

    def best(fn, *args):
        # choose the design width whose content aspect best fills the page (less empty canvas)
        global W
        target = (PAGES[page][1] / PAGES[page][0]) if page in PAGES else None
        if not target:
            W = 400.0; return fn(*args)
        cands = []
        for w in (400.0, 380.0, 360.0, 340.0, 320.0, 300.0, 285.0, 270.0):
            W = w; res = fn(*args); vb_h = float(re.search(r'viewBox="0 0 [\d.]+ ([\d.]+)"', res[0]).group(1))
            cands.append((abs(vb_h / w - target) + (0.5 if vb_h / w > target * 1.02 else 0), w, res))
        sc, w, res = min(cands, key=lambda c: c[0]); W = w
        return res

    with _LOCK:
        pages = {view: best(fn, data, which, inp, ghost, page)[0]
                 for view, fn, which in (('logical', logical, abbs), ('physical', physical, scope))}
    return {"pages": pages, "summary": {
        "ra_version": data['ra']['version'], "components_in_scope": len(scope),
        "building_blocks_in_scope": sorted(abbs), "unresolved": unresolved, "resolved_notes": notes}}
