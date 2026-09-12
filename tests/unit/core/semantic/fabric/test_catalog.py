"""The Catalog port and its in-memory adapter: identity, the closed row, the embedding index beside it."""
import pytest

from lab.core.semantic.fabric.catalog import (Catalog, CatalogEntry, MemoryCatalog, POINTER_ID_FIELDS,
                                              STATES, STATE_IRI, cosine, pointer_key)

P = {"source": "collab", "handle": "collab://site/drive/item1", "version": "3"}


def test_the_memory_adapter_satisfies_the_port():
    assert isinstance(MemoryCatalog(), Catalog)


def test_pointer_key_is_source_and_the_first_id_field():
    assert pointer_key(P) == "collab:collab://site/drive/item1"
    assert pointer_key({"source": "lab", "ref": "art://1/x.md"}) == "lab:art://1/x.md"
    with pytest.raises(ValueError):
        pointer_key({"source": "lab"})
    with pytest.raises(ValueError):
        pointer_key({"ref": "art://1/x.md"})
    assert "ref" in POINTER_ID_FIELDS and "handle" in POINTER_ID_FIELDS


def test_an_entry_enforces_its_own_invariants():
    e = CatalogEntry("urn:fabric:artifact:A", P, title="Minutes")
    assert e.state == "pending" and e.pointer_key == "collab:collab://site/drive/item1"
    assert e.created_at and e.updated_at
    with pytest.raises(ValueError):
        CatalogEntry("", P)
    with pytest.raises(ValueError):
        CatalogEntry("urn:x", {"source": "collab"})
    with pytest.raises(ValueError):
        CatalogEntry("urn:x", P, state="draft")
    with pytest.raises(ValueError):
        CatalogEntry("urn:x", P, title="t" * 301)


def test_every_state_has_a_graph_spelling():
    assert set(STATE_IRI) == set(STATES)
    assert all(v.startswith("urn:fabric:ont#") for v in STATE_IRI.values())


def test_with_touches_updated_at_and_nothing_else():
    e = CatalogEntry("urn:x", P, title="a")
    f = e.with_(state="published", baseline_version="2.0")
    assert (f.state, f.baseline_version, f.title, f.created_at) == ("published", "2.0", "a", e.created_at)
    assert f.updated_at >= e.updated_at
    assert "pointer" in e.to_dict() and e.to_dict()["iri"] == "urn:x"


def test_put_is_an_upsert_and_by_pointer_finds_the_row():
    c = MemoryCatalog()
    e = c.put(CatalogEntry("urn:x", P, title="a"))
    assert c.get("urn:x") is e and c.by_pointer(e.pointer_key) is e and len(c) == 1
    c.put(e.with_(title="b"))
    assert c.get("urn:x").title == "b" and len(c) == 1
    assert c.get("urn:nope") is None and c.by_pointer("lab:none") is None


def test_embeddings_index_only_known_rows_and_rank_by_cosine():
    c = MemoryCatalog()
    for i in ("a", "b", "c"):
        c.put(CatalogEntry(f"urn:{i}", {"source": "lab", "ref": f"art://{i}"}))
    c.put_embedding("urn:a", [1.0, 0.0], "m")
    c.put_embedding("urn:b", [0.9, 0.1], "m")
    c.put_embedding("urn:c", [0.0, 1.0], "m")
    with pytest.raises(LookupError):
        c.put_embedding("urn:zzz", [1.0, 0.0], "m")
    assert c.embedding("urn:a") == ([1.0, 0.0], "m") and c.embedding("urn:zzz") is None
    ranked = c.similar([1.0, 0.0], limit=2)
    assert [r for r, _ in ranked] == ["urn:a", "urn:b"] and ranked[0][1] == pytest.approx(1.0)
    assert [r for r, _ in c.similar([1.0, 0.0], limit=5, exclude="urn:a")] == ["urn:b", "urn:c"]
    assert c.similar([1.0, 0.0], limit=0) == []
    c.put_embedding("urn:c", [1.0, 0.0], "other-model")
    assert [r for r, _ in c.similar([1.0, 0.0], limit=5, model="m")] == ["urn:a", "urn:b"]


def test_cosine_is_defined_on_zero_vectors_and_refuses_a_mismatch():
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0
    with pytest.raises(ValueError):
        cosine([1.0], [1.0, 0.0])


def test_describe_is_title_type_and_subjects_and_never_a_body():
    from lab.core.semantic.fabric.catalog import describe, subject_labels
    links = [{"predicate": "subject", "rung": "X", "object": "urn:c#Care"},
             {"predicate": "documentType", "rung": "H", "object": "urn:fabric:scheme:doc-types#minutes"},
             {"predicate": "subject", "rung": "S", "object": "http://x/concept/Claims"},
             {"predicate": "subject", "rung": "X", "object": "urn:c#a3f9e1", "label": "Claims Intake"}]
    assert subject_labels(links) == ["Care", "Claims", "Claims Intake"]
    assert describe("ADR-14", "urn:fabric:scheme:doc-types#decision-record", ["Care"]) == "ADR-14 · decision-record · Care"
    assert describe("", "", []) == "" and describe("Notes", "", ["", "A"]) == "Notes · A"


def test_unindexed_lists_rows_without_a_vector_in_this_space_and_skips_the_withdrawn():
    c = MemoryCatalog()
    a = c.put(CatalogEntry("urn:fabric:artifact:A", P, title="a"))
    b = c.put(CatalogEntry("urn:fabric:artifact:B", {"source": "lab", "ref": "art://1/b"}, title="b"))
    w = c.put(CatalogEntry("urn:fabric:artifact:W", {"source": "lab", "ref": "art://1/w"}, title="w", state="withdrawn"))
    c.put_embedding(a.iri, [1.0, 0.0], "old-model")
    c.put_embedding(b.iri, [1.0, 0.0], "new-model")
    assert [e.iri for e in c.unindexed("new-model")] == [a.iri]          # another space counts as missing
    assert [e.iri for e in c.unindexed("old-model")] == [b.iri]
    assert w.iri not in {e.iri for e in c.unindexed("nothing")}


def test_a_scheme_id_with_characters_an_iri_cannot_carry_is_percent_encoded():
    """Measured 12 Sep 2026: a minutes ref with SPACES in its name went into graph C verbatim; rdflib refused
    to serialise it and every persist failed from then on. A name with spaces is legitimate input."""
    from lab.core.semantic.fabric.catalog import custody_iri
    ref = "art://89df6f4cd2a6/meeting-2 test-20260912.mp4.minutes.json"
    iri = custody_iri({"source": "lab", "ref": ref})
    assert iri == "art://89df6f4cd2a6/meeting-2%20test-20260912.mp4.minutes.json"
    assert custody_iri({"source": "lab", "ref": 'art://x/a<b>"c{d}|e\\f^g`h'}) == "art://x/a%3Cb%3E%22c%7Bd%7D%7Ce%5Cf%5Eg%60h"
    assert custody_iri({"source": "collab", "handle": "collab://item/d/i%20x?v=1#f"}) == "collab://item/d/i%20x?v=1#f"
