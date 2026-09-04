"""archimate_notation.py — ArchiMate 3.1 graphical notation for SVG previews.

Every element type gets the shape and/or corner icon the standard (and the cheat sheet)
prescribes, so a reviewer can tell a service from a function from an interface at a
glance — classification must be *visible*, not just encoded in xsi:type. ADOIT renders its
own notation from xsi:type on import; this module makes the preview honest before that.

shape(t, x, y, w, h, fill)  -> SVG for the element body
icon(t, x, y)               -> SVG for a 16x16 type icon anchored at (x, y) top-left ('' if the
                               shape itself carries the meaning)
label_dy(t)                 -> vertical offset for the name (objects: below the band)
rel_style(rt)               -> (stroke-dasharray, marker-start, marker-end) for a relationship type
MARKER_DEFS                 -> the SVG <defs> block declaring the line-end markers rel_style refers to
"""
S = 'stroke="#333" stroke-width="1" fill="none"'

# ---------------- corner icons (16x16 box, drawn relative to x,y) ----------------
def _actor(x, y):
    return (f'<circle cx="{x+8}" cy="{y+3}" r="2.5" {S}/><line x1="{x+8}" y1="{y+5.5}" x2="{x+8}" y2="{y+11}" {S}/>'
            f'<line x1="{x+3}" y1="{y+8}" x2="{x+13}" y2="{y+8}" {S}/><line x1="{x+8}" y1="{y+11}" x2="{x+4}" y2="{y+16}" {S}/>'
            f'<line x1="{x+8}" y1="{y+11}" x2="{x+12}" y2="{y+16}" {S}/>')
def _role(x, y):
    return (f'<rect x="{x+3}" y="{y+4}" width="10" height="8" {S}/><ellipse cx="{x+13}" cy="{y+8}" rx="2.5" ry="4" fill="white" stroke="#333"/>'
            f'<path d="M{x+3},{y+4} a2.5,4 0 0 0 0,8" {S}/>')
def _collab(x, y):
    return f'<circle cx="{x+6}" cy="{y+8}" r="5" {S}/><circle cx="{x+11}" cy="{y+8}" r="5" {S}/>'
def _process(x, y):
    return f'<polygon points="{x+1},{y+5} {x+9},{y+5} {x+9},{y+2} {x+15},{y+8} {x+9},{y+14} {x+9},{y+11} {x+1},{y+11}" {S}/>'
def _function(x, y):
    return f'<polygon points="{x+2},{y+15} {x+2},{y+6} {x+8},{y+1} {x+14},{y+6} {x+14},{y+15} {x+8},{y+10}" {S}/>'
def _interaction(x, y):
    return (f'<path d="M{x+6},{y+2} a6,6 0 0 0 0,12 z" {S}/><path d="M{x+10},{y+2} a6,6 0 0 1 0,12 z" {S}/>')
def _component(x, y):
    return (f'<rect x="{x+4}" y="{y+1}" width="11" height="14" {S}/><rect x="{x+1}" y="{y+4}" width="6" height="3" fill="white" stroke="#333"/>'
            f'<rect x="{x+1}" y="{y+9}" width="6" height="3" fill="white" stroke="#333"/>')
def _node(x, y):
    return (f'<polygon points="{x+1},{y+5} {x+5},{y+1} {x+15},{y+1} {x+15},{y+11} {x+11},{y+15} {x+1},{y+15}" {S}/>'
            f'<polyline points="{x+1},{y+5} {x+11},{y+5} {x+15},{y+1}" {S}/><line x1="{x+11}" y1="{y+5}" x2="{x+11}" y2="{y+15}" {S}/>')
def _device(x, y):
    return f'<rect x="{x+2}" y="{y+2}" width="12" height="9" rx="1" {S}/><polygon points="{x+4},{y+15} {x+12},{y+15} {x+10},{y+11} {x+6},{y+11}" {S}/>'
