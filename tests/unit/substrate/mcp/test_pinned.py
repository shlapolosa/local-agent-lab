"""`pinned.rules` — the one policy every governed derivation and view reads the corpus under."""
import pytest
from fastmcp.exceptions import ToolError

from fixtures.reference import FakeReferenceLibrary, SeededArtifact
from lab.core.reference.model import ArtifactKind
from lab.substrate.mcp import pinned

A = SeededArtifact("a", ArtifactKind.RECORD, record_type="t", records=[{"record_id": "r", "x": "1"}])
TABLE = {"a": ("a", "t"), "b": ("b", "t")}


def test_an_OPTIONAL_artifact_the_pin_lacks_is_absent_not_empty():
    library = FakeReferenceLibrary([A])
    rows, _ = pinned.rules(library, library.pin().pin_id, "run", "p", "f", table=TABLE,
                           needs=["a", "b"], reads=["a"], optional=["b"])
    assert rows["a"] and "b" not in rows


def test_a_REQUIRED_artifact_the_pin_lacks_still_refuses():
    library = FakeReferenceLibrary([A])
    with pytest.raises(ToolError, match="'b'"):
        pinned.rules(library, library.pin().pin_id, "run", "p", "f", table=TABLE,
                     needs=["a", "b"], reads=["a"])


def test_a_keyed_read_that_reaches_the_limit_refuses_rather_than_answering_from_part():
    big = SeededArtifact("a", ArtifactKind.RECORD, record_type="t", retrieval="key",
                         records=[{"record_id": f"r{i}", "x": str(i)} for i in range(pinned.LIMIT)])
    library = FakeReferenceLibrary([big])
    with pytest.raises(ToolError, match="more than"):
        pinned.rules(library, library.pin().pin_id, "run", "p", "f", table=TABLE, needs=["a"],
                     reads=["a"])


def test_a_whole_artifact_of_any_size_is_read_in_full():
    big = SeededArtifact("a", ArtifactKind.RECORD, record_type="t", retrieval="whole",
                         records=[{"record_id": f"r{i}", "x": str(i)} for i in range(pinned.LIMIT + 5)])
    library = FakeReferenceLibrary([big])
    rows, _ = pinned.rules(library, library.pin().pin_id, "run", "p", "f", table=TABLE, needs=["a"],
                           reads=["a"])
    assert len(rows["a"]) == pinned.LIMIT + 5
