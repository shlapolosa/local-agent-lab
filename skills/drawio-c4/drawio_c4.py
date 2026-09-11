"""drawio_c4.py — banded C4 solution-architecture diagrams as draw.io (mxGraph) diagram-as-code.

Declare full-width trust-zone BANDS (stacked top->down), the COMPONENTS inside each band (centred rows),
and typed EDGES. The engine lays everything out, then routes every edge with an A* orthogonal,
obstacle-avoiding router that enforces:
  * no two components overlap                       (H1)
  * no edge segment crosses a component box         (H2)
  * no diagonal segments — orthogonal only          (H3)
  * every edge leaves/enters a box with a vertical STUB before any bend
  * cross-band fan-in / fan-out collapse to a JUNCTION dot (many lines -> dot -> one line),
    centred on all connected items, drawn as a symmetric comb where clear
  * connectors meet boxes at top/bottom-centre; lanes are unique (no trunking)

Output is mxGraph XML, editable in https://app.diagrams.net. Pure-Python, no deps.

API:
    d = C4Diagram("Title", width=1820)
    d.zone("z1", "Layer label", stroke="#6C8EBF", fill="#EAF1FB", height=118, comp_fill="#DAE8FC")
    d.component("c1", "z1", "Name", "line1\\nline2", row=0)        # row=1 for a 2nd row in the band
    d.edge("c1", "c2", "sync")                                     # sync|async|xtrust|identity (+custom)
    d.legend([("Synchronous", "strokeColor=#1A1A1A;"), ...])
    open("out.drawio","w").write(d.render(strict=False))          # sets d.violations
"""
from xml.sax.saxutils import escape
from heapq import heappush, heappop
from collections import defaultdict

EDGE_STYLES = {
    "sync":     "strokeColor=#1A1A1A;endArrow=block;",
    "async":    "strokeColor=#777777;dashed=1;dashPattern=6 6;endArrow=open;",
    "xtrust":   "strokeColor=#B85450;strokeWidth=2;endArrow=block;",
    "identity": "strokeColor=#9966AA;dashed=1;dashPattern=2 4;endArrow=open;",
}
JUNCTION_COLORS = {"sync": "#1A1A1A", "async": "#777777", "xtrust": "#B85450", "identity": "#9966AA"}


