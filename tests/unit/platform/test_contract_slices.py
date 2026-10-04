"""The contract is one KERNEL plus one module per feature slice — and callers never see the seam.

A feature edits its own slice (`lab.platform.contracts.<feature>`) instead of the 2000-line shared
module every session used to collide in. What must stay TRUE for that to be safe: every name a
slice declares is reachable from `lab.platform.contracts` as the SAME object, and every registry
the kernel assembles (PROCESSES, AGENTS, SERVERS) contains the slice's members.
"""
import importlib
import pkgutil

from lab.platform import contracts

SLICES = [importlib.import_module(f"{contracts.__name__}.{m.name}")
          for m in pkgutil.iter_modules(contracts.__path__)]


def test_the_speech_slice_exists():
    assert any(s.__name__.endswith(".speech") for s in SLICES)


def test_a_slice_is_reexported_as_the_same_objects():
    for s in SLICES:
        for name in s.__all__:
            if name == "AGENTS":
                continue                    # a slice's agents are MEMBERS of the kernel's AGENTS, below
            assert getattr(contracts, name) is getattr(s, name), (s.__name__, name)
            assert name in contracts.__all__, (s.__name__, name)


def test_the_kernel_registries_contain_every_slice():
    for s in SLICES:
        for a in getattr(s, "AGENTS", ()):
            assert a in contracts.AGENTS, (s.__name__, a.name)
        for v in vars(s).values():
            if isinstance(v, contracts.ProcessSpec):
                assert contracts.PROCESSES[v.name] is v, (s.__name__, v.name)
            if isinstance(v, type) and issubclass(v, contracts.ToolCatalogue) and v is not contracts.ToolCatalogue:
                assert contracts.SERVERS[v.SERVER] is v, (s.__name__, v.SERVER)
