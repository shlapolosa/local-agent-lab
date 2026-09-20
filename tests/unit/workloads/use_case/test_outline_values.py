"""What a watcher is shown is the VALUE, never a summary of it.

Three things measured against step 5's real output shape (20 Sep 2026), each of which reads on the
page as information and is not:

  matched:  13, then "tec-cap-0000 … tec-cap-0011"   — ids, which name nothing to a person
  heat_map: 4,  then "commodity, mature, meets_target, source"  — the KEYS; the answer was the
            values (True, True, False, "map") and none of them was shown
  matched:  truncated at 12 of 13, so the one that mattered might be the one missing
"""
from lab.workloads.usecase import derivation as D


def test_a_dict_of_scalars_shows_its_values_and_not_its_keys():
    """`commodity, mature, meets_target, source` is the QUESTION. The reader opened the row for
    the answer."""
    out = D.outline({"heat_map": {"commodity": True, "mature": True, "meets_target": False,
                                  "source": "the pinned map"}})
    assert out["heat_map"]["items"] == ["commodity: True", "mature: True", "meets_target: False",
                                        "source: the pinned map"]


def test_a_list_entry_is_named_by_what_a_person_reads_not_by_its_key():
    """`capability_id` led `_LABELS`, so every matched capability rendered as `tec-cap-0031`. The
    id is machinery for joining; the label is the thing that was decided."""
    out = D.outline({"matched": [{"function": "validate the form",
                                  "capability_id": "tec-cap-0031",
                                  "capability_label": "Submission Validation"}]})
    assert out["matched"]["items"] == ["Submission Validation"]


def test_an_entry_with_only_an_id_still_says_the_id_rather_than_nothing():
    out = D.outline({"rows": [{"capability_id": "tec-cap-0031"}]})
    assert out["rows"]["items"] == ["tec-cap-0031"]


def test_a_list_of_the_size_these_steps_actually_produce_is_not_truncated():
    """Thirteen matched capabilities against a ceiling of twelve: the page said `truncated` and a
    reader could not tell whether the missing one was the interesting one."""
    out = D.outline({"matched": [{"label": f"Capability {i}"} for i in range(13)]})
    assert out["matched"]["count"] == 13 and len(out["matched"]["items"]) == 13
    assert "truncated" not in out["matched"]


def test_a_truncation_still_happens_somewhere_and_still_says_so():
    """Bounded is not the same as unbounded: this rides every frame to every watcher."""
    out = D.outline({"matched": [{"label": f"Capability {i}"} for i in range(D.MAX_ITEMS + 5)]})
    assert out["matched"]["truncated"] is True
    assert len(out["matched"]["items"]) == D.MAX_ITEMS
