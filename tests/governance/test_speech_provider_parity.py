"""The speech-provider vocabulary and its adapters must agree, in BOTH directions.

`lab.platform.contracts.SPEECH_PROVIDERS` is what an outside caller may name as a lane;
`lab.substrate.container.SPEECH_PROVIDERS` is what this lab can actually build. Drift either way is
a defect with a different failure mode, and neither is caught by any other test:

  * a NAME with no adapter is a run that passes validation and then dies in the workload — the
    expensive kind of failure, after a recording has been fetched;
  * an ADAPTER with no name is a provider nobody can ask for — work that exists and cannot be run.

This is the same argument as `test_contracts_match_servers`: where a catalogue and its
implementation must agree, exactness IS the contract, and a two-way check is the point.
"""
from lab.platform import contracts
from lab.substrate import container


def test_every_named_provider_has_an_adapter_and_every_adapter_has_a_name():
    assert set(contracts.SPEECH_PROVIDERS) == set(container.SPEECH_PROVIDERS)


def test_every_adapter_module_is_importable_and_offers_the_one_factory():
    """A registry line pointing at a module that cannot be imported, or that has no `build`, fails
    at the first submit of that lane — offline, here, is where it should fail instead."""
    import importlib
    for name, module in container.SPEECH_PROVIDERS.items():
        assert callable(getattr(importlib.import_module(module), "build", None)), \
            f"{name} -> {module} has no build()"


def test_the_lane_field_of_every_process_offers_exactly_the_known_providers():
    """A process that offered a subset would refuse a lane this lab can serve; a superset would
    accept one it cannot."""
    for spec in contracts.PROCESSES.values():
        for field in spec.inputs:
            if field.name == "provider":
                assert set(field.choices) == set(container.SPEECH_PROVIDERS)