def _sysw(x, y):
    return f'<circle cx="{x+8}" cy="{y+8}" r="7" {S}/><circle cx="{x+10}" cy="{y+6}" r="4.5" {S}/>'
def _artifact(x, y):
    return f'<polygon points="{x+3},{y+1} {x+10},{y+1} {x+14},{y+5} {x+14},{y+15} {x+3},{y+15}" {S}/><polyline points="{x+10},{y+1} {x+10},{y+5} {x+14},{y+5}" {S}/>'
def _network(x, y):
    return (f'<circle cx="{x+3}" cy="{y+4}" r="2" fill="#333"/><circle cx="{x+13}" cy="{y+4}" r="2" fill="#333"/>'
            f'<circle cx="{x+3}" cy="{y+12}" r="2" fill="#333"/><circle cx="{x+13}" cy="{y+12}" r="2" fill="#333"/>'
            f'<line x1="{x+3}" y1="{y+4}" x2="{x+13}" y2="{y+4}" {S}/><line x1="{x+3}" y1="{y+12}" x2="{x+13}" y2="{y+12}" {S}/><line x1="{x+3}" y1="{y+4}" x2="{x+13}" y2="{y+12}" {S}/>')
def _path(x, y):
    return f'<line x1="{x+1}" y1="{y+8}" x2="{x+15}" y2="{y+8}" stroke="#333" stroke-dasharray="3 2"/><polyline points="{x+4},{y+5} {x+1},{y+8} {x+4},{y+11}" {S}/><polyline points="{x+12},{y+5} {x+15},{y+8} {x+12},{y+11}" {S}/>'
def _object(x, y):
    return f'<rect x="{x+1}" y="{y+2}" width="14" height="12" {S}/><line x1="{x+1}" y1="{y+6}" x2="{x+15}" y2="{y+6}" {S}/>'
def _contract(x, y):
    return _object(x, y) + f'<line x1="{x+1}" y1="{y+10}" x2="{x+15}" y2="{y+10}" {S}/>'
def _product(x, y):
    return f'<rect x="{x+1}" y="{y+2}" width="14" height="12" {S}/><rect x="{x+1}" y="{y+2}" width="7" height="4" {S}/>'
def _stakeholder(x, y):
    return f'<rect x="{x+3}" y="{y+4}" width="10" height="8" {S}/><ellipse cx="{x+13}" cy="{y+8}" rx="2.5" ry="4" fill="white" stroke="#333"/><path d="M{x+3},{y+4} a2.5,4 0 0 0 0,8" {S}/>'
def _driver(x, y):
    return (f'<circle cx="{x+8}" cy="{y+8}" r="6" {S}/><circle cx="{x+8}" cy="{y+8}" r="1.5" fill="#333"/>'
            f'<line x1="{x+8}" y1="{y+1}" x2="{x+8}" y2="{y+15}" {S}/><line x1="{x+1}" y1="{y+8}" x2="{x+15}" y2="{y+8}" {S}/>'
            f'<line x1="{x+3}" y1="{y+3}" x2="{x+13}" y2="{y+13}" {S}/><line x1="{x+13}" y1="{y+3}" x2="{x+3}" y2="{y+13}" {S}/>')
def _assessment(x, y):
    return f'<circle cx="{x+6}" cy="{y+6}" r="4.5" {S}/><line x1="{x+9.5}" y1="{y+9.5}" x2="{x+15}" y2="{y+15}" stroke="#333" stroke-width="2"/>'
def _goal(x, y):
    return f'<circle cx="{x+8}" cy="{y+8}" r="7" {S}/><circle cx="{x+8}" cy="{y+8}" r="4" {S}/><circle cx="{x+8}" cy="{y+8}" r="1.5" fill="#333"/>'
def _outcome(x, y):
    return _goal(x, y) + f'<line x1="{x+8}" y1="{y+8}" x2="{x+16}" y2="{y}" stroke="#333" stroke-width="1.5"/><polyline points="{x+12},{y} {x+16},{y} {x+16},{y+4}" {S}/>'
