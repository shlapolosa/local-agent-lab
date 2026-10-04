"""The contract is one KERNEL plus one module per feature slice — and callers never see the seam.

A feature edits its own slice (`lab.platform.contracts.<feature>`) instead of the 2000-line shared
module every session used to collide in. A slice DECLARES what it contributes — `PROCESSES`, `AGENTS`,
`CATALOGUES` — and the kernel's registries are assembled from those tuples, so adding a process, an
agent or a catalogue to a slice is an edit to the slice alone. What must stay TRUE for that to be safe:
- a slice's declarations are complete (nothing defined in it is left out of its own tuples);
- the kernel's registries contain every slice member, as the SAME object;
- a name the kernel re-exports (kept for the callers that predate the split) IS the slice's object.
New names are imported from the slice itself, so they are not required in the kernel's `__all__`.
"""
import importlib
import pkgutil

from lab.platform import contracts

SLICES = [importlib.import_module(f"{contracts.__name__}.{m.name}")
          for m in pkgutil.iter_modules(contracts.__path__)]


def _defined(s, kind):
    return [v for v in vars(s).values() if isinstance(v, kind)]


def test_the_speech_slice_exists():
    assert any(s.__name__.endswith(".speech") for s in SLICES)


def test_a_slice_declares_everything_it_defines():
    for s in SLICES:
        assert set(map(id, _defined(s, contracts.ProcessSpec))) <= set(map(id, s.PROCESSES)), s.__name__
        catalogues = [v for v in vars(s).values() if isinstance(v, type) and issubclass(v, contracts.ToolCatalogue)
                      and v is not contracts.ToolCatalogue and v.__module__ == s.__name__]
        assert set(catalogues) <= set(s.CATALOGUES), s.__name__


def test_the_kernel_registries_contain_every_slice_member():
    for s in SLICES:
        for p in s.PROCESSES:
            assert contracts.PROCESSES[p.name] is p, (s.__name__, p.name)
            assert (p.name in contracts.PRODUCING_PROCESSES) == bool(p.products), (s.__name__, p.name)
        for a in s.AGENTS:
            assert a in contracts.AGENTS, (s.__name__, a.name)
        for c in s.CATALOGUES:
            assert contracts.SERVERS[c.SERVER] is c, (s.__name__, c.SERVER)


def test_no_slice_code_reads_a_registry_name_its_own_tuple_shadows():
    """Inside a slice, `PROCESSES` is the slice's OWN tuple — so code meaning the kernel's registry (every
    process) must say `_kernel.PROCESSES`. Learned when the fabric split made `ArtifactChanged` refuse
    `produced_by="transcript_to_minutes"`: the check silently narrowed from nine processes to two, and no
    import-time check could see it, because the name was defined — just not the one the code meant."""
    import ast, inspect
    shadowed = {"PROCESSES", "AGENTS", "CATALOGUES", "SERVERS", "ALL_TOOLS"}
    for s in SLICES:
        for fn in (n for n in ast.walk(ast.parse(inspect.getsource(s)))
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            reads = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id in shadowed}
            assert not reads, (s.__name__, fn.name, reads)


def test_an_event_may_name_any_registered_process():
    """The behavioural half of the guard above: every producer the kernel registers is accepted."""
    from lab.core import ids
    pointer = {"source": "collab", "handle": "collab://item/drive-1/01ABC", "version": "4.0"}
    for name in contracts.PRODUCING_PROCESSES:
        ev = contracts.ArtifactChanged(event_id=ids.ulid(), pointer=pointer, source_kind="collab", change="updated",
                                       actor_oid="3f2a", occurred_at="2026-09-11T08:10:31Z", produced_by=name)
        assert ev.produced_by == name


def test_a_reexported_name_is_the_slice_object():
    for s in SLICES:
        for name in s.__all__:
            if hasattr(contracts, name) and name not in ("PROCESSES", "AGENTS", "CATALOGUES"):
                assert getattr(contracts, name) is getattr(s, name), (s.__name__, name)
