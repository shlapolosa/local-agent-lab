"""archimate_engine beyond the golden render: multi-domain <organizations> tree, ADOIT `id_<uuid>`
reuse, the standard-view catalogue, nested/container views, interface icons, junctions, strict vs
lenient invariants (H4, XSD), the coarse validator when the semantic layer is unavailable, routing
edge cases (same-row, long/gutter, cyclic Serving), SVG output. Structure checks via xml.etree,
never byte-equality. Offline. Run: .venv/bin/python tests/unit/core/archimate/test_engine_more.py   (also pytest)"""
import importlib.util
import os
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
SCRIPTS = os.path.join(ROOT, "src", "lab", "core", "archimate")

from lab.core.archimate import engine as E  # noqa: E402

AM = "{http://www.opengroup.org/xsd/archimate/3.0/}"
XSI = "{http://www.w3.org/2001/XMLSchema-instance}"
UUID = "{3F2504E0-4F89-11D3-9A0C-0305E82C3301}"          # ADOIT REST id shape (braces, upper-case)


def parse(xml):
    return ET.fromstring(xml.encode())


def layered():
    """One element per layer + relations that make every standard mapping view non-empty."""
    m = E.Model("Layered", mid="lay")
    m.el("goal", "Goal", "Parity", folder="Governance")
    m.el("cap", "Capability", "Govern", folder="Governance")
    m.el("proc", "BusinessProcess", "Intake", folder="Intake")
    m.el("svc", "ApplicationService", "Routing", folder="Intake")
    m.el("comp", "ApplicationComponent", "Gateway", folder="Intake")
    m.el("node", "Node", "Host", folder="Platform")
    m.el("plateau", "Plateau", "Now", folder="Platform")
    m.el("orphan", "Deliverable", "Unfiled")                 # no folder -> not in <organizations>
    m.rel("Realization", "cap", "goal")
    m.rel("Realization", "proc", "cap")
    m.rel("Serving", "svc", "proc")
    m.rel("Realization", "comp", "svc")
    m.rel("Serving", "node", "comp")
    m.rel("Aggregation", "plateau", "comp")
    return m


def test_model_declaration_errors():
    m = E.Model("t")
    for bad in (lambda: m.el("x", "NotAType", "x"),
                lambda: m.rel("Serving", "a", "b"),
                lambda: (m.el("a", "Node", "a"), m.rel("Owns", "a", "a")),
                lambda: (m.el("a", "Node", "a"), m.rel("Serving", "a", "zzz"))):
        try:
            bad()
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")
    v = m.view("v", "V")
    try:
        v.place("zzz")
    except ValueError as e:
        assert "not declared" in str(e)
    else:
        raise AssertionError("place() must reject an undeclared element")
    try:
        v.container("a", ["zzz"])
    except ValueError as e:
        assert "place() child" in str(e)
    else:
        raise AssertionError("container() must reject an unplaced child")


def test_ident_and_safe_reuse_adoit_uuids():
    assert E._ident("gw") == "id-gw" and E._safe("gw") == "gw"
    assert E._ident(UUID) == "id_3f2504e0-4f89-11d3-9a0c-0305e82c3301" == E._ident(UUID.strip("{}"))
    assert E._safe(UUID) == "3F2504E0-4F89-11D3-9A0C-0305E82C3301"
    m = E.Model("Reuse", mid="reuse")
    m.el(UUID, "ApplicationComponent", "Existing")
    m.el("new", "ApplicationService", "New")
    m.rel("Realization", UUID, "new", rid="r-x")
    v = m.view("v", "V"); v.place(UUID, "new"); v.auto_edges()
    root = parse(m.to_xml())
    ids = {e.get("identifier") for e in root.iter(f"{AM}element")}
    assert ids == {"id_3f2504e0-4f89-11d3-9a0c-0305e82c3301", "id-new"}
    rel = root.find(f".//{AM}relationship")
    assert rel.get("source") == "id_3f2504e0-4f89-11d3-9a0c-0305e82c3301" and rel.get("target") == "id-new"
    nodes = {n.get("identifier"): n.get("elementRef") for n in root.iter(f"{AM}node")}
    assert nodes["id-n-v-3F2504E0-4F89-11D3-9A0C-0305E82C3301"] == "id_3f2504e0-4f89-11d3-9a0c-0305e82c3301"
    assert "{" not in m.to_xml()


