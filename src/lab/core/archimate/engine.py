"""archimate_engine.py — ArchiMate Model Exchange XML generator with deterministic layered layout.

Produces .archimate.xml files importable into ADOIT (and Archi/BiZZdesign) plus SVG previews.
Pure Python, no dependencies.

Layout contract (why each rule exists — see references/layout-rules.md for the full spec):
  * LAYERS preserVED: elements rank into horizontal bands by ArchiMate layer then aspect
    (Motivation < Strategy < Business < Application < Technology), services above the
    components that realize them, data at the bottom — the canonical layered reading.
  * EQUAL SPACING: siblings in a row share one HGAP; connector lanes share one LANE_SP;
    ports on a box edge are fanned at equal fractions. Uniformity is what makes a
    generated diagram look drawn-by-hand-by-someone-careful.
  * ORTHOGONAL + PARALLEL: every connector is horizontal/vertical segments only, and all
    horizontal runs between two rows sit in a shared "channel" of equally spaced lanes,
    so parallel lines stay parallel and never overlap.
  * INTERFACES AS ICONS: *Interface elements emit small square nodes (ICON x ICON) so
    ADOIT/Archi render the symbol form instead of a labelled box.
  * VERIFIED: render checks hard invariants (no overlaps, no line crosses a box, minimum
    connector length, Serving/Realization point upward) and fails loudly.

API sketch (see the skill's SKILL.md for the workflow):
    m = Model("Lab Architecture")
    m.el("gw",  "ApplicationComponent", "LiteLLM Proxy")
    m.el("v1",  "ApplicationInterface", "/v1")
    m.el("svc", "ApplicationService",   "Model Routing")
    m.rel("Composition", "gw", "v1")
    m.rel("Realization", "gw", "svc")
    v = m.view("gov", "Governance Plane")
    v.place("gw", "v1", "svc")
    v.auto_edges()
    report = m.render("out", "lab")     # out/lab.archimate.xml + out/lab-<view>.svg
"""
from collections import defaultdict
from xml.sax.saxutils import escape

try:                                   # ArchiMate graphical notation for previews (same dir)
    from lab.core.archimate.notation import (MARKER_DEFS as _NMARKERS, icon as _nicon, label_dy as _nlabel_dy,
                                    rel_style as _nrel_style, shape as _nshape)
except ImportError:                    # pragma: no cover - keeps the engine importable standalone
    _nicon = lambda t, x, y: ""
    _nshape = lambda t, x, y, w, h, fill: f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="#5c6e82"/>'
    _nlabel_dy = lambda t: 0
    _NMARKERS = ""                     # no marker defs -> plain lines, never a dangling url(#...)
    _nrel_style = lambda rt: ("", None, None)

import functools as _functools
import json as _json
import os as _os
import re as _re

# ADOIT encodes a repository object's UUID in the ArchiMate exchange as identifier="id_<uuid>" (no
# braces), while its REST API returns the id as "{<uuid>}". So when an element id we emit IS a reused
# ADOIT object id (a UUID, with or without braces), emit ADOIT's NATIVE identifier `id_<uuid>` — then a
# re-import UPDATES that object in place instead of creating a duplicate. Every other id (our own name
# slugs, relation hashes) keeps the engine's `id-<slug>` scheme, so non-matched output is byte-identical.
_UUID = _re.compile(r"^\{?([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\}?$")


def _ident(eid):
    """The ArchiMate identifier for an element id: `id_<uuid>` (ADOIT-native) if it is a reused ADOIT
    object UUID, else `id-<slug>` (unchanged engine scheme)."""
    m = _UUID.match(str(eid))
    return f"id_{m.group(1).lower()}" if m else f"id-{eid}"


def _safe(eid):
    """A brace-free token for embedding an id inside another identifier (diagram-local node ids).
    Strips the ADOIT `{...}` braces (invalid in XML NCNames); a plain slug is returned unchanged, so
    normal renders stay byte-identical."""
    return str(eid).strip("{}")

# Taxonomy (layer/aspect/definitions): lab/core/semantic/archimate/taxonomy.json — ONE source of truth
# for layer + aspect: the semantic layer, the engine's layer bands / aspect rows (_TYPES, _aspect
# below) and the coarse fallback validator all read the same file (the archimate-adoit skill's
# references/archimate-classification.json is a symlink to it). Also ANNOTATES every element's
# documentation with its classification so the model itself says why each type was chosen.
_TAX_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "semantic", "archimate",
                          "taxonomy.json")
try:
    with open(_TAX_PATH) as _f:
        _TAXONOMY = _json.load(_f)["elements"]
except (OSError, ValueError, KeyError):    # standalone copy (dangling symlink): static tables below
    _TAXONOMY = {}


def _repo_root():
    """The `lab/core` package directory (the one holding the `semantic` package), walking up from this file;
    None when the engine runs as a standalone copy (no semantic layer beside it)."""
    d = _os.path.dirname(_os.path.abspath(__file__))
    for _ in range(6):
        if _os.path.isdir(_os.path.join(d, "semantic")):
            return d
        d = _os.path.dirname(d)
    return None


_ROOT = _repo_root()