def _principle(x, y):
    return f'<rect x="{x+2}" y="{y+1}" width="12" height="14" {S}/><line x1="{x+8}" y1="{y+4}" x2="{x+8}" y2="{y+10}" stroke="#333" stroke-width="2"/><circle cx="{x+8}" cy="{y+12.5}" r="1" fill="#333"/>'
def _requirement(x, y):
    return f'<polygon points="{x+4},{y+3} {x+15},{y+3} {x+12},{y+13} {x+1},{y+13}" {S}/>'
def _constraint(x, y):
    return _requirement(x, y) + f'<line x1="{x+7}" y1="{y+3}" x2="{x+4}" y2="{y+13}" {S}/>'
def _meaning(x, y):
    return f'<path d="M{x+4},{y+12} a3,3 0 0 1 -1,-6 a4,4 0 0 1 7,-3 a3.5,3.5 0 0 1 5,3 a3,3 0 0 1 -1,6 z" {S}/>'
def _value(x, y):
    return f'<ellipse cx="{x+8}" cy="{y+8}" rx="7" ry="4.5" {S}/>'
def _resource(x, y):
    return f'<rect x="{x+1}" y="{y+4}" width="12" height="8" {S}/><rect x="{x+13}" y="{y+6}" width="2" height="4" fill="#333"/><line x1="{x+4}" y1="{y+6}" x2="{x+4}" y2="{y+10}" {S}/><line x1="{x+7}" y1="{y+6}" x2="{x+7}" y2="{y+10}" {S}/><line x1="{x+10}" y1="{y+6}" x2="{x+10}" y2="{y+10}" {S}/>'
def _capability(x, y):
    return f'<rect x="{x+1}" y="{y+11}" width="4" height="4" {S}/><rect x="{x+6}" y="{y+6}" width="4" height="9" {S}/><rect x="{x+11}" y="{y+1}" width="4" height="14" {S}/>'
def _coa(x, y):
    return f'<circle cx="{x+6}" cy="{y+10}" r="5" {S}/><circle cx="{x+6}" cy="{y+10}" r="2" {S}/><line x1="{x+6}" y1="{y+10}" x2="{x+15}" y2="{y+1}" {S}/><polyline points="{x+11},{y+1} {x+15},{y+1} {x+15},{y+5}" {S}/>'
def _workpkg(x, y):
    return f'<path d="M{x+13},{y+4} a6,6 0 1 0 1,5" {S}/><polyline points="{x+10},{y+2} {x+14},{y+4} {x+12},{y+8}" {S}/>'
def _plateau(x, y):
    return f'<line x1="{x+1}" y1="{y+5}" x2="{x+13}" y2="{y+5}" stroke="#333" stroke-width="2"/><line x1="{x+3}" y1="{y+9}" x2="{x+15}" y2="{y+9}" stroke="#333" stroke-width="2"/><line x1="{x+1}" y1="{y+13}" x2="{x+13}" y2="{y+13}" stroke="#333" stroke-width="2"/>'
def _gap(x, y):
    return f'<circle cx="{x+8}" cy="{y+8}" r="6" {S}/><line x1="{x}" y1="{y+6}" x2="{x+16}" y2="{y+6}" {S}/><line x1="{x}" y1="{y+10}" x2="{x+16}" y2="{y+10}" {S}/>'
def _location(x, y):
    return f'<path d="M{x+8},{y+15} C{x+3},{y+9} {x+2},{y+7} {x+2},{y+5} a6,6 0 0 1 12,0 c0,2 -1,4 -6,10 z" {S}/><circle cx="{x+8}" cy="{y+5}" r="2" {S}/>'
