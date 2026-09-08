"""The Power Automate flow template must ask about EVERY lane, not just the first.

A committed client template is a contract like any other, and this one drifted the moment
`SPEECH_LANES` made a single submit create several runs: the flow polled `request_id` — the first
lane — and the other lanes' questions were never asked. Worse, when that first lane failed the flow
terminated, so no question was asked at all even though a later lane had a good transcript. Measured
live 8 Sep 2026 on the 19:13 recording: munsit failed on a provider 500, elevenlabs failed, and the
assemblyai lane finished with a perfectly answerable question that nobody was ever shown.

None of this can be unit-tested against Power Automate, so what is asserted here is what a reader
cannot check by eye in 700 lines of JSON: that the loop exists, that it iterates the right thing,
that nothing inside it still points at the submit's own request_id, and the three properties that
are silently wrong rather than loudly broken.
"""
import json
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[5] / "config/clients/power-automate/flow.template.json"


def _flow() -> dict:
    return json.loads(TEMPLATE.read_text())


def _walk(node):
    """Every action object in the tree, however deeply nested in If/Foreach branches."""
    if isinstance(node, dict):
        for key in ("actions", "else"):
            for name, action in (node.get(key) or {}).items() if key == "actions" else ():
                yield name, action
                yield from _walk(action)
        if isinstance(node.get("else"), dict):
            yield from _walk(node["else"])
        for name, action in (node.get("actions") or {}).items():
            yield from _walk(action)


def _all_actions() -> dict:
    flow = _flow()
    found = dict(flow["actions"])
    for name, action in list(flow["actions"].items()):
        for n, a in _walk(action):
            found[n] = a
    return found


def test_the_flow_loops_over_every_lane_the_submit_returned():
    loop = _flow()["actions"]["For_each_lane"]
    assert loop["type"] == "Foreach"
    assert "lanes" in loop["foreach"], "it must iterate the submit's `lanes`, not a single run"


def test_the_loop_is_sequential_because_it_sets_a_variable():
    """Power Automate REFUSES SetVariable inside a concurrent Apply-to-each, and `runState` is set
    on every pass. A template that omits this imports and then fails at run time."""
    loop = _flow()["actions"]["For_each_lane"]
    assert loop["runtimeConfiguration"]["concurrency"]["repetitions"] == 1


def test_each_lane_polls_its_own_run_and_none_polls_the_submits_first_one():
    """The single edit that makes the loop mean anything. Left as `body('Start_run')` every lane
    would poll the FIRST run and ask the same question three times."""
    blob = json.dumps(_flow())
    assert "items('For_each_lane')?['request_id']" in blob
    assert "body('Start_run')?['request_id']" not in blob


def test_the_run_state_is_reset_before_each_lane_is_polled():
    """Without this the Until's condition is already satisfied by the PREVIOUS lane's `done`, so the
    loop exits before the new run has started and asks the last lane's question again — a wrong
    answer that looks entirely normal."""
    actions = _all_actions()
    assert "Reset_run_state" in actions
    poll = actions["Poll_until_the_question_exists"]
    assert "Reset_run_state" in (poll.get("runAfter") or {}), "the reset must precede the poll"


def _types_under(node, wanted, found=None):
    """Every action of type `wanted` anywhere beneath `node`, however deeply nested.

    Matched on the action's TYPE, not on the word appearing somewhere in the JSON — a comment
    explaining why a Terminate was removed would otherwise fail this test, which it did.
    """
    found = [] if found is None else found
    if isinstance(node, list):
        for item in node:
            _types_under(item, wanted, found)
    elif isinstance(node, dict):
        for name, action in node.items():
            if isinstance(action, dict) and action.get("type") == wanted:
                found.append(name)
            if isinstance(action, (dict, list)):
                _types_under(action, wanted, found)
    return found


def test_a_failing_lane_does_not_terminate_the_other_lanes():
    """The bug this whole change exists for: a Terminate inside the loop aborts the flow and takes
    the healthy lanes with it — including the two paths that were correct when the flow handled one
    run, an ambiguous answer and a refused decision."""
    loop = _flow()["actions"]["For_each_lane"]
    assert _types_under(loop, "Terminate") == [], "a lane must record its failure, not end the flow"
    assert "Note_the_lane_problem" in json.dumps(loop)
    # ...and every one of those paths still SAYS something, rather than failing silently
    assert len(_types_under(loop, "AppendToArrayVariable")) >= 3


def test_the_flow_still_fails_loudly_when_no_lane_produced_a_question():
    """Collecting failures must not become swallowing them: if every lane failed, the flow failed."""
    report = _flow()["actions"]["Report_lane_problems"]
    assert report["runAfter"] == {"For_each_lane": ["Succeeded"]}
    assert "Terminate" in json.dumps(report)


def test_the_card_names_the_lane_it_belongs_to():
    """Three cards for one meeting are otherwise indistinguishable, and answering the wrong one
    attributes speakers to a different provider's transcript."""
    card = json.dumps(_all_actions()["Compose_card"])
    assert "items('For_each_lane')?['provider']" in card


def test_a_lane_that_never_started_is_skipped_rather_than_polled():
    """`submit_lanes` returns a row with an empty request_id and an `error` for a lane it could not
    submit. Polling that would spend the whole 90-minute window on a run that does not exist."""
    guard = _flow()["actions"]["For_each_lane"]["actions"]["Skip_lanes_that_never_started"]
    assert guard["type"] == "If" and "request_id" in json.dumps(guard["expression"])