@_functools.lru_cache(maxsize=1)
def _semantic():
    """The repo's semantic layer (exact ArchiMate relationship matrix), if present; None -> the
    coarse rules. Built ONCE per process: constructing SemanticService re-parses the taxonomy, the
    3,844-pair matrix XML and the reference workbooks (~1.7 s measured), and validate_relations()
    runs inside every metered validate/render tool call."""
    if _ROOT is None:
        return None
    try:
        from lab.core.semantic.service import SemanticService
        return SemanticService()
    except Exception:
        return None


# ---------------------------------------------------------------- element taxonomy
# layer -> standard ArchiMate fill
FILL = {"Motivation": "#E6E6FA", "Strategy": "#F5DEAA", "Business": "#FFFFB5",
        "Application": "#B5FFFF", "Technology": "#C9E7B8", "Physical": "#C9E7B8",
        "Implementation": "#FFE0E0", "Other": "#F0F0F0"}
_LAYER_BAND = {"Motivation": 0, "Strategy": 1, "Business": 2, "Application": 3,
               "Technology": 4, "Physical": 4, "Implementation": 5, "Other": 3}
# aspect sub-row inside a layer band, top -> down (services above realizers, data last)
_ASPECT_ROW = {"Service": 0, "Interface": 1, "Behaviour": 2, "Active": 3, "Passive": 4}

_ASPECT_NAME = {"active": "Active", "behaviour": "Behaviour", "passive": "Passive"}  # taxonomy -> row bucket

# xsi:type -> layer. _TYPES is DERIVED from the taxonomy (single source of truth); _FALLBACK_TYPES is
# the standalone table for a skill copy without the taxonomy file and must stay in step with
# src/lab/core/semantic/archimate/taxonomy.json (tests/unit/core/archimate/test_engine.py checks both against it). AndJunction /
# OrJunction are the exchange-format junction subtypes the taxonomy folds into Junction.
_FALLBACK_TYPES = {
 **{t: "Motivation" for t in ("Stakeholder Driver Assessment Goal Outcome Principle "
                              "Requirement Constraint Meaning Value").split()},
 **{t: "Strategy" for t in "Resource Capability CourseOfAction ValueStream".split()},
 **{t: "Business" for t in ("BusinessActor BusinessRole BusinessCollaboration BusinessInterface "
                            "BusinessProcess BusinessFunction BusinessInteraction BusinessEvent "
                            "BusinessService BusinessObject Contract Representation Product").split()},
 **{t: "Application" for t in ("ApplicationComponent ApplicationCollaboration ApplicationInterface "
                               "ApplicationFunction ApplicationInteraction ApplicationProcess "
                               "ApplicationEvent ApplicationService DataObject").split()},
 **{t: "Technology" for t in ("Node Device SystemSoftware TechnologyCollaboration TechnologyInterface "
                              "Path CommunicationNetwork TechnologyFunction TechnologyProcess "
                              "TechnologyInteraction TechnologyEvent TechnologyService Artifact").split()},
 **{t: "Physical" for t in "Equipment Facility DistributionNetwork Material".split()},
 **{t: "Implementation" for t in "WorkPackage Deliverable ImplementationEvent Plateau Gap".split()},
 **{t: "Other" for t in "Location Grouping Junction AndJunction OrJunction".split()},
}
_TYPES = {t: c["layer"] for t, c in _TAXONOMY.items()} if _TAXONOMY else dict(_FALLBACK_TYPES)
_TYPES.setdefault("AndJunction", "Other"); _TYPES.setdefault("OrJunction", "Other")
_REL_TYPES = ("Composition Aggregation Assignment Realization Serving Access Influence "
              "Triggering Flow Specialization Association Junction").split()
_FALLBACK_BEHAVIOUR = set("Driver Assessment Goal Outcome Principle Requirement Constraint Meaning Value "
                          "Capability CourseOfAction ValueStream WorkPackage Plateau".split())
_FALLBACK_PASSIVE = ("Artifact", "Contract", "Representation", "Product", "Material", "Deliverable", "Gap")


def _aspect(atype):
    """The layout/validation bucket of a type. `Service` and `Interface` are the two deliberate
    LAYOUT buckets (services row above their realizers; interfaces drawn as icons) computed on top
    of the taxonomy's aspect (active | behaviour | passive) — everything else comes from the
    taxonomy, never from a name heuristic (the old suffix rules misfiled Stakeholder, the three
    Collaborations, CommunicationNetwork, Path, DistributionNetwork, Location, Grouping and Junction
    as Behaviour, and Gap as Behaviour instead of Passive)."""
    if atype.endswith("Service"):
        return "Service"
    if atype.endswith("Interface"):
        return "Interface"
    tax = _TAXONOMY.get(atype)
    if tax:
        return _ASPECT_NAME.get(tax.get("aspect"), "Active")
    if atype in ("Junction", "AndJunction", "OrJunction"):
        return "Active"                    # taxonomy: Junction is (Other, active)
    return _aspect_heuristic(atype)


def _aspect_heuristic(atype):
    """Standalone fallback (taxonomy file absent): coarse suffix rules aligned with the taxonomy."""
    if atype.endswith(("Process", "Function", "Interaction", "Event")) or atype in _FALLBACK_BEHAVIOUR:
        return "Behaviour"
    if atype.endswith("Object") or atype in _FALLBACK_PASSIVE:
        return "Passive"
    return "Active"


def rank_of(atype):
    layer = _TYPES.get(atype, "Other")
    return _LAYER_BAND[layer] * 10 + _ASPECT_ROW[_aspect(atype)]