def _equipment(x, y):
    return f'<circle cx="{x+8}" cy="{y+8}" r="5" {S}/><circle cx="{x+8}" cy="{y+8}" r="2" {S}/>' + "".join(
        f'<line x1="{x+8+5*dx}" y1="{y+8+5*dy}" x2="{x+8+7.5*dx}" y2="{y+8+7.5*dy}" stroke="#333" stroke-width="2"/>'
        for dx, dy in ((1,0),(-1,0),(0,1),(0,-1),(.7,.7),(-.7,.7),(.7,-.7),(-.7,-.7)))
def _facility(x, y):
    return f'<polygon points="{x+1},{y+15} {x+1},{y+7} {x+5},{y+10} {x+5},{y+7} {x+9},{y+10} {x+9},{y+7} {x+13},{y+10} {x+13},{y+3} {x+15},{y+3} {x+15},{y+15}" {S}/>'
def _distnet(x, y):
    return f'<line x1="{x+1}" y1="{y+6}" x2="{x+15}" y2="{y+6}" {S}/><line x1="{x+1}" y1="{y+10}" x2="{x+15}" y2="{y+10}" {S}/><polyline points="{x+4},{y+3} {x+1},{y+6} {x+4},{y+9}" {S}/><polyline points="{x+12},{y+7} {x+15},{y+10} {x+12},{y+13}" {S}/>'
def _material(x, y):
    return f'<polygon points="{x+4},{y+2} {x+12},{y+2} {x+15},{y+8} {x+12},{y+14} {x+4},{y+14} {x+1},{y+8}" {S}/>'

ICONS = {
    "BusinessActor": _actor, "BusinessRole": _role, "BusinessCollaboration": _collab,
    "BusinessProcess": _process, "BusinessFunction": _function, "BusinessInteraction": _interaction,
    "BusinessObject": _object, "Contract": _contract, "Product": _product,
    "ApplicationComponent": _component, "ApplicationCollaboration": _collab,
    "ApplicationProcess": _process, "ApplicationFunction": _function, "ApplicationInteraction": _interaction,
    "DataObject": _object,
    "Node": _node, "Device": _device, "SystemSoftware": _sysw, "TechnologyCollaboration": _collab,
    "TechnologyProcess": _process, "TechnologyFunction": _function, "TechnologyInteraction": _interaction,
    "Artifact": _artifact, "CommunicationNetwork": _network, "Path": _path,
    "Equipment": _equipment, "Facility": _facility, "DistributionNetwork": _distnet, "Material": _material,
    "Stakeholder": _stakeholder, "Driver": _driver, "Assessment": _assessment, "Goal": _goal,
    "Outcome": _outcome, "Principle": _principle, "Requirement": _requirement, "Constraint": _constraint,
    "Meaning": _meaning, "Value": _value,
    "Resource": _resource, "Capability": _capability, "CourseOfAction": _coa,
    "WorkPackage": _workpkg, "Plateau": _plateau, "Gap": _gap, "Location": _location,
}


def icon(t, x, y):
    f = ICONS.get(t)
    return f(x, y) if f else ""