def test_organizations_tree_by_domain_then_layer():
    m = layered()
    root = parse(m.to_xml())
    org = root.find(f"{AM}organizations")
    assert org is not None
    # schema order: elements, relationships, organizations (no views -> no <views>)
    assert [c.tag for c in root] == [f"{AM}name", f"{AM}elements", f"{AM}relationships", f"{AM}organizations"]
    tree = {}
    for dom in org:
        layers = tree.setdefault(dom.find(f"{AM}label").text, {})
        for lay in dom.findall(f"{AM}item"):
            layers[lay.find(f"{AM}label").text] = [i.get("identifierRef") for i in lay.findall(f"{AM}item")]
    assert tree == {"Governance": {"Motivation": ["id-goal"], "Strategy": ["id-cap"]},
                    "Intake": {"Application": ["id-svc", "id-comp"], "Business": ["id-proc"]},
                    "Platform": {"Implementation": ["id-plateau"], "Technology": ["id-node"]}}
    assert "id-orphan" not in m.to_xml().split("<organizations>")[1]
    # classification annotation prefixes every documentation
    docs = [d.text for d in root.iter(f"{AM}documentation")]
    assert len(docs) == 8 and all(d.startswith("[") and " — " in d for d in docs)
    # no folders -> no <organizations>, no relations -> no <relationships>
    bare = E.Model("bare"); bare.el("a", "Node", "A")
    r = parse(bare.to_xml())
    assert r.find(f"{AM}organizations") is None and r.find(f"{AM}relationships") is None
    assert bare.to_spec() == {"name": "bare", "id": "model", "elements": [{"id": "a", "type": "Node", "name": "A"}], "relations": []}


def test_standard_views_catalogue_skips_empty_and_edgeless():
    m = layered()
    made = m.standard_views(prefix="std-")
    assert set(made) == {"mot-strategy", "strategy-biz", "biz-app", "app-tech", "impl-roadmap", "full"}
    assert [v.vid for v in m.views] == [f"std-{k}" for k in made]
    assert {s for _, s, _ in made["impl-roadmap"].edges} == {"plateau"}        # expand=True pulled comp in
    assert set(made["impl-roadmap"].nodes) == {"plateau", "orphan", "comp"}   # Deliverable is Implementation too
    assert len(made["full"].nodes) == 8 and len(made["full"].edges) == 6       # orphan Deliverable has no relation
    # a layer with elements but no relationships among them says nothing -> view removed
    m2 = E.Model("impl"); m2.el("p", "Plateau", "P"); m2.el("c", "ApplicationComponent", "C")
    assert m2.standard_views() == {} and m2.views == []
    assert m2.layer_view("none", "None", ("Motivation",)) is None
    xml = m.to_xml(strict=True)
    root = parse(xml)
    assert len(root.findall(f".//{AM}view")) == 6 and m._report["violations"] == []