def _rgb(h):
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


class Model:
    def __init__(self, name, mid="model"):
        self.name, self.mid = name, mid
        self.elements = {}      # eid -> (type, name, doc)
        self.relations = {}     # rid -> (type, src, tgt, extra-attrs dict)
        self.views = []
        self.folders = {}       # eid -> folder/domain label (drives <organizations>)
        self._rseq = 0

    def el(self, eid, atype, name, doc=None, folder=None):
        if atype not in _TYPES:
            raise ValueError(f"unknown ArchiMate element type: {atype}")
        self.elements[eid] = (atype, name, doc)
        if folder:
            self.folders[eid] = folder
        return eid

    def rel(self, rtype, src, tgt, rid=None, accessType=None):
        if rtype not in _REL_TYPES:
            raise ValueError(f"unknown ArchiMate relationship type: {rtype}")
        for e in (src, tgt):
            if e not in self.elements:
                raise ValueError(f"relationship endpoint not declared: {e}")
        self._rseq += 1
        rid = rid or f"r{self._rseq}"
        extra = {"accessType": accessType} if accessType else {}
        self.relations[rid] = (rtype, src, tgt, extra)
        return rid

    def view(self, vid, title):
        v = View(self, vid, title)
        self.views.append(v)
        return v

    # ---------------- standard view catalogue ----------------
    def layer_view(self, vid, title, layers, expand=False):
        """A mapping view: every element of the given layer(s) plus all relationships
        among them. expand=True also pulls in 1-hop neighbours from other layers
        (useful for implementation/roadmap views where plateaus aggregate elements)."""
        sel = {eid for eid, (t, _, _) in self.elements.items() if _TYPES.get(t, "Other") in layers}
        if expand:
            for _, (rt, s, g, _x) in self.relations.items():
                if s in sel: sel.add(g)
                if g in sel: sel.add(s)
        if not sel:
            return None
        v = self.view(vid, title)
        v.place(*sorted(sel))
        v.auto_edges()
        return v

    def standard_views(self, prefix=""):
        """The standard cross-layer mapping catalogue. Views whose layers hold no
        elements are skipped, so call this on any model and get only what applies."""
        cat = [
            ("mot-strategy",  "Motivation to Strategy Mapping",       ("Motivation", "Strategy"), False),
            ("strategy-biz",  "Strategy to Business Mapping",         ("Strategy", "Business"), False),
            ("biz-app",       "Business to Application Mapping",      ("Business", "Application"), False),
            ("app-tech",      "Application to Technology & Physical Mapping",
                              ("Application", "Technology", "Physical"), False),
            ("impl-roadmap",  "Implementation & Roadmap",             ("Implementation",), True),
            ("full",          "Full Architecture View",
                              ("Motivation", "Strategy", "Business", "Application",
                               "Technology", "Physical", "Implementation"), False),
        ]
        made = {}
        for vid, title, layers, expand in cat:
            v = self.layer_view(prefix + vid, title, layers, expand=expand)
            if v is not None and v.edges:
                made[vid] = v
            elif v is not None:
                self.views.remove(v)   # a mapping view with no relationships says nothing
        return made

    # ---------------- semantic validation ----------------
    def to_spec(self):
        """The JSON shape the MCP tools and the semantic layer accept."""
        return {"name": self.name, "id": self.mid,
                "elements": [{"id": e, "type": t, "name": n, **({"doc": d} if d else {})}
                             for e, (t, n, d) in self.elements.items()],
                "relations": [{"id": r, "type": t, "src": s, "tgt": g, **x}
                              for r, (t, s, g, x) in self.relations.items()]}

    def validate_relations(self):
        """Legality of every relationship. Exact (full ArchiMate relationship matrix +
        interface-exposure semantics) when the repo's semantic layer is importable;
        otherwise the coarse category rules below. Warnings, not failures — the
        modeller decides; ADOIT applies its own matrix on import anyway."""
        sem = _semantic()
        if sem is not None:
            r = sem.validate_model(self.to_spec())
            return [f"{i['id']} ({i['relation']} {i['source']}->{i['target']}): not permitted for "
                    f"{i['types']} — allowed: {', '.join(i['allowed']) or 'nothing'}" for i in r["illegal"]]                 + [f"semantic: {w}" for w in r["warnings"]]
        warns = []
        for rid, (rt, s, g, _) in self.relations.items():
            ts, tg = self.elements[s][0], self.elements[g][0]
            ls, lg = _TYPES.get(ts, "Other"), _TYPES.get(tg, "Other")
            a_s, a_g = _aspect(ts), _aspect(tg)
            w = None
            if rt == "Access" and a_g != "Passive":
                w = f"Access must target a passive element, not {tg}"
            elif rt == "Access" and a_s == "Passive":
                w = f"Access cannot originate from passive element {ts}"
            elif rt == "Serving" and (a_s == "Passive" or a_g == "Passive"):
                w = "Serving cannot involve a passive element (use Access for data)"
            elif rt == "Influence" and lg != "Motivation":
                w = f"Influence must target a Motivation element, not {tg}"
            elif rt == "Assignment" and a_s not in ("Active", "Interface"):
                w = f"Assignment source must be active structure, not {ts} ({a_s})"
            elif rt == "Assignment" and a_g == "Passive" and tg != "Artifact":
                w = f"Assignment cannot target passive element {tg} (except Artifact)"
            elif rt in ("Triggering", "Flow") and (a_s == "Passive" or a_g == "Passive"):
                w = f"{rt} connects behaviour/active elements, not passive ones"
            elif rt in ("Composition", "Aggregation") and ls != lg and \
                    "Other" not in (ls, lg) and "Implementation" not in (ls, lg):
                w = f"{rt} across layers ({ls}->{lg}) — usually Realization/Assignment is meant"
            elif rt == "Specialization" and ts != tg:
                w = f"Specialization should relate same types ({ts} vs {tg})"
            if w:
                warns.append(f"{rid} ({rt} {s}->{g}): {w}")
        return warns

    # ---------------- output ----------------
    def to_xml(self, strict=True):
        body, report = [], {"views": {}, "violations": [], "warnings": self.validate_relations()}
        for v in self.views:
            vxml, canvas, viol = v.render()
            body.append(vxml)
            report["views"][v.vid] = canvas
            report["violations"] += [f"[{v.vid}] {x}" for x in viol]
        if strict and report["violations"]:
            raise AssertionError("layout invariants violated:\n  " + "\n  ".join(report["violations"]))
        out = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/" '
               'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
               'xsi:schemaLocation="http://www.opengroup.org/xsd/archimate/3.0/ '
               'http://www.opengroup.org/xsd/archimate/3.1/archimate3_Diagram.xsd" '
               f'identifier="id-{self.mid}">',
               f'<name xml:lang="en">{escape(self.name)}</name>', '<elements>']
        for eid, (t, n, doc) in self.elements.items():
            tax = _TAXONOMY.get(t)
            ann = (f"[{tax['layer']} layer · {tax['aspect']} structure — {t}] " if tax else "")
            text = ann + (doc or (tax["definition"] if tax else ""))
            out.append(f'<element identifier="{_ident(eid)}" xsi:type="{t}"><name xml:lang="en">{escape(n)}</name>'
                       + (f'<documentation xml:lang="en">{escape(text)}</documentation>' if text else '')
                       + '</element>')
        out.append('</elements>')
        if self.relations:
            out.append('<relationships>')
            for rid, (t, s, g, extra) in self.relations.items():
                at = "".join(f' {k}="{v}"' for k, v in extra.items())
                out.append(f'<relationship identifier="id-{rid}" source="{_ident(s)}" target="{_ident(g)}" '
                           f'xsi:type="{t}"{at}/>')
            out.append('</relationships>')
        # <organizations>: a folder tree grouping elements by domain (primary) then ArchiMate layer.
        # Emitted ONLY when folders are set (otherwise the output is byte-identical to before).
        # Schema order (ArchiMate 3.1 Model Exchange): elements, relationships, organizations, views.
        if self.folders:
            tree = {}
            for eid in self.elements:
                dom = self.folders.get(eid)
                if not dom:
                    continue
                layer = _TYPES.get(self.elements[eid][0], "Other")
                tree.setdefault(dom, {}).setdefault(layer, []).append(eid)
            if tree:
                out.append('<organizations>')
                for dom in sorted(tree):
                    out.append(f'<item><label xml:lang="en">{escape(dom)}</label>')
                    for layer in sorted(tree[dom]):
                        out.append(f'<item><label xml:lang="en">{escape(layer)}</label>')
                        for eid in tree[dom][layer]:
                            out.append(f'<item identifierRef="{_ident(eid)}"/>')
                        out.append('</item>')
                    out.append('</item>')
                out.append('</organizations>')
        if body:
            out.append('<views><diagrams>')
            out += body
            out.append('</diagrams></views>')
        out.append('</model>')
        self._report = report
        return "\n".join(out)

    _XSD = None

    @classmethod
    def _schema(cls):
        """Official ArchiMate 3.1 XSD, shipped beside the engine (xsd/; the skill's references/xsd
        links to it) — every render is validated
        against it (Archi rejects schema-invalid files; ADOIT is merely lenient)."""
        if cls._XSD is None:
            import os
            try:
                import xmlschema
                cls._XSD = xmlschema.XMLSchema(os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "xsd",
                    "archimate3_Diagram.xsd"))
            except Exception:
                cls._XSD = False
        return cls._XSD

    def render(self, outdir, basename, strict=True):
        import os
        xml = self.to_xml(strict=strict)
        os.makedirs(outdir, exist_ok=True)
        xp = os.path.join(outdir, f"{basename}.archimate.xml")
        with open(xp, "w") as f:
            f.write(xml)
        schema = self._schema()
        if schema:
            errors = [f"XSD: {e.reason}" for e in schema.iter_errors(xp)]
            if errors and strict:
                raise AssertionError("schema-invalid export:\n  " + "\n  ".join(errors[:5]))
            self._report["violations"] += errors
        self._report["schema_validated"] = bool(schema)
        paths = [xp]
        for v in self.views:
            sp = os.path.join(outdir, f"{basename}-{v.vid}.svg")
            with open(sp, "w") as f:
                f.write(v.to_svg())
            paths.append(sp)
        return {"files": paths, **self._report}


