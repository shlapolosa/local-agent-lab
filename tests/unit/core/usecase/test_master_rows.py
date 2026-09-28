"""One home for "a committed master, as rows" — four copies of the same two lines grew in one day
(review F12, 28 Sep 2026)."""
import pytest

from lab.core.usecase import seed


def test_a_committed_master_reads_as_rows_keyed_by_its_headers():
    rows = seed.master_rows("guardrails")
    assert len(rows) > 20 and {"id", "pred", "cap"} <= set(rows[0])


def test_a_master_that_is_not_committed_raises_rather_than_reading_as_empty():
    with pytest.raises(FileNotFoundError, match="ontology_concepts"):
        seed.master_rows("ontology_concepts")          # PRIVATE: never in this repository
