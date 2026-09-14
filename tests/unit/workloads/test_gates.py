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


class _Agent:
    def __init__(self, *replies):
        self.replies, self.asked = list(replies), []

    async def run(self, message):
        self.asked.append(message)
        return self.replies[min(len(self.asked) - 1, len(self.replies) - 1)]


def _run(agent, **kw):
    import asyncio
    from jsonschema import Draft202012Validator
    from lab.workloads import gates
    validator = Draft202012Validator({"type": "object", "required": ["selected"]})
    return asyncio.run(gates.run_gated(agent, "pick", step="21", validator=validator, **kw))


def test_a_soft_shortfall_is_asked_for_once_then_recorded_on_the_answer_rather_than_raised():
    """A required family nobody selected is something the design still OWES — a reviewer must see
    it, and the run must not lose its work over it."""
    agent = _Agent('{"selected": ["a"]}', '{"selected": ["a"], "unresolved": ["F9"]}')
    out = _run(agent, soft=lambda o: [f"family F{n} is owed" for n in (3, 4)], soft_remedy="pick one")
    assert "family F3 is owed — pick one" in agent.asked[1], "the retry hears the finding WITH the remedy"
    assert out["unresolved"] == ["F9", "family F3 is owed", "family F4 is owed"], "the record carries the finding alone"


def test_a_soft_rule_never_reasons_about_an_answer_the_hard_gate_refused():
    seen = []
    agent = _Agent('{"nope": 1}', '{"selected": ["a"]}')
    out = _run(agent, soft=lambda o: seen.append(o) or [])
    assert seen == [{"selected": ["a"]}], "run over the accepted answer only"
    assert out == {"selected": ["a"]}


def test_a_hard_failure_still_raises_after_the_one_retry():
    import pytest
    from lab.workloads import gates
    with pytest.raises(gates.GateFailed):
        _run(_Agent('{"nope": 1}', '{"nope": 2}'), soft=lambda o: [])