def test_nested_container_view_and_interface_icons():
    m = E.Model("Cap", mid="cap")
    m.el("l1", "Capability", "Care")
    m.el("l2a", "Capability", "Triage"); m.el("l2b", "Capability", "Discharge")
    m.el("api", "ApplicationInterface", "/v1")
    m.el("svc", "ApplicationService", "Routing")
    m.el("comp", "ApplicationComponent", "Gateway")
    m.rel("Composition", "l1", "l2a", rid="c1"); m.rel("Composition", "l1", "l2b", rid="c2")
    m.rel("Composition", "comp", "api", rid="c3"); m.rel("Assignment", "api", "svc", rid="a1")
    m.rel("Realization", "comp", "svc", rid="r1")
    v = m.view("nest", "Nested")
    v.place("l2a", "l2b", order=0)
    v.container("l1", ["l2a", "l2b"])
    v.place("api", "svc", "comp")
    v.auto_edges()
    assert {r for r, _, _ in v.edges} == {"c3", "a1", "r1"}          # c1/c2 shown by nesting, not lines
    assert v.nodes["api"]["icon"] and v.nodes["api"]["w"] == v.nodes["api"]["h"] == E.View.ICON
    xml = m.to_xml(strict=True)
    root = parse(xml)
    view = root.find(f".//{AM}view")
    top = {n.get("elementRef"): n for n in view.findall(f"{AM}node")}
    assert set(top) == {"id-l1", "id-api", "id-svc", "id-comp"}
    kids = [n.get("elementRef") for n in top["id-l1"].findall(f"{AM}node")]
    assert kids == ["id-l2a", "id-l2b"]
    cx, cy, cw, ch = (int(top["id-l1"].get(k)) for k in "xywh")
    for k in top["id-l1"].findall(f"{AM}node"):                        # children lie inside the container
        kx, ky, kw, kh = (int(k.get(a)) for a in "xywh")
        assert cx < kx and kx + kw < cx + cw and cy < ky and ky + kh <= cy + ch
    assert top["id-l1"].find(f"{AM}style/{AM}font").get("size") == "11"   # container caption font
    assert top["id-api"].get("w") == "30"
    assert len(view.findall(f"{AM}connection")) == 3
    svg = v.to_svg()
    assert svg.count('r="15.0" fill=') == 1 and 'stroke-dasharray="4 3"' in svg   # interface icon + dashed container
    assert svg.count("<text") == 1 + 6                                         # title + every element name
    assert "Triage" in svg and "Discharge" in svg


def test_junctions_and_svg_from_cold_view():
    m = E.Model("J")
    m.el("e1", "BusinessEvent", "Claim received"); m.el("j", "Junction", "")
    m.el("p1", "BusinessProcess", "Verify"); m.el("p2", "BusinessProcess", "Register")
    m.rel("Triggering", "e1", "j"); m.rel("Triggering", "j", "p1"); m.rel("Triggering", "j", "p2")
    v = m.view("flow", "Flow"); v.place("e1", "j", "p1", "p2"); v.auto_edges()
    svg = v.to_svg()                                    # builds the layout itself (no render() first)
    assert 'fill="#333"/>' in svg and "<polyline" in svg and 'marker-end="url(#arrF)"' in svg
    assert m.validate_relations() == []                 # the matrix knows Junction (not the And/Or subtypes)
    m.el("aj", "AndJunction", ""); m.el("oj", "OrJunction", "")
    root = parse(m.to_xml())
    assert root.find(f".//{AM}element[@identifier='id-aj']").get(f"{XSI}type") == "AndJunction"
    assert root.find(f".//{AM}element[@identifier='id-oj']").get(f"{XSI}type") == "OrJunction"
    assert E.rank_of("AndJunction") == E.rank_of("OrJunction") == E.rank_of("Junction")


def test_strict_raises_on_h4_and_lenient_reports():
    m = E.Model("H4")
    m.el("svc", "ApplicationService", "S"); m.el("proc", "BusinessProcess", "P")
    m.rel("Serving", "svc", "proc", rid="s1")
    v = m.view("v", "V"); v.place("svc", rank=0); v.place("proc", rank=1); v.auto_edges()   # served pinned BELOW
    try:
        m.to_xml(strict=True)
    except AssertionError as e:
        assert "H4 Serving s1 points downward" in str(e)
    else:
        raise AssertionError("strict must raise on an invariant violation")
    xml = m.to_xml(strict=False)
    assert m._report["violations"] == ["[v] H4 Serving s1 points downward (served/realized must sit above)"]
    assert parse(xml).find(f".//{AM}connection") is not None
    with tempfile.TemporaryDirectory() as d:
        rep = m.render(d, "h4", strict=False)
        assert rep["violations"][0].startswith("[v] H4") and os.path.exists(os.path.join(d, "h4-v.svg"))


