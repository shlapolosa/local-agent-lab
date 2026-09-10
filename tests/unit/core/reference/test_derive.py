"""Turning a governed artifact's master into its agent-readable form.

The two forms are the SAME artifact at the same version (DR-02), so the derivation has to be
deterministic: re-running it on unchanged content must produce byte-identical output and identical
ids, or a re-publish invents a new version and every prior citation stops resolving.

Chunking is structural first and packed second. A citation has to point at something a person can
find in the master, so the anchor is the heading path — never a byte offset, which survives no edit
at all.
"""
import pytest

from lab.core.reference.derive import (
    DerivationError,
    chunk,
    content_digest,
    passages,
    records,
)

DOC = """# Tradeoff catalogue

Some opening prose that belongs to the top heading.

## G23 versus at-least-once delivery

Idempotency key plus a compensating action. Where the effect is irreversible the
obligation resolves to a pre-commit confirmation instead.

## G18 versus an open-ended interpretive step

Human sampling at a declared rate plus an outcome assertion.
"""


# ---------------------------------------------------------------- chunking

def test_a_passage_is_anchored_on_its_heading_path_not_a_byte_offset():
    out = chunk(DOC)
    assert all(p.heading_path for p in out)
    assert any("G23" in " > ".join(p.heading_path) for p in out)


def test_no_passage_crosses_a_heading():
    """Packing two sections together would give a citation an anchor that does not contain half
    its own text."""
    out = chunk(DOC)
    for passage in out:
        assert "## " not in passage.text


def test_the_heading_path_accumulates_down_the_levels():
    out = chunk(DOC)
    deep = [p for p in out if "G23" in " > ".join(p.heading_path)][0]
    assert deep.heading_path[0].startswith("Tradeoff")


def test_chunking_is_deterministic():
    assert [p.text for p in chunk(DOC)] == [p.text for p in chunk(DOC)]


def test_a_long_section_is_packed_into_several_passages_with_overlap():
    body = "# Head\n\n" + "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(20))
    out = chunk(body, target_tokens=100, overlap=0.15)
    assert len(out) > 1
    assert all(p.heading_path == ("Head",) for p in out)
    # consecutive passages share some tail/head text
    assert any(set(a.text.split()) & set(b.text.split()) for a, b in zip(out, out[1:]))


def test_a_document_with_no_heading_still_yields_a_passage():
    out = chunk("Just some prose with no heading at all.")
    assert len(out) == 1
    assert out[0].heading_path == ()


def test_an_empty_document_refuses_rather_than_indexing_nothing():
    """An artifact that produced no passages would pass a `passages > 0` gate the moment somebody
    relaxed it. Refuse at derivation instead."""
    with pytest.raises(DerivationError):
        chunk("   \n\n  ")


# ---------------------------------------------------------------- passage ids

def test_a_passage_id_is_stable_across_runs():
    first = passages("tradeoff-catalogue", DOC)
    second = passages("tradeoff-catalogue", DOC)
    assert [p.passage_id for p in first] == [p.passage_id for p in second]


def test_a_passage_id_is_scoped_to_its_artifact():
    a = passages("tradeoff-catalogue", DOC)
    b = passages("quality-attributes", DOC)
    assert {p.passage_id for p in a}.isdisjoint({p.passage_id for p in b})


def test_editing_one_section_does_not_renumber_the_others():
    """The property that makes a re-publish cheap: only what changed gets a new id, so citations
    into untouched sections keep resolving."""
    before = {p.passage_id for p in passages("cat", DOC)}
    after = {p.passage_id for p in passages("cat", DOC + "\n## A new section\n\nMore text.\n")}
    assert before <= after


# ---------------------------------------------------------------- records

ROWS = [{"risk_class": "E2", "mandatory": "G09, G17"},
        {"risk_class": "E3", "mandatory": "G09, G16"}]


def test_a_record_id_is_derived_from_its_natural_key():
    out = records("guardrail-mapping", ROWS, key_fields=("risk_class",))
    assert len({r.record_id for r in out}) == 2


