"""The shared gate — what a retry is told."""


def test_a_retry_is_told_every_missing_key_not_the_first_five():
    """Facet vectors require nine conditions on every workflow step; a schema shortfall of four
    keys on ten steps is forty problems, and a refusal cut to five left the model unable to
    comply on its one retry (13 Sep 2026)."""
    from jsonschema import Draft202012Validator
    from lab.workloads import gates
    schema = {"type": "object", "properties": {"steps": {"type": "array", "items": {
        "type": "object", "required": [f"c{i}" for i in range(4)],
        "properties": {f"c{i}": {"type": "boolean"} for i in range(4)}}}}}
    out = {"steps": [{} for _ in range(10)]}
    problems = gates.schema_errors(Draft202012Validator(schema), out)
    assert len(problems) == 40 and gates.MAX_REPORTED >= 40
