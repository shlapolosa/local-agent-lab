"""The artifacts a step created, findable from the step that created them.

A run writes its outputs by REFERENCE (`art://<id>/<name>`), and until now a watcher could see
that a ref existed — it is a value, and values are shown — but had no way to open one. The refs
are collected from the step's own output and stamped on its node, so the page offers a link per
artifact without knowing what any of them IS.

Found by SCHEME, never by field name: `screening_ref`, `xml_ref`, `svg_refs`, `record_ref` and
whatever the next step calls its output are all just strings that start with `art://`, and a list
of known field names is a list to forget to update.
"""
from lab.workloads.usecase import derivation as D


def test_a_ref_anywhere_in_the_output_is_found_by_its_scheme():
    out = {"screening_ref": "art://abc123/screening.json", "band": "business-critical"}
    assert D.artifacts_in(out) == [{"ref": "art://abc123/screening.json",
                                    "name": "screening.json"}]


def test_refs_nested_in_lists_and_dicts_are_found_too():
    """`svg_refs` is a list; a staged import puts refs inside objects. Neither is special-cased."""
    out = {"views": {"svg_refs": ["art://a/one.svg", "art://b/two.svg"]},
           "import_artifacts": [{"ref": "art://c/objects.xlsx", "label": "Objects"}]}
    assert [a["name"] for a in D.artifacts_in(out)] == ["one.svg", "two.svg", "objects.xlsx"]


def test_the_same_ref_twice_is_offered_once():
    out = {"a": "art://x/one.svg", "b": "art://x/one.svg"}
    assert len(D.artifacts_in(out)) == 1


def test_a_string_that_is_not_a_ref_is_not_an_artifact():
    """Prose mentioning a scheme, a malformed ref, or an ordinary sentence must not become a link
    that 404s — a broken download reads as a lost artifact."""
    out = {"note": "we store things as art:// refs", "bad": "art://", "prose": "nothing here"}
    assert D.artifacts_in(out) == []


def test_an_output_that_is_not_a_mapping_yields_nothing_rather_than_raising():
    assert D.artifacts_in("a string") == [] and D.artifacts_in(None) == []


def test_the_page_is_offered_with_the_ref_so_a_multi_page_source_still_opens():
    out = {"src": "art://d/malaffi.vsdx#Shafafiya"}
    assert D.artifacts_in(out) == [{"ref": "art://d/malaffi.vsdx#Shafafiya",
                                    "name": "malaffi.vsdx"}]


def test_the_stamp_carries_the_artifacts_beside_the_shape(monkeypatch):
    from lab.platform import runlog
    from lab.workloads.usecase.steps import step_for
    seen = {}
    monkeypatch.setattr(runlog, "node", lambda rid, name, status, **kw: seen.update(kw))
    D.stamp_shape({"run_id": "r1"}, step_for("5"), {"ref": "art://abc/coverage.json"})
    assert seen["artifacts"] == [{"ref": "art://abc/coverage.json", "name": "coverage.json"}]


def test_a_step_that_wrote_nothing_stamps_no_artifacts(monkeypatch):
    from lab.platform import runlog
    from lab.workloads.usecase.steps import step_for
    seen = {}
    monkeypatch.setattr(runlog, "node", lambda rid, name, status, **kw: seen.update(kw))
    D.stamp_shape({"run_id": "r1"}, step_for("5"), {"matched": []})
    assert seen.get("artifacts") is None, "an empty list would put an empty heading on every step"
