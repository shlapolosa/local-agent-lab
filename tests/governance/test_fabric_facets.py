"""A facet is declared in FOUR places, and no two of them can see each other.

`FACETS` says which predicate carries it, `fab.ttl` declares the property so `semantic_ontologies` can
explain it, `fab-shapes.ttl` admits it into the CLOSED node shape, and the catalogue's row holds the column.
Adding the fifth facet touched all four and nothing would have failed if one had been missed — the shape
refuses the write (loud), but an undeclared property and a missing dataclass field are both silent.

These are parity tests, so EXACTNESS is the contract: the same reason `test_contracts_match_servers` asserts
both directions rather than membership.
"""
from dataclasses import fields
from pathlib import Path

from lab.core.semantic.fabric import catalog, service
from lab.core.semantic.fabric.catalog import CatalogEntry
from lab.substrate.mcp.semantic import catalog_pg

TTL = Path(service.__file__).parent


def _declared(text: str) -> set[str]:
    return {line.split()[0].split(":", 1)[1] for line in text.splitlines()
            if line.startswith("fab:") and "owl:" in line}


def test_every_FACET_predicate_is_declared_in_the_ONTOLOGY():
    """Otherwise `semantic_ontologies` and `describe` cannot explain a predicate `catalog_get` reports."""
    declared = _declared((TTL / "fab.ttl").read_text())
    for field_name, (predicate, _) in service.FACETS.items():
        local = str(predicate).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        if str(predicate).startswith("urn:fabric:ont#"):
            assert local in declared, f"{field_name} asserts fab:{local}, which fab.ttl does not declare"


def test_every_FACET_is_admitted_by_the_CLOSED_shape():
    """A closed shape refuses an undeclared predicate, so a facet missing here fails every write that uses
    it — loudly, but only once a run reaches that line in production."""
    shapes = (TTL / "fab-shapes.ttl").read_text()
    for field_name, (predicate, _) in service.FACETS.items():
        short = str(predicate).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        assert short in shapes, f"{field_name} ({short}) is not admitted by fab-shapes.ttl"


def test_the_FACET_NAMES_and_the_ROW_agree_in_both_directions():
    row = {f.name for f in fields(CatalogEntry)}
    assert set(catalog.FIELDS) <= row, f"a facet with no column: {set(catalog.FIELDS) - row}"
    assert set(catalog.FIELDS) == set(service.FACETS), "FIELDS and FACETS are one list spelled twice"


def test_every_POSTGRES_COLUMN_names_a_field_the_ROW_actually_has():
    """`put()` reads each column off the entry by NAME with no default, so a column without its field raises
    on the first write. This says so before a deploy does."""
    row = {f.name for f in fields(CatalogEntry)} | {"pointer_key"}
    assert set(catalog_pg._COLUMNS) <= row, f"columns with no field: {set(catalog_pg._COLUMNS) - row}"
