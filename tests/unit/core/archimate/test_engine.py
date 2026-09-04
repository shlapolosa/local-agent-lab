"""Skill engine — golden render of the lab model, taxonomy-derived classification, notation module.
Offline: uses var/out/architecture/lab_model.json when generated (`python scripts/lab_model.py`), else an
inline slice of it, so the golden render stays meaningful on a fresh clone.
Run: .venv/bin/python tests/unit/core/archimate/test_engine.py   (also pytest-compatible)"""
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SKILL = ROOT / "skills" / "archimate-adoit"

from lab.core.archimate import engine as E  # noqa: E402
from lab.core.archimate import notation as N  # noqa: E402

TAXONOMY = json.load(open(ROOT / "src" / "lab" / "core" / "semantic" / "archimate" / "taxonomy.json"))["elements"]
JUNCTIONS = {"AndJunction", "OrJunction"}          # exchange-format subtypes the taxonomy folds into Junction


def build_model(spec):
    """Spec -> Model, the same shape adoit-mcp's _build() uses."""
    m = E.Model(spec["name"], spec.get("id", "model"))
    for e in spec.get("elements", []):
        m.el(e["id"], e["type"], e["name"], e.get("doc"), folder=e.get("folder"))
    for r in spec.get("relations", []):
        m.rel(r["type"], r["src"], r["tgt"], rid=r.get("id"), accessType=r.get("accessType"))
    for v in spec.get("views", []):
        vw = m.view(v["id"], v["title"])
        if v.get("rows"):
            for i, row in enumerate(v["rows"]):
                vw.place(*row, rank=i)
        else:
            vw.place(*v["elements"])
        for c in v.get("containers", []):
            vw.container(c["id"], children=c["children"])
        vw.auto_edges()
    if spec.get("standard_views"):
        m.standard_views()
    return m


def test_taxonomy_is_one_file():
    link = SKILL / "references" / "archimate-classification.json"
    assert link.is_symlink(), "skill taxonomy copy must be a symlink to src/lab/core/semantic/archimate/taxonomy.json"
    assert link.resolve() == (ROOT / "src" / "lab" / "core" / "semantic" / "archimate" / "taxonomy.json").resolve()
    assert E._TAXONOMY == TAXONOMY


def test_types_and_aspect_derive_from_taxonomy():
    """0 unintended mismatches: layer straight from the taxonomy; aspect = taxonomy aspect with
    ONLY the two deliberate layout buckets (Service, Interface) on top."""
    assert set(E._TYPES) == set(TAXONOMY) | JUNCTIONS
    bad = []
    for t, c in TAXONOMY.items():
        if E._TYPES[t] != c["layer"]:
            bad.append((t, "layer", E._TYPES[t], c["layer"]))
        want = ("Service" if t.endswith("Service") else "Interface" if t.endswith("Interface")
                else c["aspect"].capitalize())
        if E._aspect(t) != want:
            bad.append((t, "aspect", E._aspect(t), want))
    assert not bad, bad
    for j in JUNCTIONS:
        assert E._TYPES[j] == "Other" and E._aspect(j) == E._aspect("Junction") == "Active"
    # the 11 types the old suffix heuristic misfiled as Behaviour
    for t in ("Stakeholder", "CommunicationNetwork", "Path", "DistributionNetwork", "Location",
              "Grouping", "Junction", "BusinessCollaboration", "ApplicationCollaboration",
              "TechnologyCollaboration"):
        assert E._aspect(t) == "Active", t
    assert E._aspect("Gap") == "Passive"
    # every layer/aspect the taxonomy uses has a band/row -> rank_of never KeyErrors
    for t in E._TYPES:
        assert isinstance(E.rank_of(t), int)
    # standalone fallback agrees with the taxonomy (so a skill copy without src/lab/core/semantic/ behaves the same)
    for t, c in TAXONOMY.items():
        assert E._FALLBACK_TYPES[t] == c["layer"], t
        if not t.endswith(("Service", "Interface")):
            assert E._aspect_heuristic(t) == c["aspect"].capitalize(), t


