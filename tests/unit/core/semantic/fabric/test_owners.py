"""The owner map — FR-2.2.2: an owner is LOOKED UP (site/library/folder → owner; a lab product → the run's
requester), never model-guessed; the item's author is the last resort a person can still correct."""
import json

import pytest

from lab.core.semantic.fabric.owners import OwnerMap

MAP = {"collab": {"drive-1": "lib@x", "drive-1/EA/decisions": "ea@x"},
       "lab": {"use_case_screening": "requester", "visio_to_archimate": "arch@x"}}


def test_longest_folder_prefix_wins_then_the_drive_then_the_author_then_nobody():
    m = OwnerMap.from_dict(MAP)
    doc = {"source": "collab", "handle": "collab://item/drive-1/i1"}
    assert m.resolve(doc, path="EA/decisions/2026") == ("ea@x", "owner-map")
    assert m.resolve(doc, path="Finance") == ("lib@x", "owner-map")
    assert m.resolve({"source": "collab", "handle": "collab://item/drive-2/i9"}, author="ann@x") == ("ann@x", "item-author")
    assert m.resolve({"source": "collab", "handle": "collab://item/drive-2/i9"}) == ("", "")


def test_a_lab_product_is_owned_by_the_map_or_by_the_runs_requester():
    m = OwnerMap.from_dict(MAP)
    assert m.resolve({"source": "lab", "ref": "art://1/x"}, produced_by="use_case_screening", requester="sub@x") == ("sub@x", "requester")
    assert m.resolve({"source": "lab", "ref": "art://1/x"}, produced_by="use_case_screening") == ("", "")
    assert m.resolve({"source": "lab", "ref": "art://1/x"}, produced_by="visio_to_archimate", requester="sub@x") == ("arch@x", "owner-map")
    assert m.resolve({"source": "lab", "ref": "art://1/x"}, produced_by="unknown_process", requester="sub@x") == ("", "")


def test_the_map_loads_from_a_file_and_an_absent_file_is_an_empty_map(tmp_path):
    p = tmp_path / "owners.json"; p.write_text(json.dumps(MAP))
    assert OwnerMap.load(str(p)).resolve({"source": "lab", "ref": "art://1/x"}, produced_by="visio_to_archimate") == ("arch@x", "owner-map")
    assert OwnerMap.load(str(tmp_path / "missing.json")) == OwnerMap.empty()
    with pytest.raises(ValueError):
        OwnerMap.from_dict({"collab": {"d": 42}})
