"""Asking a model the same question twice should get the same answer — where the model allows it.

Measured against the live gateway 20 Sep 2026, same prompt twice:

    gpt-5.4-mini-think  temperature=0            -> two DIFFERENT answers
    gpt-5.4-mini        temperature=0 + seed     -> byte-identical
    gpt-4.1             temperature=0 + seed     -> byte-identical

So the run-to-run spread in step 5 is the REASONING model, not a missing setting: thinking models
ignore temperature. Setting it is still right — it costs nothing and it is what makes a
non-reasoning model exactly reproducible — but it is not on its own a fix, and saying so was wrong.
"""
from lab.platform import config
from lab.workloads.usecase import agents as A
from lab.workloads.usecase.steps import STEPS

STEP = next(s for s in STEPS if s.key == "coverage_map")


def _options(**kw):
    agent = A.make_agent(STEP, credential="sk-x", gateway_url="http://gw", model="m", **kw)
    return dict(agent.default_options or {})


def test_a_deterministic_ask_is_the_DEFAULT_not_something_to_remember():
    """Nothing set temperature anywhere in this codebase, so every agent ran at the provider's
    default. A setting that has to be remembered per call site is one that will be missed."""
    assert _options()["temperature"] == 0


def test_a_seed_travels_too_even_though_it_does_not_buy_determinism_here():
    """The seed is sent because asking the same way every time is free and is a precondition for
    anything else — NOT because it makes step 5 reproducible. Measured on step 5's real payload
    (74 candidates with definitions, ~22 KB): `gpt-5.4-mini` and `gpt-5.4-mini-think` at
    temperature=0 with this seed each returned three DISTINCT answers out of three. An earlier
    spike on a one-sentence prompt returned byte-identical answers and was written up as
    reproducibility; it measured the prompt it was given."""
    assert _options()["seed"] == config.AGENT_SEED


def test_a_step_can_ask_for_something_else_without_editing_this_function():
    """One step wanting a warmer setting must not mean a second `make_agent`."""
    assert _options(temperature=0.7)["temperature"] == 0.7


def test_the_existing_options_are_untouched():
    opts = _options(store=True, max_tokens=123)
    assert opts["store"] is True and opts["max_tokens"] == 123