def test_xsd_gate_strict_and_lenient():
    m = E.Model("bad"); m.el("bad id", "Node", "N")          # a space is not an NCName -> schema-invalid
    with tempfile.TemporaryDirectory() as d:
        try:
            m.render(d, "bad", strict=True)
        except AssertionError as e:
            assert "schema-invalid export" in str(e) and "XSD:" in str(e)
        else:
            raise AssertionError("XSD errors must fail a strict render")
        rep = m.render(d, "bad", strict=False)
        assert rep["schema_validated"] is True and rep["violations"] and rep["violations"][0].startswith("XSD:")
        assert rep["files"] == [os.path.join(d, "bad.archimate.xml")]


def test_routing_edge_cases_same_row_long_edges_and_cycle():
    m = E.Model("R")
    for i in range(3):
        m.el(f"c{i}", "ApplicationComponent", f"C{i}")
    m.el("d", "DataObject", "D"); m.el("g", "Goal", "G"); m.el("n", "Node", "N")
    m.rel("Flow", "c0", "c1", rid="same-row")               # same rank -> lane below the row
    m.rel("Flow", "c1", "c0", rid="same-row-back")           # parallel, opposite direction
    m.rel("Realization", "c2", "g", rid="straight")          # adjacent rows, aligned -> one straight vertical
    m.rel("Serving", "n", "c0", rid="up")                    # spans the data row -> side gutter route
    m.rel("Access", "c0", "d", rid="acc", accessType="Write")
    v = m.view("v", "V"); v.place("c0", "c1", "c2", "d", "g", "n"); v.auto_edges()
    xml = m.to_xml(strict=True)
    assert m._report["violations"] == [] and v.has_long
    root = parse(xml)
    bends = {c.get("relationshipRef"): len(c.findall(f"{AM}bendpoint")) for c in root.iter(f"{AM}connection")}
    assert bends == {"id-same-row": 2, "id-same-row-back": 2, "id-straight": 0, "id-up": 4, "id-acc": 2}, bends
    route = {e["rid"]: e for e in v._E}
    assert route["straight"]["straight"] and route["up"]["gx"] is not None and route["same-row"]["d"] == 0
    assert root.find(f".//{AM}relationship[@identifier='id-acc']").get("accessType") == "Write"
    assert all(int(n.get("x")) >= 0 and int(n.get("y")) >= 0 for n in root.iter(f"{AM}node"))
    # a Serving cycle with nothing pinned: the rank relaxation gives up after its bounded sweeps
    c = E.Model("cyc"); c.el("a", "ApplicationComponent", "A"); c.el("b", "ApplicationComponent", "B")
    c.rel("Serving", "a", "b", rid="ab"); c.rel("Serving", "b", "a", rid="ba")
    cv = c.view("v", "V"); cv.place("a", "b"); cv.auto_edges()
    c.to_xml(strict=False)
    assert any("H4" in x for x in c._report["violations"])