# ---------------- element body shapes ----------------
def shape(t, x, y, w, h, fill):
    st = f'fill="{fill}" stroke="#5c6e82"'
    if t.endswith("Service"):                      # rounded "capsule" rectangle
        return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{min(14, h/3)}" {st}/>'
    if t.endswith("Event"):                        # notched left edge, pointed right
        n = min(12, h / 4)
        return (f'<polygon points="{x},{y} {x+w-n},{y} {x+w},{y+h/2} {x+w-n},{y+h} {x},{y+h} '
                f'{x+n},{y+h/2}" {st}/>')
    if t == "ValueStream":                         # chevron
        n = min(16, h / 3)
        return (f'<polygon points="{x},{y} {x+w-n},{y} {x+w},{y+h/2} {x+w-n},{y+h} {x},{y+h} '
                f'{x+n},{y+h/2}" {st}/>')
    if t in ("Representation", "Deliverable"):     # wavy bottom edge
        return (f'<path d="M{x},{y} h{w} v{h-8} q-{w/4},-8 -{w/2},0 q-{w/4},8 -{w/2},0 z" {st}/>')
    if t == "Node":                                # 3-D box
        d = 8
        return (f'<polygon points="{x},{y+d} {x+d},{y} {x+w},{y} {x+w},{y+h-d} {x+w-d},{y+h} {x},{y+h}" {st}/>'
                f'<polyline points="{x},{y+d} {x+w-d},{y+d} {x+w},{y}" fill="none" stroke="#5c6e82"/>'
                f'<line x1="{x+w-d}" y1="{y+d}" x2="{x+w-d}" y2="{y+h}" stroke="#5c6e82"/>')
    if t == "Grouping":
        return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" {st} stroke-dasharray="6 4"/>'
    if t in ("Junction", "AndJunction", "OrJunction"):
        return f'<circle cx="{x+w/2}" cy="{y+h/2}" r="{min(w,h)/2}" fill="#333"/>'
    if t.endswith("Object") or t in ("Contract", "Artifact"):   # banded header (objects) / page (artifact)
        if t == "Artifact":
            return (f'<polygon points="{x},{y} {x+w-12},{y} {x+w},{y+12} {x+w},{y+h} {x},{y+h}" {st}/>'
                    f'<polyline points="{x+w-12},{y} {x+w-12},{y+12} {x+w},{y+12}" fill="none" stroke="#5c6e82"/>')
        return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" {st}/>'
                f'<line x1="{x}" y1="{y+14}" x2="{x+w}" y2="{y+14}" stroke="#5c6e82"/>'
                + (f'<line x1="{x}" y1="{y+24}" x2="{x+w}" y2="{y+24}" stroke="#5c6e82"/>' if t == "Contract" else ""))
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" {st}/>'


def label_dy(t):
    """Objects carry a header band; push the name below it."""
    return 8 if (t.endswith("Object") or t == "Contract") else 0


# ---------------- relationship notation ----------------
# Line-end markers — each relationship type must be tellable at a glance. Emitted once per SVG
# (inside <defs>); REL_STYLE refers to them by id.
MARKER_DEFS = (
    '<defs>'
    '<marker id="arrF" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">'
    '<polygon points="0 0, 10 4, 0 8" fill="#444"/></marker>'
    '<marker id="arrO" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">'
    '<polyline points="0 0, 9 4, 0 8" fill="none" stroke="#444"/></marker>'
    '<marker id="triH" markerWidth="12" markerHeight="10" refX="11" refY="5" orient="auto">'
    '<polygon points="0 0, 11 5, 0 10" fill="white" stroke="#444"/></marker>'
    '<marker id="diaF" markerWidth="14" markerHeight="8" refX="1" refY="4" orient="auto">'
    '<polygon points="1 4, 7 0, 13 4, 7 8" fill="#444"/></marker>'
    '<marker id="diaH" markerWidth="14" markerHeight="8" refX="1" refY="4" orient="auto">'
    '<polygon points="1 4, 7 0, 13 4, 7 8" fill="white" stroke="#444"/></marker>'
    '<marker id="dot" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto">'
    '<circle cx="4" cy="4" r="3" fill="#444"/></marker>'
    '</defs>'
)

# (stroke-dasharray, marker-start, marker-end) per ArchiMate 3.x notation
REL_STYLE = {
    "Composition":    ("",    "diaF", None),
    "Aggregation":    ("",    "diaH", None),
    "Assignment":     ("",    "dot",  "arrF"),
    "Realization":    ("2 3", None,   "triH"),
    "Specialization": ("",    None,   "triH"),
    "Serving":        ("",    None,   "arrO"),
    "Access":         ("2 3", None,   "arrO"),
    "Influence":      ("6 4", None,   "arrO"),
    "Triggering":     ("",    None,   "arrF"),
    "Flow":           ("6 4", None,   "arrF"),
    "Association":    ("",    None,   None),
}


def rel_style(rt):
    """Line notation for a relationship type; an unknown type draws a plain filled arrow."""
    return REL_STYLE.get(rt, ("", None, "arrF"))
