"""A person submitting for the first time must be able to SEE what a submission looks like.

The repo shipped four filled intake CSVs and no example of the thing those drivers describe. So
the only concrete artifact on the Submit page was a field table, and on 23 Sep 2026 one was
uploaded into the `submission` slot — twice — because nothing else looked like an answer to
"attach the use case". The run then read blank driver rows as the narrative.

An example is offered the same way the CSVs are: DISCOVERED from the directory, so adding one is a
file and removing one cannot leave a dead button.
"""
from lab.substrate.review import app as APP


def test_every_scenario_ships_a_prose_submission_beside_its_intake_csv():
    prose = dict(APP.sample_submissions())
    csvs = dict(APP.sample_csvs())
    assert prose, "no example submission ships"
    missing = sorted(set(csvs) - set(prose))
    assert not missing, f"these scenarios have drivers but no use case to go with them: {missing}"


def test_an_example_is_prose_a_person_can_upload_into_the_submission_slot():
    """It has to be a type the picker actually offers, or the example cannot be used."""
    for name, body in APP.sample_submissions():
        assert body.strip(), name
        text = body.decode("utf-8")
        # what step 3 must find: a problem, whose it is, what changes, and ONE named owner
        low = text.lower()
        for wanted in ("problem", "owner"):
            assert wanted in low, f"{name} never mentions {wanted}"
        assert len(text.split()) > 80, f"{name} is too thin to be a worked example"


def test_the_examples_do_not_state_the_problem_as_a_solution():
    """`steps._frame` refuses a problem written as the answer — an example that trips the gate
    teaches the wrong shape."""
    from lab.workloads.usecase.steps import _SOLUTION_WORDS
    for name, body in APP.sample_submissions():
        # The PROBLEM section only: a later section may legitimately discuss what changes.
        text = body.decode("utf-8").lower()
        problem = text.split("## who has it")[0]
        hits = [w for w in _SOLUTION_WORDS if w in problem]
        assert not hits, f"{name} states its problem as a solution: {hits}"