def test_a_record_id_survives_a_change_to_a_non_key_field():
    """A re-publish that corrected a typo in the body must not orphan every citation to the row."""
    before = records("guardrail-mapping", ROWS, key_fields=("risk_class",))
    edited = [ROWS[0] | {"mandatory": "G09, G17, G23"}, ROWS[1]]
    after = records("guardrail-mapping", edited, key_fields=("risk_class",))
    assert before[0].record_id == after[0].record_id


def test_a_record_keeps_its_body_verbatim():
    out = records("guardrail-mapping", ROWS, key_fields=("risk_class",))
    assert out[0].body == ROWS[0]


def test_a_row_missing_the_key_field_refuses():
    with pytest.raises(DerivationError) as e:
        records("guardrail-mapping", [{"mandatory": "G09"}], key_fields=("risk_class",))
    assert "risk_class" in str(e.value)


def test_two_rows_with_the_same_key_refuse_rather_than_one_shadowing_the_other():
    """An exact lookup that silently returned one of two rows would be worse than a failed one."""
    with pytest.raises(DerivationError):
        records("m", [ROWS[0], ROWS[0]], key_fields=("risk_class",))


# ---------------------------------------------------------------- the content digest

def test_the_digest_covers_the_content_not_the_ordering_of_a_dict():
    a = content_digest([{"b": 2, "a": 1}])
    b = content_digest([{"a": 1, "b": 2}])
    assert a == b


def test_the_digest_changes_when_any_content_changes():
    assert content_digest([{"a": 1}]) != content_digest([{"a": 2}])


def test_the_digest_is_order_sensitive_across_entries():
    """Two artifacts holding the same rows in a different order are not the same artifact — a
    price sheet's line order is part of what was signed."""
    assert content_digest([{"a": 1}, {"b": 2}]) != content_digest([{"b": 2}, {"a": 1}])


# ---------------------------------------------------------------- passages FROM records

def _map_records():
    from lab.core.reference.derive import records
    return records("capability-map", [
        {"id": "L1", "parent": "-", "level": "1", "label": "Care Delivery",
         "path": "Care Delivery", "definition": "Delivering care to patients"},
        {"id": "L2", "parent": "L1", "level": "2", "label": "Triage",
         "path": "Care Delivery > Triage", "definition": "Sorting patients by urgency"},
    ], key_fields=["id", "parent", "level"])


def test_a_record_artifact_derives_one_passage_per_record():
    """A vector-mode record artifact is searchable AND exact: every row becomes exactly one
    passage that names the record it came from, so a semantic hit resolves to a real row."""
    from lab.core.reference.derive import record_passages
    out = record_passages("capability-map", _map_records(), text_fields=["path", "definition"])
    assert [p.record_id for p in out] == [r.record_id for r in _map_records()]
    assert out[1].text == "Care Delivery > Triage. Sorting patients by urgency"
    assert [p.ordinal for p in out] == [0, 1]


def test_a_record_passage_is_anchored_on_its_key_and_identified_by_its_record():
    """The id follows the RECORD, not the text: a corrected definition keeps the passage's id, so a
    citation into it keeps resolving across a re-publish — the same rule records themselves keep."""
    from lab.core.reference.derive import record_passages
    first = record_passages("capability-map", _map_records(), text_fields=["path", "definition"])
    edited = record_passages("capability-map", [
        r for r in _map_records()], text_fields=["path"])
    assert [p.passage_id for p in first] == [p.passage_id for p in edited]
    assert first[0].anchor == "id=L1 · parent=- · level=1"
    assert first[0].passage_id != record_passages("other-map", _map_records(),
                                                  text_fields=["path"])[0].passage_id


def test_record_passages_default_to_every_non_empty_field_in_order():
    from lab.core.reference.derive import record_passages
    out = record_passages("capability-map", _map_records())
    assert out[0].text.startswith("L1. -. 1. Care Delivery. Care Delivery. Delivering")


def test_a_record_that_renders_no_text_refuses_rather_than_indexing_an_empty_passage():
    from lab.core.reference.derive import DerivationError, record_passages, records
    blank = records("m", [{"id": "x", "definition": ""}], key_fields=["id"])
    with pytest.raises(DerivationError) as e:
        record_passages("m", blank, text_fields=["definition"])
    assert "no text" in str(e.value)