def test_notation_owns_relationship_style():
    assert set(N.REL_STYLE) == {"Composition", "Aggregation", "Assignment", "Realization", "Specialization",
                                "Serving", "Access", "Influence", "Triggering", "Flow", "Association"}
    used = {m for dash, ms, me in N.REL_STYLE.values() for m in (ms, me) if m}
    for marker in used:
        assert f'id="{marker}"' in N.MARKER_DEFS, marker
    assert N.MARKER_DEFS.startswith("<defs>") and N.MARKER_DEFS.endswith("</defs>")
    assert N.rel_style("Realization") == ("2 3", None, "triH")
    assert N.rel_style("NotAType") == ("", None, "arrF")
    assert not hasattr(E.View, "edge"), "View.edge was dead code — deleted"


LAB_MODEL = ROOT / "var" / "out" / "architecture" / "lab_model.json"      # git-ignored; `python scripts/lab_model.py` regenerates it

# A small in-code stand-in for the lab model on a fresh clone (LAB_MODEL absent): every layer, a
# multi-domain folder tree, a nested container view and enough relations for the standard-view
# catalogue — so the golden assertions below hold on the same code paths.
INLINE_SPEC = {"name": "Lab slice", "id": "slice", "standard_views": True, "elements": [
    {"id": "goal", "type": "Goal", "name": "Pattern parity", "folder": "Governance"},
    {"id": "cap", "type": "Capability", "name": "Governance", "folder": "Governance"},
    {"id": "proc", "type": "BusinessProcess", "name": "Intake", "folder": "Intake"},
    {"id": "api", "type": "ApplicationInterface", "name": "/v1", "folder": "Gateway"},
    {"id": "svc", "type": "ApplicationService", "name": "Routing", "folder": "Gateway"},
    {"id": "gw", "type": "ApplicationComponent", "name": "LiteLLM Proxy", "doc": "APIM analogue", "folder": "Gateway"},
    {"id": "data", "type": "DataObject", "name": "Spend ledger", "folder": "Gateway"},
    {"id": "host", "type": "Node", "name": "MacBook", "folder": "Platform"},
    {"id": "now", "type": "Plateau", "name": "Local lab", "folder": "Platform"},
], "relations": [
    {"id": "r1", "type": "Realization", "src": "cap", "tgt": "goal"},
    {"id": "r2", "type": "Realization", "src": "proc", "tgt": "cap"},
    {"id": "r3", "type": "Serving", "src": "svc", "tgt": "proc"},
    {"id": "r4", "type": "Composition", "src": "gw", "tgt": "api"},
    {"id": "r5", "type": "Assignment", "src": "api", "tgt": "svc"},
    {"id": "r6", "type": "Realization", "src": "gw", "tgt": "svc"},
    {"id": "r7", "type": "Access", "src": "gw", "tgt": "data", "accessType": "Write"},
    {"id": "r8", "type": "Serving", "src": "host", "tgt": "gw"},
    {"id": "r9", "type": "Aggregation", "src": "now", "tgt": "gw"},
], "views": [
    {"id": "governance-plane", "title": "Governance Plane", "elements": ["api", "svc", "gw", "data", "host"]},
    {"id": "nested", "title": "Gateway nested", "elements": ["api", "gw"], "containers": [{"id": "gw", "children": ["api"]}]},
]}


def test_golden_render_lab_model():
    spec = json.load(open(LAB_MODEL)) if LAB_MODEL.exists() else INLINE_SPEC
    if spec is INLINE_SPEC:
        print("NOTE: var/out/architecture/lab_model.json not generated — golden render uses the inline spec")
    m = build_model(spec)
    xml = m.to_xml(strict=True)                      # raises on any layout-invariant violation
    assert m._report["violations"] == []
    assert xml.count("<element ") == len(spec["elements"])
    assert xml.count("<relationship ") == len(spec["relations"])
    assert len(m.views) > len(spec["views"])         # standard_views added the catalogue views
    with tempfile.TemporaryDirectory() as d:
        rep = m.render(d, "lab", strict=True)
        assert rep["schema_validated"] is True, "xmlschema missing — XSD gate did not run"
        assert not [v for v in rep["violations"] if v.startswith("XSD")]
        assert len(rep["files"]) == 1 + len(m.views)
        svg = open(os.path.join(d, f"lab-{m.views[0].vid}.svg")).read()
        assert N.MARKER_DEFS in svg and 'marker-end="url(#' in svg
    assert all(isinstance(w, str) for w in m.validate_relations())


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"ok  {name}")
    print("ALL TESTS PASSED")
