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


def test_a_match_without_the_optional_label_still_names_the_CAPABILITY_not_the_function():
    """Seen live on run 38545b7f (20 Sep 2026): `matched: 38`, then "prepare design pack" seven
    times and "validate design pack" eight. Those are FUNCTIONS — what each match was made FROM —
    repeated once per capability the function matched to, which is the least useful line the row
    could carry.

    `capability_label` is OPTIONAL in the coverage_map schema (only `function`, `capability_id`
    and `confidence` are required) and the model frequently omits it, so the label chain fell
    through to `function`. The id is the fallback that matters: it names the thing DECIDED, and it
    is distinct per row. The function is last — it answers a question the reader did not ask.
    """
    matched = [{"function": "prepare design pack", "capability_id": "tec-cap-0031",
                "confidence": "lookup"},
               {"function": "prepare design pack", "capability_id": "tec-cap-0042",
                "confidence": "lookup"}]
    assert D.outline({"matched": matched})["matched"]["items"] == ["tec-cap-0031", "tec-cap-0042"]


def test_the_label_still_wins_when_the_model_did_supply_one():
    assert D.outline({"matched": [{"function": "f", "capability_id": "tec-cap-0031",
                                   "capability_label": "Submission Validation"}]}
                     )["matched"]["items"] == ["Submission Validation"]


def test_a_function_is_still_how_an_entry_with_nothing_else_is_named():
    """`functions_without_capability` entries and anything else carrying only a function must not
    become unnamed by demoting the field."""
    assert D.outline({"gaps": [{"function": "reconcile the ledger"}]}
                     )["gaps"]["items"] == ["reconcile the ledger"]


# ---------------------------------------- an entry with no "name" field still shows its VALUES

def test_an_entry_with_no_name_field_renders_its_values_not_its_keys():
    """Seen live on the design run: `selected 15`, then "capability, component_id, component,
    rejected_alternatives" fifteen times. The fallback joined the dict's KEYS — the same column
    headings repeated once per row, which is the least informative thing the row could say.

    Nine array-of-object fields across seven steps land here (checked against every step's schema,
    not against the three that were screenshotted), so the fallback is fixed rather than the label
    list extended for each."""
    out = D.outline({"selected": [{"capability": "Grounding and retrieval",
                                   "component_id": "cmp-a9c03320dd",
                                   "component": "Azure AI Search",
                                   "rejected_alternatives": ["x", "y"]}]})
    item = out["selected"]["items"][0]
    assert "Grounding and retrieval" in item and "Azure AI Search" in item
    assert "component_id" not in item, "that is a heading, not an answer"


def test_the_named_field_still_wins_when_there_is_one():
    out = D.outline({"matched": [{"capability_label": "Submission Validation",
                                  "capability_id": "tec-cap-0031"}]})
    assert out["matched"]["items"] == ["Submission Validation"]


def test_containers_inside_an_entry_are_not_flattened_into_the_label():
    """A row's nested list is its own detail. Splicing it into the one-line label is how a row
    becomes unreadable — `rejected_alternatives` is four more names nobody asked for here."""
    out = D.outline({"rows": [{"conflict": "latency vs assurance",
                               "options": ["a", "b", "c"], "sacrificed": "latency"}]})
    assert out["rows"]["items"] == ["latency vs assurance · latency"]


def test_an_entry_of_only_containers_says_what_it_has_rather_than_nothing():
    out = D.outline({"rows": [{"meanings": ["a", "b"]}]})
    assert out["rows"]["items"][0]


def test_every_schema_declared_list_renders_a_value_for_a_realistic_row():
    """The systematic check: for every array-of-object field any step declares, a row built from
    its own schema must render something that is not a heading."""
    from lab.workloads.usecase import steps as S
    for st in list(S.STEPS) + [S.CAPABILITY_QUERY]:
        for prop, spec in (S.schema(st.key).get("properties") or {}).items():
            if spec.get("type") != "array" or (spec.get("items") or {}).get("type") != "object":
                continue
            fields = list((spec["items"].get("properties") or {}))
            row = {f: f"value-of-{f}" for f in fields}
            label = D.outline({prop: [row]})[prop]["items"][0]
            assert label.startswith("value-of-"), f"step {st.number} {prop}: {label!r}"


def test_a_mapping_whose_values_are_lists_summarises_them():
    """`by_step` on the obligations is `{step: [obligation, ...]}` and rendered as a raw Python
    repr — `n1: [{'guardrail': 'G01', 'text': ...}]`. A reader gets the count and the first one,
    which is what the row is for; the record has the rest."""
    out = D.outline({"by_step": {"n1": [{"guardrail": "G01", "text": "prompt integrity"},
                                        {"guardrail": "G03", "text": "output scanning"}]}})
    item = out["by_step"]["items"][0]
    assert item.startswith("n1: ") and "G01" in item and "2" in item
    assert "{" not in item and "'" not in item, "a Python repr is not a rendering"


def test_an_empty_list_value_says_none_rather_than_an_empty_bracket():
    out = D.outline({"by_step": {"n1": []}})
    assert out["by_step"]["items"] == ["n1: none"]