def test_coarse_validator_when_semantic_layer_is_unavailable():
    m = E.Model("coarse")
    m.el("comp", "ApplicationComponent", "C"); m.el("data", "DataObject", "D"); m.el("proc", "BusinessProcess", "P")
    m.el("goal", "Goal", "G"); m.el("art", "Artifact", "A"); m.el("node", "Node", "N"); m.el("svc", "ApplicationService", "S")
    m.el("api", "ApplicationInterface", "I"); m.el("plat", "Plateau", "Now")
    cases = [  # (rid, type, src, tgt, expected fragment or None when legal)
        ("a1", "Access", "comp", "proc", "Access must target a passive element"),
        ("a2", "Access", "data", "art", "Access cannot originate from passive element"),
        ("s1", "Serving", "data", "comp", "Serving cannot involve a passive element"),
        ("i1", "Influence", "comp", "proc", "Influence must target a Motivation element"),
        ("g1", "Assignment", "proc", "comp", "Assignment source must be active structure"),
        ("g2", "Assignment", "node", "data", "Assignment cannot target passive element"),
        ("g3", "Assignment", "node", "art", None),
        ("t1", "Triggering", "comp", "data", "Triggering connects behaviour/active elements"),
        ("c1", "Composition", "comp", "proc", "Composition across layers (Application->Business)"),
        ("c2", "Aggregation", "plat", "comp", None),                     # Implementation may aggregate anything
        ("p1", "Specialization", "comp", "svc", "Specialization should relate same types"),
        ("ok1", "Realization", "comp", "svc", None),
        ("ok2", "Assignment", "api", "svc", None),
        ("ok3", "Access", "comp", "data", None),
        ("ok4", "Influence", "proc", "goal", None),
    ]
    for rid, t, s, g, _ in cases:
        m.rel(t, s, g, rid=rid)
    exact = m.validate_relations()
    assert any("not permitted" in w for w in exact)                    # the semantic layer is live here
    orig = E._semantic
    E._semantic = lambda: None
    try:
        warns = m.validate_relations()
    finally:
        E._semantic = orig
    got = {w.split(" ")[0]: w for w in warns}
    for rid, t, s, g, frag in cases:
        if frag is None:
            assert rid not in got, got.get(rid)
        else:
            assert rid in got and frag in got[rid] and f"({t} {s}->{g})" in got[rid], (rid, got.get(rid))
    assert all("not permitted" not in w for w in warns)


def test_semantic_cache_falls_back_when_service_import_fails():
    E._semantic.cache_clear()
    saved = sys.modules.get("lab.core.semantic.service")
    sys.modules["lab.core.semantic.service"] = None                      # `from lab.core.semantic.service import …` -> ImportError
    try:
        assert E._semantic() is None
    finally:
        E._semantic.cache_clear()
        if saved is not None:
            sys.modules["lab.core.semantic.service"] = saved
        else:
            del sys.modules["lab.core.semantic.service"]
    assert E._semantic() is not None


def test_standalone_copy_without_taxonomy_semantic_or_xsd():
    """A skill copy dropped somewhere without references/ or the repo: static tables, coarse
    validator, no XSD gate — same XML structure."""
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "scripts"))
        for f in ("engine.py", "notation.py"):
            shutil.copy(os.path.join(SCRIPTS, f), os.path.join(d, "scripts", f))
        spec = importlib.util.spec_from_file_location("archimate_engine_standalone", os.path.join(d, "scripts", "engine.py"))
        S = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(S)
        assert S._TAXONOMY == {} and S._TYPES == {**S._FALLBACK_TYPES} and S._ROOT is None
        assert S._semantic() is None
        assert S._aspect("Stakeholder") == "Active" and S._aspect("Gap") == "Passive" and S._aspect("Goal") == "Behaviour"
        assert S.rank_of("ApplicationService") < S.rank_of("ApplicationComponent") < S.rank_of("DataObject")
        m = S.Model("standalone"); m.el("c", "ApplicationComponent", "C", doc="custom doc"); m.el("s", "ApplicationService", "S")
        m.rel("Realization", "c", "s"); v = m.view("v", "V"); v.place("c", "s"); v.auto_edges()
        assert m.validate_relations() == []
        rep = m.render(d, "sa", strict=True)
        assert rep["schema_validated"] is False and rep["violations"] == []
        root = parse(open(rep["files"][0]).read())
        docs = [x.text for x in root.iter(f"{AM}documentation")]
        assert docs == ["custom doc"]                               # no taxonomy -> no classification prefix
        assert S.Model._XSD is False and S.Model._schema() is False


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
