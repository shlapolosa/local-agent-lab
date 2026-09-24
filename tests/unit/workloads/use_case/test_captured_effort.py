"""The effort a submitter captured beats the effort an agent inferred.

Q25 of the real intake asks, per role: how many people, how often, how long it takes now and how
long it would take. `benefit.operational_efficiency` needs exactly that, typed. Until now the only
producer was step 24's AGENT — which is not even shown the intake, so its prompt tells it to cite
"the intake field it came from", a source it structurally cannot see.

So the table is a declared input, and the design run prefers what a person captured over what an
agent reconstructed. Not because the agent is bad at it: because one of them is EVIDENCE and the
other is an inference, and driver 1 is the only driver with real data in every submission.
"""
from lab.platform.contracts import InputKind, PROCESSES

SPEC = PROCESSES["use_case_screening"]


def test_the_effort_table_is_a_declared_typed_input():
    field = SPEC.field("effort")
    assert field.kind is InputKind.TABLE and not field.required
    assert {c.name for c in field.columns} >= {
        "role", "headcount", "current_minutes", "expected_minutes"}


def test_its_columns_are_the_fields_the_formula_actually_reads():
    """Named for the domain, so the row needs no translation on the way in."""
    from lab.core.usecase import benefit
    declared = {c.name for c in SPEC.field("effort").columns}
    assert set(benefit._EFFORT_FIELDS) <= declared, sorted(set(benefit._EFFORT_FIELDS) - declared)


def test_a_real_two_role_answer_survives_the_contract():
    """37 % of real submissions list two or three roles — the case the mapping could not hold."""
    out = SPEC.validate({"submitter": "o@m.ae", "submission": "art://a/u.md", "effort": [
        {"role": "mid", "headcount": "2", "frequency_per_week": "1",
         "current_minutes": "180", "expected_minutes": "30"},
        {"role": "lead", "headcount": "1", "frequency_per_week": "1",
         "current_minutes": "120", "expected_minutes": "20"}]})
    assert len(out["effort"]) == 2
    assert out["effort"][0]["headcount"] == 2.0


def test_the_captured_table_is_what_the_benefit_call_uses():
    from lab.workloads.use_case_design import workflow as design
    captured = [{"role": "mid", "headcount": 2.0, "frequency_per_week": 1.0,
                 "current_minutes": 180.0, "expected_minutes": 30.0}]
    inferred = [{"role": "guessed", "headcount": 1.0, "frequency_per_week": 1.0,
                 "current_minutes": 60.0, "expected_minutes": 10.0}]
    assert design.effort_rows({"effort": captured}, {"effort": inferred}) == captured


def test_the_agent_s_answer_still_stands_when_nobody_captured_one():
    from lab.workloads.use_case_design import workflow as design
    inferred = [{"role": "guessed", "headcount": 1.0}]
    assert design.effort_rows({}, {"effort": inferred}) == inferred
    assert design.effort_rows({"effort": []}, {"effort": inferred}) == inferred


def test_the_captured_table_travels_on_the_submission_record():
    """The design half reads the RECORD, never the original submit, and driver 1 is computed
    there. A table captured at intake that stopped at the screening boundary would be evidence
    collected and thrown away."""
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[4]
    for path, key in ((root / "src/lab/workloads/use_case_screening/workflow.py", "effort"),
                      (root / "src/lab/workloads/use_case_design/workflow.py", "effort")):
        tree = ast.parse(path.read_text())
        keys = {k.value for node in ast.walk(tree) if isinstance(node, ast.Dict)
                for k in node.keys if isinstance(k, ast.Constant)}
        assert key in keys, f"{path.name} does not carry {key!r}"