class C4Diagram:
    GAP_BAND = 80          # vertical gap between bands
    STUB = 18              # vertical run before any bend
    PAD = 9               # clearance the router keeps off every box
    COMPH = 78            # default component height
    HPAD = 18             # band inner horizontal padding
    HGAP = 26             # gap between components in a row
    ROWGAP = 40           # gap between two rows inside a band
    MAXW = 300            # max component width (else centred)
    Y0 = 90              # first band top

    def __init__(self, title, width=1820, edge_styles=None, junction_colors=None):
        self.title = title; self.W = width
        self.ES = dict(EDGE_STYLES); self.ES.update(edge_styles or {})
        self.JC = dict(JUNCTION_COLORS); self.JC.update(junction_colors or {})
        self._zones = []          # (zid,label,stroke,fill,height,comp_fill,dashed,center)
        self._comps = []          # (cid,zid,title,desc,row,col,fill)
        self._edges = []          # (s,t,kind)
        self._legend = []
        self._systems = []        # (label, [zone_ids], color)       -- banded mode
        self._trust = []          # (label, after_zone, fill, stroke) -- banded mode
        self._security = {}       # zone_id -> note text              -- banded mode

    # ---------- declaration ----------
    def zone(self, zid, label, stroke="#666666", fill="#F5F5F5", height=120,
             comp_fill=None, dashed=True, center=False):
        self._zones.append((zid, label, stroke, fill, height, comp_fill or "#EEEEEE", dashed, center))
        return zid

    def component(self, cid, zid, title, desc="", row=0, col=None, fill=None):
        self._comps.append((cid, zid, title, desc, row, col, fill)); return cid

    def edge(self, s, t, kind):
        self._edges.append((s, t, kind)); return (s, t)

    def legend(self, items):
        self._legend = list(items)

    # ---------- banded-mode declarations (no effect on the A* render) ----------
    def system(self, label, zone_ids, color="#5A5A5A"):
        """A dotted boundary box that ENCOMPASSES the listed bands (a deployable system / trust zone)."""
        self._systems.append((label, list(zone_ids), color)); return label

    def trust_boundary(self, label, after_zone, fill="#FBE9A0", stroke="#C9A100"):
        """A gold dashed strip placed in an enlarged gap AFTER the named zone."""
        self._trust.append((label, after_zone, fill, stroke)); return label

    def security(self, zone_id, text):
        """A per-band security-context note rendered right-aligned in the band header."""
        self._security[zone_id] = text; return zone_id

    # ---------- layout ----------
    def _layout(self):
        ZX, ZW = 40, self.W - 80
        y = self.Y0; self.Z = {}
        for z in self._zones:
            zid = z[0]; self.Z[zid] = (z, ZX, y, ZW); y += z[4] + self.GAP_BAND
        self.canvas_bottom = y - self.GAP_BAND
        self.pos = {}
        rows = defaultdict(list)
        for c in self._comps: rows[(c[1], c[4])].append(c)
        for (zid, row), items in rows.items():
            items.sort(key=lambda c: (c[5] is None, c[5] if c[5] is not None else 0))
            _, _, zy, _ = self.Z[zid]
            n = len(items); cw = min(self.MAXW, (ZW - 2 * self.HPAD - (n - 1) * self.HGAP) // n)
            total = n * cw + (n - 1) * self.HGAP; startx = ZX + (ZW - total) // 2
            top = zy + 30 + row * (self.COMPH + self.ROWGAP)
            for k, c in enumerate(items):
                self.pos[c[0]] = (startx + k * (cw + self.HGAP), top, cw, self.COMPH)
        self.boxes = dict(self.pos)
        self._zcfg = {c[0]: c for c in self._comps}
        self.ZX, self.ZW = ZX, ZW

    # ---------- band index + junctions ----------
    def _band(self, c): return next(i for i, z in enumerate(self._zones) if z[0] == self._zcfg[c][1])

    def _build_junctions(self):
        fanin = defaultdict(list); fanout = defaultdict(list)
        for s, t, k in self._edges:
            if self._band(s) != self._band(t): fanin[(t, k)].append(s); fanout[(s, k)].append(t)
        ccx = lambda c: self.boxes[c][0] + self.boxes[c][2] / 2
        ccy = lambda c: self.boxes[c][1] + self.boxes[c][3] / 2
        gapY = sorted(self.Z[self._zones[i][0]][2] + self._zones[i][4] + self.GAP_BAND / 2
                      for i in range(len(self._zones) - 1))
        gapnear = lambda yy: min(gapY, key=lambda g: abs(g - yy))
        self.NE = []; self.JUN = {}; jc = 0; consumed = set()
        for (t, k), srcs in fanin.items():
            if len(srcs) >= 2:
                jid = f"jn{jc}"; jc += 1
                cx = sum(ccx(m) for m in srcs + [t]) / (len(srcs) + 1)
                cy = (sum(ccy(s) for s in srcs) / len(srcs) + ccy(t)) / 2
                self.JUN[jid] = (cx, gapnear(cy), k)
                for s in srcs: self.NE.append((s, jid, k)); consumed.add((s, t, k))
                self.NE.append((jid, t, k))
        for (s, k), tgts in fanout.items():
            rem = [t for t in tgts if (s, t, k) not in consumed]
            if len(rem) >= 2:
                jid = f"jn{jc}"; jc += 1
                cx = sum(ccx(m) for m in [s] + rem) / (len(rem) + 1)
                cy = (ccy(s) + sum(ccy(t) for t in rem) / len(rem)) / 2
                self.JUN[jid] = (cx, gapnear(cy), k)
                self.NE.append((s, jid, k))
                for t in rem: self.NE.append((jid, t, k)); consumed.add((s, t, k))
        for s, t, k in self._edges:
            if (s, t, k) not in consumed: self.NE.append((s, t, k))

    # ---------- anchors ----------
    def _anchor_side(self, comp, px, py):
        x, y, w, h = self.boxes[comp]; return 'B' if py >= y + h / 2 else 'T'

    def _fan_anchors(self):
        cxy = lambda e: (self.JUN[e][0], self.JUN[e][1]) if e in self.JUN else \
            (self.boxes[e][0] + self.boxes[e][2] / 2, self.boxes[e][1] + self.boxes[e][3] / 2)
        self.csides = {}; use = defaultdict(list)
        for k, (s, t, kind) in enumerate(self.NE):
            if s not in self.JUN:
                sd = self._anchor_side(s, *cxy(t)); self.csides[(k, 'S')] = sd; use[(s, sd)].append((k, 'S'))
            if t not in self.JUN:
                sd = self._anchor_side(t, *cxy(s)); self.csides[(k, 'T')] = sd; use[(t, sd)].append((k, 'T'))
        self.cfrac = {}
        for (comp, sd), lst in use.items():
            n = len(lst)
            for j, (k, role) in enumerate(lst): self.cfrac[(k, role)] = (j + 1) / (n + 1)

    def _anchor(self, k, role, e):
        if e in self.JUN: return (self.JUN[e][0], self.JUN[e][1])
        sd = self.csides[(k, role)]; f = self.cfrac[(k, role)]; x, y, w, h = self.boxes[e]
        return {'B': (x + f * w, y + h), 'T': (x + f * w, y)}[sd]

    # ---------- routing ----------
    def _astar(self, s, t, sa, ta):
        ign = {s, t}; P = self.PAD; B = self.boxes
        GUT_L, GUT_R = self.ZX - 26, self.ZX + self.ZW + 26
        xs = {GUT_L, GUT_R, 18, self.W - 18, sa[0], ta[0]}; ys = {60, self.canvas_bottom + 120, sa[1], ta[1]}
        for c, (bx, by, bw, bh) in B.items(): xs |= {bx - P, bx + bw + P}; ys |= {by - P, by + bh + P}
        for i in range(len(self._zones) - 1):
            ys.add(self.Z[self._zones[i][0]][2] + self._zones[i][4] + self.GAP_BAND / 2)
        xs = sorted(xs); ys = sorted(ys)
        xs = sorted(set(xs) | {(a + b) / 2 for a, b in zip(xs, xs[1:])})
        ys = sorted(set(ys) | {(a + b) / 2 for a, b in zip(ys, ys[1:])})
        xi = {v: i for i, v in enumerate(xs)}; yi = {v: i for i, v in enumerate(ys)}
        def hc(x1, x2, yy):
            lo, hi = min(x1, x2), max(x1, x2)
            for c, (bx, by, bw, bh) in B.items():
                if c in ign: continue
                if by - P + 1e-6 < yy < by + bh + P - 1e-6 and lo < bx + bw + P - 1e-6 and hi > bx - P + 1e-6: return False
            return True
        def vc(xx, y1, y2):
            lo, hi = min(y1, y2), max(y1, y2)
            for c, (bx, by, bw, bh) in B.items():
                if c in ign: continue
                if bx - P + 1e-6 < xx < bx + bw + P - 1e-6 and lo < by + bh + P - 1e-6 and hi > by - P + 1e-6: return False
            return True
        start, goal = (sa[0], sa[1]), (ta[0], ta[1])
        openq = [(0, start, None)]; best = {start: 0}; came = {}
        while openq:
            f, cur, pd = heappop(openq)
            if cur == goal: break
            cx, cy = cur; ix, iy = xi[cx], yi[cy]; nb = []
            if ix + 1 < len(xs) and hc(cx, xs[ix + 1], cy): nb.append((xs[ix + 1], cy))
            if ix - 1 >= 0 and hc(cx, xs[ix - 1], cy): nb.append((xs[ix - 1], cy))
            if iy + 1 < len(ys) and vc(cx, cy, ys[iy + 1]): nb.append((cx, ys[iy + 1]))
            if iy - 1 >= 0 and vc(cx, cy, ys[iy - 1]): nb.append((cx, ys[iy - 1]))
            for n2 in nb:
                nd = (1 if n2[0] != cx else 0, 1 if n2[1] != cy else 0)
                g = best[cur] + abs(n2[0] - cx) + abs(n2[1] - cy) + (40 if pd and pd != nd else 0)
                if g < best.get(n2, 1e18):
                    best[n2] = g; came[n2] = (cur, nd)
                    heappush(openq, (g + abs(n2[0] - goal[0]) + abs(n2[1] - goal[1]), n2, nd))
        if goal not in came and goal != start: return [start, goal]
        p = [goal]; n = goal
        while n in came: n = came[n][0]; p.append(n)
        p.reverse()
        simp = [p[0]]
        for i in range(1, len(p) - 1):
            ax, ay = simp[-1]; bx, by = p[i]; cx2, cy2 = p[i + 1]
            if (ax == bx == cx2) or (ay == by == cy2): continue
            simp.append(p[i])
        simp.append(p[-1]); return simp

    def _clear(self, horiz, a, b, fixed, ign, P=8):
        for c, (bx, by, bw, bh) in self.boxes.items():
            if c in ign: continue
            if horiz:
                if by - P < fixed < by + bh + P and min(a, b) < bx + bw + P and max(a, b) > bx - P: return False
            else:
                if bx - P < fixed < bx + bw + P and min(a, b) < by + bh + P and max(a, b) > by - P: return False
        return True

    def _verify(self, path, s, t):
        for (x1, y1), (x2, y2) in zip(path, path[1:]):
            if abs(x1 - x2) > 1 and abs(y1 - y2) > 1: return False           # diagonal
            horiz = abs(y1 - y2) < 1
            for c, (bx, by, bw, bh) in self.boxes.items():
                if c in (s, t): continue
                if horiz:
                    if by + 1e-6 < y1 < by + bh - 1e-6 and min(x1, x2) < bx + bw - 1e-6 and max(x1, x2) > bx + 1e-6: return False
                else:
                    if bx + 1e-6 < x1 < bx + bw - 1e-6 and min(y1, y2) < by + bh - 1e-6 and max(y1, y2) > by + 1e-6: return False
        return True

    # ---------- render ----------
    def render(self, strict=False, layout="astar", outline_bands=True, animate_async=True):
        if layout == "banded":
            return self._render_banded(strict=strict, outline_bands=outline_bands, animate_async=animate_async)
        return self._render_astar(strict=strict)

    def _render_astar(self, strict=False):
        self._layout(); self._build_junctions(); self._fan_anchors()
        cells = []; self.violations = []
        # overlap check
        ids = list(self.boxes)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                ax, ay, aw, ah = self.boxes[ids[i]]; bx, by, bw, bh = self.boxes[ids[j]]
                if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + bh:
                    self.violations.append(f"H1 overlap {ids[i]}<>{ids[j]}")
        # zones
        for z in self._zones:
            zid, label, stroke, fill, h, cfill, dashed, center = z
            _, zx, zy, zw = self.Z[zid]
            va = "middle" if center else "top"; al = "center" if center else "left"
            d = "0" if (not dashed) else "1"
            cells.append(f'<mxCell id="{zid}" value="{_esc(label)}" style="rounded=0;dashed={d};dashPattern=8 6;strokeColor={stroke};fillColor={fill};verticalAlign={va};align={al};fontStyle=1;fontColor={stroke};fontSize=12;spacingLeft=12;spacingTop=8;arcSize=4;" vertex="1" parent="1"><mxGeometry x="{zx}" y="{zy}" width="{zw}" height="{h}" as="geometry"/></mxCell>')
        # components
        zfill = {z[0]: z[5] for z in self._zones}; zstroke = {z[0]: z[2] for z in self._zones}
        for c in self._comps:
            cid, zid, title, desc, row, col, fill = c; x, y, w, hh = self.boxes[cid]
            f = fill or zfill[zid]; val = "&lt;b&gt;" + _esc(title) + "&lt;/b&gt;" + ("&#10;" + _esc(desc) if desc else "")
            cells.append(f'<mxCell id="{cid}" value="{val}" style="rounded=1;whiteSpace=wrap;html=1;fillColor={f};strokeColor={zstroke[zid]};align=center;verticalAlign=top;spacingTop=6;fontSize=10;arcSize=8;" vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{hh}" as="geometry"/></mxCell>')
        # junction dots
        for jid, (jx, jy, jk) in self.JUN.items():
            col = self.JC.get(jk, "#000000")
            cells.append(f'<mxCell id="{jid}" value="" style="ellipse;fillColor={col};strokeColor={col};" vertex="1" parent="1"><mxGeometry x="{round(jx-5)}" y="{round(jy-5)}" width="10" height="10" as="geometry"/></mxCell>')
        # edges
        for k, (s, t, kind) in enumerate(self.NE):
            sj, tj = s in self.JUN, t in self.JUN
            sa = self._anchor(k, 'S', s); ta = self._anchor(k, 'T', t); path = None
            if sj ^ tj:                                              # symmetric comb if clear
                if tj:
                    jx, jy, _ = self.JUN[t]; xs, ce = sa
                    if self._clear(False, ce, jy, xs, {s}) and self._clear(True, xs, jx, jy, {s}): path = [(xs, ce), (xs, jy), (jx, jy)]
                else:
                    jx, jy, _ = self.JUN[s]; xt, ce = ta
                    if self._clear(False, jy, ce, xt, {t}) and self._clear(True, jx, xt, jy, {t}): path = [(jx, jy), (xt, jy), (xt, ce)]
            if path is None:                                        # A* with vertical stubs
                ss = sa if sj else (sa[0], sa[1] + (self.STUB if self.csides[(k, 'S')] == 'B' else -self.STUB))
                st = ta if tj else (ta[0], ta[1] + (self.STUB if self.csides[(k, 'T')] == 'B' else -self.STUB))
                mid = self._astar(s, t, ss, st); path = ([sa] if not sj else []) + mid + ([ta] if not tj else [])
            if not self._verify(path, s, t): self.violations.append(f"H2/H3 edge {s}->{t}")
            extra = ""
            if not sj: sx, sy, sw, sh = self.boxes[s]; extra += f"exitX={(sa[0]-sx)/sw:.3f};exitY={(sa[1]-sy)/sh:.3f};exitDx=0;exitDy=0;"
            if not tj: tx, ty, tw, th = self.boxes[t]; extra += f"entryX={(ta[0]-tx)/tw:.3f};entryY={(ta[1]-ty)/th:.3f};entryDx=0;entryDy=0;"
            pts = "".join(f'<mxPoint x="{round(x)}" y="{round(y)}"/>' for (x, y) in path[1:-1])
            cells.append(f'<mxCell id="ne{k}" style="edgeStyle=none;rounded=0;html=1;{self.ES.get(kind,"")}{extra}" edge="1" parent="1" source="{s}" target="{t}"><mxGeometry relative="1" as="geometry"><Array as="points">{pts}</Array></mxGeometry></mxCell>')
        # legend
        ZX, ZW = self.ZX, self.ZW; ly = self.canvas_bottom + 24
        if self._legend:
            cells.append(f'<mxCell id="leg" value="Legend" style="rounded=0;strokeColor=#999;fillColor=#FFFFFF;align=left;verticalAlign=top;fontStyle=1;spacingLeft=10;spacingTop=6;fontSize=11;" vertex="1" parent="1"><mxGeometry x="{ZX}" y="{ly}" width="{ZW}" height="{34+((len(self._legend)+1)//2)*30}" as="geometry"/></mxCell>')
            for i, (txt, st) in enumerate(self._legend):
                sx = ZX + 20 + (i % 2) * ((ZW - 40) // 2); sy = ly + 34 + (i // 2) * 30
                cells.append(f'<mxCell id="legl{i}" style="endArrow=block;html=1;{st}" edge="1" parent="1"><mxGeometry relative="1" as="geometry"><mxPoint x="{sx}" y="{sy}" as="sourcePoint"/><mxPoint x="{sx+70}" y="{sy}" as="targetPoint"/></mxGeometry></mxCell>')
                cells.append(f'<mxCell id="legt{i}" value="{_esc(txt)}" style="text;html=1;align=left;verticalAlign=middle;fontSize=10;" vertex="1" parent="1"><mxGeometry x="{sx+80}" y="{sy-10}" width="340" height="20" as="geometry"/></mxCell>')
            ly += 34 + ((len(self._legend) + 1) // 2) * 30
        ch = ly + 40
        if self.violations and strict: raise AssertionError(f"invariant violations: {self.violations[:8]}")
        out = ['<mxfile host="app.diagrams.net">', '<diagram name="C4" id="c4">',
               f'<mxGraphModel dx="1422" dy="800" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{self.W}" pageHeight="{ch}" math="0" shadow="0">',
               '<root>', '<mxCell id="0"/>', '<mxCell id="1" parent="0"/>',
               f'<mxCell id="title" value="{_esc(self.title)}" style="text;html=1;align=center;fontStyle=1;fontSize=18;" vertex="1" parent="1"><mxGeometry x="{ZX}" y="24" width="{ZW}" height="34" as="geometry"/></mxCell>']
        out += cells; out += ['</root>', '</mxGraphModel>', '</diagram>', '</mxfile>']
        return "\n".join(out)

    # ---------- banded layout + channel router (ported from gen_band_svg.py) ----------
    # constants (verbatim from gen_band_svg.py / gen_band_drawio.py)
    PAD_B = 46; GUTTER = 150; NODEH = 82; NGAP = 20; INNERPAD = 14; LABELH = 20
    LANE = 110; MAXNW = 210; SYSO = 18; TRUSTGAP = 104

    def _render_banded(self, strict=False, outline_bands=True, animate_async=True):
        import html as _html
        from collections import defaultdict as _dd
        zorder = [z[0] for z in self._zones]
        zmeta = {z[0]: z for z in self._zones}
        zidx = {z: i for i, z in enumerate(zorder)}
        byz = {z: [] for z in zorder}
        for c in self._comps: byz[c[1]].append(c[0])
        title = {c[0]: c[2] for c in self._comps}
        bandof = {c[0]: c[1] for c in self._comps}
        desc = {c[0]: (c[3] or "") for c in self._comps}
        adj = _dd(list)
        for (s, t, k) in self._edges: adj[s].append(t); adj[t].append(s)

        PAD = self.PAD_B; GUTTER = self.GUTTER; NODEH = self.NODEH; NGAP = self.NGAP
        INNERPAD = self.INNERPAD; LABELH = self.LABELH; LANE = self.LANE; MAXNW = self.MAXNW
        SYSO = self.SYSO; TRUSTGAP = self.TRUSTGAP
        BAND_W = self.W - 2 * (PAD + GUTTER)
        bx0 = PAD + GUTTER
        BANDH = LABELH + INNERPAD + NODEH + INNERPAD

        # systems & trust: generalise the hardcoded gen_band_drawio dicts to the declared lists
        SYSTEMS = self._systems
        # trust strip placed in an enlarged gap AFTER after_zone -> the band immediately following gets TRUSTGAP room
        trust_before = {}  # zone_that_gets_extra_top_room -> (label, fill, stroke)
        for (lab, after_zone, tfill, tstroke) in self._trust:
            if after_zone in zidx and zidx[after_zone] + 1 < len(zorder):
                nxt = zorder[zidx[after_zone] + 1]; trust_before[nxt] = (lab, tfill, tstroke)
        SEC = dict(self._security)

        bandY = {}; y = PAD + 40
        for z in zorder:
            if z in trust_before: y += TRUSTGAP   # room for the trust-boundary strip
            bandY[z] = y; y += BANDH + LANE
        CANVAS_H = y - LANE + PAD + 22; CANVAS_W = bx0 + BAND_W + GUTTER + PAD

        def inner_w(): return BAND_W - 2 * INNERPAD
        def nodew(n): return min(MAXNW, (inner_w() - (n - 1) * NGAP) / n) if n else MAXNW
        def xpositions(order):
            n = len(order)
            if not n: return {}, 0
            w = nodew(n); tot = n * w + (n - 1) * NGAP; sx = bx0 + INNERPAD + (inner_w() - tot) / 2
            return {nid: sx + i * (w + NGAP) for i, nid in enumerate(order)}, w
        def node_geom(ob):
            G = {}
            for z in zorder:
                xs, w = xpositions(ob[z]); ny = bandY[z] + LABELH + INNERPAD
                for nid in ob[z]: G[nid] = (xs[nid], ny, w, NODEH)
            return G
        def centers(G): return {k: (x + w / 2, yy + h / 2) for k, (x, yy, w, h) in G.items()}
        def seg_cross(a, b, c, d):
            def o(p, q, r): return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
            return ((o(a, b, c) > 0) != (o(a, b, d) > 0)) and ((o(c, d, a) > 0) != (o(c, d, b) > 0))
        def crossings(ob):
            C = centers(node_geom(ob)); segs = [(C[e[0]], C[e[1]], e[0], e[1]) for e in self._edges]
            n = 0
            for i in range(len(segs)):
                for j in range(i + 1, len(segs)):
                    a, b, s1, t1 = segs[i]; c, d, s2, t2 = segs[j]
                    if len({s1, t1, s2, t2}) < 4: continue
                    if seg_cross(a, b, c, d): n += 1
            return n
        # ---- barycenter ordering ----
        order = {z: list(byz[z]) for z in zorder}
        def frac(z, nid): o = order[z]; return (o.index(nid) + 0.5) / len(o)
        def sweep(td):
            for z in (zorder if td else list(reversed(zorder))):
                if len(order[z]) <= 1: continue
                key = {}
                for nid in order[z]:
                    nb = [a for a in adj[nid] if bandof.get(a) and bandof[a] != z]
                    key[nid] = sum(frac(bandof[a], a) for a in nb) / len(nb) if nb else frac(z, nid)
                order[z] = sorted(order[z], key=lambda n: (key[n], byz[z].index(n)))
        best = [{z: list(order[z]) for z in zorder}, crossings(order)]
        for it in range(14):
            sweep(it % 2 == 0); c = crossings(order)
            if c < best[1]: best = [{z: list(order[z]) for z in zorder}, c]
        order = best[0]

        G = node_geom(order); C = centers(G); cx = {k: v[0] for k, v in C.items()}
        # ---- channel routing ----
        def bot(z): return bandY[z] + BANDH
        def nb(n): x, yy, w, h = G[n]; return yy + h
        def nt(n): x, yy, w, h = G[n]; return yy
        EI = []; lcol = 0; rcol = 0
        for idx, e in enumerate(self._edges):
            s, t, ty = e[0], e[1], e[2]; bs, bt = zidx[bandof[s]], zidx[bandof[t]]; di = bt - bs
            long = abs(di) >= 2; side = None; gutx = None
            if long:
                side = "L" if (cx[s] + cx[t]) / 2 < bx0 + BAND_W / 2 else "R"
                if side == "L": gutx = bx0 - 18 - lcol * 14; lcol += 1
                else: gutx = bx0 + BAND_W + 18 + rcol * 14; rcol += 1
            EI.append(dict(idx=idx, s=s, t=t, ty=ty, bs=bs, bt=bt, di=di, long=long, gutx=gutx))
        attach = _dd(list)
        for ei in EI:
            s, t = ei["s"], ei["t"]; di = ei["di"]
            sside = 'B' if di >= 0 else 'T'; tside = 'T' if di > 0 else ('B' if di < 0 else 'B')
            hks = ei["gutx"] if ei["long"] else cx[t]; hkt = ei["gutx"] if ei["long"] else cx[s]
            attach[(s, sside)].append((ei["idx"], hks, 's', sside))
            attach[(t, tside)].append((ei["idx"], hkt, 't', tside))
        portx = {}
        for (nid, side), lst in attach.items():
            lst.sort(key=lambda r: r[1]); x, yy, w, h = G[nid]; n = len(lst)
            for k, (eidx, hk, role, sd) in enumerate(lst): portx[(eidx, role)] = x + w * (k + 1) / (n + 1)
        runs = _dd(list)
        def addrun(gi, xa, xb, eidx, key): runs[gi].append(dict(xa=min(xa, xb), xb=max(xa, xb), eidx=eidx, key=key))
        for ei in EI:
            i = ei["idx"]; s, t = ei["s"], ei["t"]; di = ei["di"]; sx = portx[(i, 's')]; tx = portx[(i, 't')]
            if not ei["long"]:
                if di == 0: addrun(ei["bs"], sx, tx, i, 'S')
                elif di > 0: addrun(ei["bs"], sx, tx, i, 'S')
                else: addrun(ei["bt"], sx, tx, i, 'S')
            else:
                if di > 0: addrun(ei["bs"], sx, ei["gutx"], i, 'A'); addrun(ei["bt"] - 1, ei["gutx"], tx, i, 'B')
                else: addrun(ei["bs"] - 1, sx, ei["gutx"], i, 'A'); addrun(ei["bt"], ei["gutx"], tx, i, 'B')
        track = {}
        for gi, rs in runs.items():
            rs.sort(key=lambda r: r["xa"]); ends = []
            for r in rs:
                placed = False
                for ti, last in enumerate(ends):
                    if r["xa"] > last + 8: ends[ti] = r["xb"]; track[(gi, r["eidx"], r["key"])] = ti; placed = True; break
                if not placed: track[(gi, r["eidx"], r["key"])] = len(ends); ends.append(r["xb"])
        def laneY(gi, tr):
            ntk = max((track[k] for k in track if k[0] == gi), default=0) + 1
            sp = min(14, (LANE - 20) / max(ntk, 1))
            return bandY[zorder[gi + 1]] - LANE + 12 + tr * sp if gi + 1 < len(zorder) else bot(zorder[gi]) + 12 + tr * sp
        # ---- routed polylines per edge ----
        ROUTES = {}
        for ei in EI:
            i = ei["idx"]; s, t = ei["s"], ei["t"]; ty = ei["ty"]; di = ei["di"]
            sx = portx[(i, 's')]; tx = portx[(i, 't')]
            if not ei["long"]:
                gi = ei["bs"] if di >= 0 else ei["bt"]; ly = laneY(gi, track[(gi, i, 'S')])
                sy = nb(s) if di >= 0 else nt(s); tyy = nt(t) if di > 0 else nb(t)
                pts = [(sx, sy), (sx, ly), (tx, ly), (tx, tyy)]
            else:
                gx = ei["gutx"]
                if di > 0:
                    gA = ei["bs"]; gB = ei["bt"] - 1; yA = laneY(gA, track[(gA, i, 'A')]); yB = laneY(gB, track[(gB, i, 'B')])
                    pts = [(sx, nb(s)), (sx, yA), (gx, yA), (gx, yB), (tx, yB), (tx, nt(t))]
                else:
                    gA = ei["bs"] - 1; gB = ei["bt"]; yA = laneY(gA, track[(gA, i, 'A')]); yB = laneY(gB, track[(gB, i, 'B')])
                    pts = [(sx, nt(s)), (sx, yA), (gx, yA), (gx, yB), (tx, yB), (tx, nb(t))]
            ROUTES[i] = (pts, ty)

        def wrap(s, n=21):
            words = s.split(); lines = []; cur = ""
            for w in words:
                if len(cur) + len(w) + 1 <= n: cur = (cur + " " + w).strip()
                else: lines.append(cur); cur = w
            if cur: lines.append(cur)
            return lines[:3]
        def tint(hx, amt=0.87):
            h = hx.lstrip("#"); r, g, b = int(h[:2], 16), int(h[2:4], 16), int(h[4:], 16)
            return f"#{int(r+(255-r)*amt):02x}{int(g+(255-g)*amt):02x}{int(b+(255-b)*amt):02x}"

        # ---------- mxGraph emit ----------
        def esc(s): return _html.escape(s, quote=True)
        cells = []; _id = [100]
        def nxt(): _id[0] += 1; return f"c{_id[0]}"
        def vcell(cid, value, style, x, yy, w, h, parent="1"):
            cells.append(
              f'        <mxCell id="{cid}" value="{value}" style="{style}" vertex="1" parent="{parent}">\n'
              f'          <mxGeometry x="{round(x,2)}" y="{round(yy,2)}" width="{round(w,2)}" height="{round(h,2)}" as="geometry"/>\n'
              f'        </mxCell>')
        def ecell(cid, src, tgt, style, waypoints):
            geo = '<mxGeometry relative="1" as="geometry">'
            if waypoints:
                geo += '\n            <Array as="points">'
                for (px, py) in waypoints:
                    geo += f'\n              <mxPoint x="{round(px,2)}" y="{round(py,2)}"/>'
                geo += '\n            </Array>\n          '
            geo += '</mxGeometry>'
            cells.append(
              f'        <mxCell id="{cid}" style="{style}" edge="1" parent="1" source="{src}" target="{tgt}">\n'
              f'          {geo}\n'
              f'        </mxCell>')

        # --- system boundaries: dashed boxes ENCOMPASSING several bands (drawn first/behind) ---
        for name, bands, scol in SYSTEMS:
            bs = [b for b in bands if b in bandY]
            if not bs: continue
            ytop = min(bandY[b] for b in bs) - SYSO - 17; ybot = max(bot(b) for b in bs) + SYSO
            st = (f"rounded=1;arcSize=4;fillColor=none;strokeColor={scol};strokeWidth=3.5;"
                  f"dashed=1;dashPattern=3 7;verticalAlign=top;align=left;spacingLeft=12;spacingTop=4;"
                  f"fontColor={scol};fontStyle=1;fontSize=12;html=1;")
            vcell(nxt(), esc(name), st, bx0 - SYSO, ytop, BAND_W + 2 * SYSO, ybot - ytop)

        # --- trust-boundary strips (gold) in the enlarged gap before the named band ---
        for (lab, tfill, tstroke), z in ((trust_before[z], z) for z in trust_before):
            gy = bandY[z] - 46
            st = (f"rounded=1;arcSize=20;fillColor={tfill};strokeColor={tstroke};strokeWidth=3.5;"
                  f"dashed=1;dashPattern=3 7;align=center;verticalAlign=middle;fontColor=#6b5200;"
                  f"fontStyle=1;fontSize=11;html=1;")
            vcell(nxt(), esc(lab), st, bx0 - SYSO, gy, BAND_W + 2 * SYSO, 36)

        # --- band containers ---
        for z in zorder:
            m = zmeta[z]; by = bandY[z]; stroke = m[2]
            if outline_bands:
                st = (f"rounded=1;arcSize=6;fillColor=none;strokeColor={stroke};strokeWidth=2;"
                      f"verticalAlign=top;align=left;spacingLeft=13;spacingTop=3;fontColor={stroke};"
                      f"fontStyle=1;fontSize=12;html=1;")
            else:
                st = (f"rounded=1;arcSize=6;fillColor={tint(stroke)};strokeColor={stroke};strokeWidth=2;"
                      f"verticalAlign=top;align=left;spacingLeft=13;spacingTop=3;fontColor={stroke};"
                      f"fontStyle=1;fontSize=12;html=1;")
            vcell(nxt(), esc(m[1]), st, bx0, by, BAND_W, BANDH)
            if z in SEC:
                nst = (f"text;html=1;align=right;verticalAlign=top;fontColor={stroke};"
                       f"fontSize=9;fontStyle=2;strokeColor=none;fillColor=none;")
                vcell(nxt(), esc("\U0001F512 " + SEC[z]), nst, bx0 + BAND_W - 360, by + 2, 348, 16)

        # --- components ---
        GID = {}
        for z in zorder:
            m = zmeta[z]; cfill = m[5]; stroke = m[2]
            for nid in order[z]:
                x, yy, w, h = G[nid]; cid = nxt(); GID[nid] = cid
                tline = " ".join(wrap(title[nid], 22))
                dline = " ".join(wrap(desc[nid], 34)[:3])
                raw = f"<b>{esc(tline)}</b>"
                if dline: raw += f'<br/><font style="font-size:8px;color:#555">{esc(dline)}</font>'
                val = esc(raw)
                st = (f"rounded=1;whiteSpace=wrap;html=1;fillColor={cfill};"
                      f"strokeColor={stroke};strokeWidth=1.3;fontSize=10;align=center;"
                      f"verticalAlign=middle;arcSize=8;")
                vcell(cid, val, st, x, yy, w, h)

        # --- edges ---
        BESTY = {
         "sync":     "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;strokeColor=#1A1A1A;",
         "async":    "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;strokeColor=#7A7A7A;dashed=1;dashPattern=6 4;flowAnimation=1;",
         "xtrust":   "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;strokeColor=#B85450;strokeWidth=2.4;",
         "identity": "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;strokeColor=#9966AA;dashed=1;dashPattern=2 4;",
        }
        animatable = {"async"}
        animated = 0
        for ei in EI:
            i = ei["idx"]; s, t = ei["s"], ei["t"]; pts, ty = ROUTES[i]
            interior = pts[1:-1]
            st = BESTY.get(ty, BESTY["sync"])
            if not animate_async and "flowAnimation=1;" in st:
                st = st.replace("flowAnimation=1;", "")
            if animate_async and ty in animatable and "flowAnimation=1;" in st: animated += 1
            ecell(nxt(), GID[s], GID[t], st, interior)
        self._animated_count = animated

        # --- legend ---
        if self._legend:
            ly = CANVAS_H - PAD + 8
            parts = " · ".join(lab for lab, _ in self._legend)
            leg = f"<b>Legend:</b>  {parts}  |  dotted box = system / trust boundary"
            lst = ("text;html=1;align=left;verticalAlign=middle;fontSize=10;fontColor=#333;"
                   "strokeColor=none;fillColor=none;")
            vcell(nxt(), esc(leg), lst, bx0, ly, BAND_W, 18)

        # --- title ---
        tst = "text;html=1;align=left;verticalAlign=middle;fontSize=15;fontStyle=1;fontColor=#1a1a1a;strokeColor=none;fillColor=none;"
        vcell(nxt(), esc(self.title), tst, bx0, PAD - 30, BAND_W, 22)

        # --- violations: node overlaps ---
        self.violations = []
        ids = list(G)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                ax, ay, aw, ah = G[ids[i]]; bx_, by_, bw, bh = G[ids[j]]
                if ax < bx_ + bw and bx_ < ax + aw and ay < by_ + bh and by_ < ay + bh:
                    self.violations.append(f"H1 overlap {ids[i]}<>{ids[j]}")
        if self.violations and strict:
            raise AssertionError(f"invariant violations: {self.violations[:8]}")

        body = "\n".join(cells)
        xml = (
         '<mxfile host="app.diagrams.net" type="device">\n'
         '  <diagram id="banded" name="Solution Architecture">\n'
         f'    <mxGraphModel dx="1200" dy="800" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" '
         f'arrows="1" fold="1" page="1" pageScale="1" pageWidth="{int(CANVAS_W)}" pageHeight="{int(CANVAS_H)}" '
         'math="0" shadow="0">\n'
         '      <root>\n'
         '        <mxCell id="0"/>\n'
         '        <mxCell id="1" parent="0"/>\n'
         f'{body}\n'
         '      </root>\n'
         '    </mxGraphModel>\n'
         '  </diagram>\n'
         '</mxfile>\n'
        )
        return xml


def _esc(s): return escape(s).replace("\n", "&#10;")