class View:
    # geometry knobs — one value each so spacing stays uniform everywhere
    MARGIN = 60; HGAP = 70; W = 190; H = 58; ICON = 30
    GAP_BASE = 110          # minimum row gap (also guarantees min connector length)
    LANE_SP = 18            # equal spacing between parallel lanes in a channel
    STUB = 22               # straight run leaving a box before any bend
    GUT_SP = 18; GUTTER = 84  # side gutter for edges spanning >1 row gap
    SNAP = 36               # near-aligned adjacent edges snap to a straight vertical
    MIN_SEP = 24            # min horizontal clearance between runs sharing a lane
    IPAD = 16; ICH = 28     # container inner padding / caption strip

    def __init__(self, model, vid, title):
        self.m, self.vid, self.title = model, vid, title
        self.nodes = {}   # eid -> dict(w,h,rank,order,parent,container,icon)
        self.kids = {}
        self.edges = []   # (rid, src, tgt)

    # ---------------- declaration ----------------
    def place(self, *eids, rank=None, order=None, w=None, h=None):
        for i, eid in enumerate(eids):
            t = self._t(eid)
            icon = _aspect(t) == "Interface"
            self.nodes[eid] = dict(
                w=w or (self.ICON if icon else self.W), h=h or (self.ICON if icon else self.H),
                rank=rank if rank is not None else rank_of(t), pinned=rank is not None,
                order=(order + i) if order is not None else None,
                parent=None, container=False, icon=icon)
        return eids[0] if len(eids) == 1 else eids

    def container(self, eid, children, rank=None, order=None):
        t = self._t(eid)
        self.nodes[eid] = dict(w=0, h=0, rank=rank if rank is not None else rank_of(t),
                               pinned=rank is not None, order=order, parent=None,
                               container=True, icon=False)
        self.kids[eid] = list(children)
        for c in children:
            if c not in self.nodes:
                raise ValueError(f"place() child {c} before adding it to container {eid}")
            self.nodes[c]["parent"] = eid
        return eid

    def auto_edges(self):
        """Draw every model relationship whose two ends are on this view — except
        Composition/Aggregation already shown by nesting (rule D1: nesting, not a line)."""
        for rid, (t, s, g, _) in self.m.relations.items():
            if s in self.nodes and g in self.nodes:
                if t in ("Composition", "Aggregation") and (
                        self.nodes[g].get("parent") == s or self.nodes[s].get("parent") == g):
                    continue
                self.edges.append((rid, s, g))

    def _t(self, eid):
        if eid not in self.m.elements:
            raise ValueError(f"element not declared on model: {eid}")
        return self.m.elements[eid][0]

    # ---------------- layout ----------------
    def _top(self, e):
        p = self.nodes[e]["parent"]
        return p if p is not None else e

    def _layout(self):
        N = self.nodes
        # Rule A4: dependency direction beats aspect order — whatever is served/realized
        # floats above its server/realizer (the layered-view "Customer on top" reading).
        # Explicit rank= pins a node; unresolvable cycles surface later as H4 violations.
        for _ in range(6):
            changed = False
            for rid, s, g in self.edges:
                if self.m.relations[rid][0] in ("Serving", "Realization"):
                    S, T = self._top(s), self._top(g)
                    if S != T and N[T]["rank"] >= N[S]["rank"] and not N[T]["pinned"]:
                        N[T]["rank"] = N[S]["rank"] - 1
                        changed = True
            if not changed:
                break
        for cid, ch in self.kids.items():  # container = inner row of children
            N[cid]["w"] = max(180, sum(N[c]["w"] for c in ch) + self.HGAP * (len(ch) - 1) + 2 * self.IPAD)
            N[cid]["h"] = max(N[c]["h"] for c in ch) + self.ICH + self.IPAD

        rows = defaultdict(list)
        for e in N:
            if N[e]["parent"] is None:
                rows[N[e]["rank"]].append(e)
        self.rowseq = sorted(rows)

        # order: declared first, then barycenter sweeps to cut crossings
        adj = defaultdict(list)
        for _, s, g in self.edges:
            adj[self._top(s)].append(self._top(g))
            adj[self._top(g)].append(self._top(s))
        idx = {}
        for r in self.rowseq:
            rows[r].sort(key=lambda e: (N[e]["order"] is None, N[e]["order"] or 0))
            idx.update({e: i for i, e in enumerate(rows[r])})
        for _ in range(4):
            for r in self.rowseq:
                def bary(e):
                    ns = [idx[a] for a in adj[e] if a in idx and N[a]["rank"] != r]
                    return sum(ns) / len(ns) if ns else idx[e]
                rows[r].sort(key=lambda e: (N[e]["order"] if N[e]["order"] is not None else 1e9, bary(e)))
                idx.update({e: i for i, e in enumerate(rows[r])})
        self.rows = rows

        # x: equal HGAP inside each row, every row centred on the widest
        widths = {r: sum(N[e]["w"] for e in rows[r]) + self.HGAP * (len(rows[r]) - 1) for r in rows}
        full = max(widths.values()) if widths else 400
        self.has_long = any(abs(self.rowseq.index(self._rank_row(s)) - self.rowseq.index(self._rank_row(g))) > 1
                            for _, s, g in self.edges) or any(
                            self._rank_row(s) == self._rank_row(g) for _, s, g in self.edges)
        gut = self.GUTTER if self.has_long else 0
        x0 = self.MARGIN + gut
        self.pos = {}
        for r in self.rowseq:
            x = x0 + (full - widths[r]) / 2
            for e in rows[r]:
                self.pos[e] = [round(x), 0]
                x += N[e]["w"] + self.HGAP
        self.content_w = full
        self.canvas_w = round(full + 2 * (self.MARGIN + gut))
        for cid, ch in self.kids.items():  # children x inside container
            x = self.pos[cid][0] + self.IPAD
            for c in sorted(ch, key=lambda c: (N[c]["order"] is None, N[c]["order"] or 0)):
                self.pos[c] = [round(x), 0]
                x += N[c]["w"] + self.HGAP

    def _rank_row(self, e):
        return self.nodes[self._top(e)]["rank"]

    def _classify_edges(self):
        """Split edges into: straight verticals, single-channel runs, gutter routes."""
        ri = {r: i for i, r in enumerate(self.rowseq)}
        E = []
        for k, (rid, s, g) in enumerate(self.edges):
            rs, rt = ri[self._rank_row(s)], ri[self._rank_row(g)]
            E.append(dict(k=k, rid=rid, s=s, t=g, rs=rs, rt=rt, d=rt - rs))
        return E

    def _ports_runs(self, E):
        """Assign fanned ports (equal fractions of the box edge) and channel runs (x-only)."""
        N, P = self.nodes, self.pos
        cx = lambda e: P[e][0] + N[e]["w"] / 2
        lg, rg = 0, 0
        for ei in E:
            if abs(ei["d"]) >= 2:  # long edge -> side gutter, allocated outward in order
                left = (cx(ei["s"]) + cx(ei["t"])) / 2 < self.MARGIN + self.GUTTER + self.content_w / 2
                if left:
                    ei["gx"] = self.MARGIN + self.GUTTER - 30 - lg * self.GUT_SP; lg += 1
                else:
                    ei["gx"] = self.canvas_w - self.MARGIN - self.GUTTER + 30 + rg * self.GUT_SP; rg += 1
        att = defaultdict(list)   # (leaf, side) -> [(edge, sortx, role)]
        for ei in E:
            d = ei["d"]
            ss = "B" if d >= 0 else "T"
            ts = "T" if d > 0 else "B"
            sx_hint = ei.get("gx", cx(ei["t"]))
            tx_hint = ei.get("gx", cx(ei["s"]))
            att[(ei["s"], ss)].append((ei, sx_hint, "s")); ei["ss"] = ss
            att[(ei["t"], ts)].append((ei, tx_hint, "t")); ei["ts"] = ts
        for (leaf, side), lst in att.items():
            lst.sort(key=lambda r: r[1])
            x, w = P[leaf][0], N[leaf]["w"]
            for i, (ei, _, role) in enumerate(lst):     # equal port fractions (anchor fanning)
                ei["sx" if role == "s" else "tx"] = x + w * (i + 1) / (len(lst) + 1)
        for ei in E:  # near-aligned adjacent edges become one straight vertical
            ei["straight"] = False
            if abs(ei["d"]) == 1 and abs(ei["sx"] - ei["tx"]) <= self.SNAP:
                xm = (ei["sx"] + ei["tx"]) / 2
                sb, tb = (P[ei["s"]][0], N[ei["s"]]["w"]), (P[ei["t"]][0], N[ei["t"]]["w"])
                if sb[0] + 6 <= xm <= sb[0] + sb[1] - 6 and tb[0] + 6 <= xm <= tb[0] + tb[1] - 6:
                    ei["sx"] = ei["tx"] = xm
                    ei["straight"] = True
        runs = defaultdict(list)  # gap index -> [(xa, xb, edge, tag)]
        for ei in E:
            d, s = ei["d"], ei
            if s["straight"]:
                continue
            if d == 0:
                runs[max(s["rs"], 0)].append([min(s["sx"], s["tx"]), max(s["sx"], s["tx"]), ei, "S"])
            elif abs(d) == 1:
                g = min(s["rs"], s["rt"])
                runs[g].append([min(s["sx"], s["tx"]), max(s["sx"], s["tx"]), ei, "S"])
            else:
                gA = s["rs"] if d > 0 else s["rs"] - 1
                gB = s["rt"] - 1 if d > 0 else s["rt"]
                runs[gA].append([min(s["sx"], s["gx"]), max(s["sx"], s["gx"]), ei, "A"])
                runs[gB].append([min(s["tx"], s["gx"]), max(s["tx"], s["gx"]), ei, "B"])
        self.tracks = {}
        self.ntracks = defaultdict(int)
        for g, rs in runs.items():  # greedy interval packing -> minimal parallel lanes
            rs.sort(key=lambda r: r[0])
            ends = []
            for xa, xb, ei, tag in rs:
                for ti in range(len(ends)):
                    if xa > ends[ti] + self.MIN_SEP:
                        ends[ti] = xb; self.tracks[(g, ei["k"], tag)] = ti; break
                else:
                    self.tracks[(g, ei["k"], tag)] = len(ends); ends.append(xb)
            self.ntracks[g] = len(ends)

    def _vertical(self, E):
        """Row y positions: every gap sized to hold its lanes with equal spacing."""
        N = self.nodes
        self.rowh = {r: max(N[e]["h"] for e in self.rows[r]) for r in self.rowseq}
        self.gap_h, self.rowy = {}, {}
        y = self.MARGIN
        for i, r in enumerate(self.rowseq):
            self.rowy[r] = y
            need = self.ntracks.get(i, 0)
            gh = max(self.GAP_BASE, 2 * self.STUB + max(need - 1, 0) * self.LANE_SP + 2 * self.LANE_SP)
            self.gap_h[i] = gh
            y += self.rowh[r] + gh
        self.canvas_h = round(y - self.gap_h.get(len(self.rowseq) - 1, 0)
                              + (self.gap_h.get(len(self.rowseq) - 1, 0)
                                 if self.ntracks.get(len(self.rowseq) - 1) else 0) + self.MARGIN)
        for r in self.rowseq:  # final y per node (centred in its row)
            for e in self.rows[r]:
                self.pos[e][1] = round(self.rowy[r] + (self.rowh[r] - N[e]["h"]) / 2)
        for cid, ch in self.kids.items():
            for c in ch:
                self.pos[c][1] = self.pos[cid][1] + self.ICH

    def _lane_y(self, g, t):
        r = self.rowseq[g]
        top = self.rowy[r] + self.rowh[r]
        n = self.ntracks.get(g, 1)
        mid = top + self.gap_h[g] / 2
        return mid - (n - 1) * self.LANE_SP / 2 + t * self.LANE_SP

    def _routes(self, E):
        N, P = self.nodes, self.pos
        bot = lambda e: P[e][1] + N[e]["h"]
        top = lambda e: P[e][1]
        for ei in E:
            s, t, d, k = ei["s"], ei["t"], ei["d"], ei["k"]
            sx, tx = ei["sx"], ei["tx"]
            sy = bot(s) if ei["ss"] == "B" else top(s)
            ty = bot(t) if ei["ts"] == "B" else top(t)
            if ei["straight"]:
                ei["pts"] = [(sx, sy), (tx, ty)]
                continue
            if d == 0:
                ly = self._lane_y(max(ei["rs"], 0), self.tracks[(max(ei["rs"], 0), k, "S")])
                ei["pts"] = [(sx, sy), (sx, ly), (tx, ly), (tx, ty)]
            elif abs(d) == 1:
                g = min(ei["rs"], ei["rt"])
                ly = self._lane_y(g, self.tracks[(g, k, "S")])
                ei["pts"] = [(sx, sy), (sx, ly), (tx, ly), (tx, ty)]
            else:
                gA = ei["rs"] if d > 0 else ei["rs"] - 1
                gB = ei["rt"] - 1 if d > 0 else ei["rt"]
                yA = self._lane_y(gA, self.tracks[(gA, k, "A")])
                yB = self._lane_y(gB, self.tracks[(gB, k, "B")])
                gx = ei["gx"]
                ei["pts"] = [(sx, sy), (sx, yA), (gx, yA), (gx, yB), (tx, yB), (tx, ty)]

    # ---------------- invariants ----------------
    def _verify(self, E):
        viol = []
        N, P = self.nodes, self.pos
        leaves = {e: (P[e][0], P[e][1], P[e][0] + N[e]["w"], P[e][1] + N[e]["h"])
                  for e in N if not N[e]["container"]}
        items = list(leaves.items())
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (a, (ax1, ay1, ax2, ay2)), (b, (bx1, by1, bx2, by2)) = items[i], items[j]
                if ax1 < bx2 and bx1 < ax2 and ay1 < by2 and by1 < ay2:
                    viol.append(f"H1 overlap {a}<>{b}")
        for ei in E:
            pts = ei["pts"]
            total = 0
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                total += abs(x1 - x2) + abs(y1 - y2)
                if abs(x1 - x2) > 0.5 and abs(y1 - y2) > 0.5:
                    viol.append(f"H-ortho diagonal segment on {ei['rid']}")
                for e, (bx1, by1, bx2, by2) in leaves.items():
                    if e in (ei["s"], ei["t"]):
                        continue
                    if abs(y1 - y2) <= 0.5:  # horizontal
                        if by1 + 1 < y1 < by2 - 1 and min(x1, x2) < bx2 - 1 and max(x1, x2) > bx1 + 1:
                            viol.append(f"H2 {ei['rid']} crosses {e}")
                    else:
                        if bx1 + 1 < x1 < bx2 - 1 and min(y1, y2) < by2 - 1 and max(y1, y2) > by1 + 1:
                            viol.append(f"H2 {ei['rid']} crosses {e}")
            if total < 40:
                viol.append(f"H3 connector too short on {ei['rid']}")
            rt = self.m.relations[ei["rid"]][0]
            if rt in ("Serving", "Realization") and ei["d"] > 0:
                viol.append(f"H4 {rt} {ei['rid']} points downward (served/realized must sit above)")
        return viol

    def _normalize(self, E):
        """The Open Exchange schema requires nonNegativeInteger coordinates; gutter routing
        can push x below zero. Shift the whole drawing right/down so every node AND every
        bendpoint is >= 0 (with a small margin), and grow the canvas accordingly."""
        xs = [x for x, _ in self.pos.values()] + [x for ei in E for x, _ in ei["pts"]]
        ys = [y for _, y in self.pos.values()] + [y for ei in E for _, y in ei["pts"]]
        dx = max(0, 10 - min(xs)) if xs else 0
        dy = max(0, 10 - min(ys)) if ys else 0
        if not dx and not dy:
            return
        for e in self.pos:
            self.pos[e] = [self.pos[e][0] + dx, self.pos[e][1] + dy]
        for ei in E:
            ei["pts"] = [(x + dx, y + dy) for x, y in ei["pts"]]
        self.canvas_w += dx
        self.canvas_h += dy

    # ---------------- render ----------------
    def _build(self):
        self._layout()
        E = self._classify_edges()
        self._ports_runs(E)
        self._vertical(E)
        self._routes(E)
        self._normalize(E)
        self._E = E
        return self._verify(E)

    def render(self):
        viol = self._build()
        out = [f'<view identifier="id-v-{self.vid}" xsi:type="Diagram">'
               f'<name xml:lang="en">{escape(self.title)}</name>']
        nid = {}

        def emit(eid):
            x, y = self.pos[eid]
            n = self.nodes[eid]
            nn = f"id-n-{self.vid}-{_safe(eid)}"
            nid[eid] = nn
            t = self._t(eid)
            r, g, b = _rgb(FILL[_TYPES.get(t, "Other")])
            out.append(f'<node identifier="{nn}" elementRef="{_ident(eid)}" xsi:type="Element" '
                       f'x="{round(x)}" y="{round(y)}" w="{n["w"]}" h="{n["h"]}">'
                       f'<style><fillColor r="{r}" g="{g}" b="{b}"/>'
                       f'<lineColor r="92" g="110" b="130"/>'
                       f'<font name="Sans" size="{11 if n["container"] else 9}">'
                       f'<color r="0" g="0" b="0"/></font></style>')
            for c in self.kids.get(eid, []):
                emit(c)
            out.append('</node>')

        for e in self.nodes:
            if self.nodes[e]["parent"] is None:
                emit(e)
        for ei in self._E:
            c = (f'<connection identifier="id-c-{self.vid}-{ei["k"]}" relationshipRef="id-{ei["rid"]}" '
                 f'xsi:type="Relationship" source="{nid[ei["s"]]}" target="{nid[ei["t"]]}">'
                 f'<style><lineColor r="70" g="70" b="70"/></style>')
            for (x, y) in ei["pts"][1:-1]:
                c += f'<bendpoint x="{round(x)}" y="{round(y)}"/>'
            out.append(c + '</connection>')
        out.append('</view>')
        return "\n".join(out), (self.canvas_w, self.canvas_h), viol

    def to_svg(self):
        """Quick human-checkable preview; ADOIT import uses the XML, not this."""
        if not hasattr(self, "_E"):
            self._build()
        N, P = self.nodes, self.pos
        s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.canvas_w}" height="{self.canvas_h}" '
             f'font-family="Helvetica,Arial" font-size="10">',
             '<rect width="100%" height="100%" fill="white"/>',
             f'<text x="{self.MARGIN}" y="{self.MARGIN - 20}" font-size="15" font-weight="bold">'
             f'{escape(self.title)}</text>',
             _NMARKERS]                 # relationship markers (archimate_notation.MARKER_DEFS)
        def draw(eid):
            x, y = P[eid]; n = N[eid]; t = self._t(eid)
            fill = FILL[_TYPES.get(t, "Other")]
            name = self.m.elements[eid][1]
            if n["icon"]:
                s.append(f'<circle cx="{x + n["w"]/2}" cy="{y + n["h"]/2}" r="{n["w"]/2}" '
                         f'fill="{fill}" stroke="#5c6e82"/>')
                s.append(f'<text x="{x + n["w"]/2}" y="{y - 4}" text-anchor="middle" font-size="8">'
                         f'{escape(name)}</text>')
            else:
                if n["container"]:
                    s.append(f'<rect x="{x}" y="{y}" width="{n["w"]}" height="{n["h"]}" fill="{fill}" '
                             f'stroke="#5c6e82" stroke-dasharray="4 3"/>')
                else:                       # ArchiMate notation: type-specific body + corner icon
                    s.append(_nshape(t, x, y, n["w"], n["h"], fill))
                    s.append(_nicon(t, x + n["w"] - 20, y + 4))
                ty = y + 16 if n["container"] else y + n["h"] / 2 + 3 + _nlabel_dy(t)
                anch = x + 8 if n["container"] else x + n["w"] / 2
                mid = "" if n["container"] else ' text-anchor="middle"'
                wt = "bold" if n["container"] else "normal"
                s.append(f'<text x="{anch}" y="{ty}"{mid} font-weight="{wt}">{escape(name)}</text>')
        for e in self.nodes:
            if N[e]["parent"] is None:
                draw(e)
        for cid in self.kids:
            for c in self.kids[cid]:
                draw(c)
        for ei in self._E:
            pts = " ".join(f"{round(x)},{round(y)}" for x, y in ei["pts"])
            rt = self.m.relations[ei["rid"]][0]
            dash, ms, me = _nrel_style(rt)      # ArchiMate 3.x line notation (archimate_notation.REL_STYLE)
            attrs = ""
            if dash:
                attrs += f' stroke-dasharray="{dash}"'
            if ms:
                attrs += f' marker-start="url(#{ms})"'
            if me:
                attrs += f' marker-end="url(#{me})"'
            s.append(f'<polyline points="{pts}" fill="none" stroke="#444"{attrs}/>')
        s.append('</svg>')
        return "\n".join(s)
