"""The cell codec — `encode` and `decode` are inverses, and every list column is declared.

The declaration matters because the format is lossy: a one-element list and a scalar render to
the same cell, so which it is cannot be recovered by looking. A list column nobody declared comes
back as a string, and the first consumer to iterate it gets characters.
"""
import json
from pathlib import Path

import pytest

from lab.core.reference import cells

SEED = Path(__file__).resolve().parents[4] / "src" / "lab" / "core" / "usecase" / "seed"


@pytest.mark.parametrize("column", sorted(cells.LIST_COLUMNS))
def test_a_declared_list_column_round_trips_including_one_element(column):
    for value in (["G07"], ["S13", "S5"], []):
        assert cells.decode(cells.encode(value), column) == value


def test_a_nested_object_round_trips_and_prose_with_a_semicolon_is_left_alone():
    assert cells.decode(cells.encode({"name": "federated", "n": 2}), "variant") == {"name": "federated", "n": 2}
    prose = "admitted via the map only; projects cannot introduce components"
    assert cells.decode(prose, "rule") == prose


def test_every_column_that_is_ever_a_list_in_the_seed_is_declared():
    """Found `sources`, `src` and `fail` three behind by hand. A list column left undeclared is a
    row that decodes wrong under a pin and nowhere else."""
    seen: dict[str, str] = {}
    for path in sorted(SEED.glob("*.json")):
        payload = json.loads(path.read_text())
        for key, value in payload.items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                for row in value:
                    for column, cell in row.items():
                        if isinstance(cell, list):
                            seen[column] = path.stem
    undeclared = {c: f for c, f in seen.items() if c not in cells.LIST_COLUMNS}
    assert not undeclared, f"list-valued seed columns not in LIST_COLUMNS: {undeclared}"


class _Record:
    def __init__(self, body): self.body = body


def test_rows_decodes_every_cell_drops_the_bookkeeping_id_and_empty_cells():
    rows = cells.rows([_Record({"record_id": "rec-1", "family": "F1", "topology": "T1; T2",
                                "variant": '{"name": "federated"}', "note": "", "spare": None})])
    assert rows == [{"family": "F1", "topology": ["T1", "T2"], "variant": {"name": "federated"}}]
