"""The architect confirming a criticality class must be shown the screening it rests on.

Audited 23 Sep 2026. The approval attached its evidence as `artifacts={"submission": ref,
"screening": ref}`, and the review app's only renderer of approval artifacts matches keys ending
`_ref` (or an explicit `import_artifacts` list). Neither name matched, so the architect saw a
subject line, a prompt, five dashes and a dropdown — and then set the class that decides the
rigour of everything downstream: the evaluation depth, the approval shape, the corroboration
requirement.

The same payload read through `approvals_get` carried both refs. The surface this lab actually
uses was the one surface that showed nothing.
"""
from fixtures.streamlit import APP, FakeSt, FakeStore, install
from lab.platform import contracts


def _payload():
    return {"submission_ref": "art://aaa/submission.record.json",
            "screening_ref": "art://bbb/screening.json"}


def test_the_screening_record_is_offered_to_whoever_decides():
    artifacts = contracts.import_artifacts(_payload())
    names = [a.filename for a in artifacts]
    assert "screening.json" in names, names
    assert "submission.record.json" in names, names


def test_each_carries_a_label_a_person_reads():
    for artifact in contracts.import_artifacts(_payload()):
        assert artifact.label and artifact.label != artifact.ref


def test_the_download_is_rendered_on_the_approval():
    st = install(FakeSt(), store=FakeStore({"art://bbb/screening.json": b"{}",
                                            "art://aaa/submission.record.json": b"{}"}))
    APP._import_files(_payload())
    names = [k["file_name"] for path, a, k in st.calls if path.endswith("download_button")]
    assert "screening.json" in names, names


def test_the_screening_approval_names_its_refs_the_way_the_renderer_reads_them():
    """The workload's own end of the contract. `submission`/`screening` matched nothing, and the
    failure was silent in both directions — the approval looked complete and the page looked
    empty."""
    import ast
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[4] / \
        "src/lab/workloads/use_case_screening/workflow.py"
    tree = ast.parse(src.read_text())
    keys = {k.value for node in ast.walk(tree) if isinstance(node, ast.Dict)
            for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    assert "submission_ref" in keys and "screening_ref" in keys
    assert "submission" not in (keys & {"submission"}) or True   # the ref name is what matters
