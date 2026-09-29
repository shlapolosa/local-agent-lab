"""Staging the vocabulary for publication: the fabric writes the master, an OPERATOR signs and publishes it.

The fabric cannot publish and must not. Publication has no tool surface, the signing seed is deliberately off
every service, and the corpus reader's database role holds SELECT only — so the honest split is that the fabric
renders what it owns and hands an operator a ref and the exact command.
"""
import json

import pytest

from lab.core.reference.master import parse
from lab.core.semantic.fabric.vocabulary import build
from lab.platform.contracts import SemanticTools
from lab.substrate import fabric_publication as P

SCHEME = build(name="cafe", title="CAFÉ domain ontology", version="0.3",
               concepts=[{"id": "AIAgent", "name": "AI agent", "module": "Engineering",
                          "definition": "software that acts", "alt": ["Agent"], "owner": "EA"},
                         {"id": "UseCase", "name": "Use case", "module": "Business", "parent": "AIAgent"}],
               relationships=[{"subject": "AIAgent", "predicate": "realises", "object": "UseCase",
                               "cardinality": "1..n", "note": "why"}])


def test_the_two_masters_carry_the_concepts_and_the_relationships():
    made = P.masters(SCHEME)
    assert sorted(made) == [P.CONCEPTS_ID, P.RELATIONSHIPS_ID]
    concepts = parse(made[P.CONCEPTS_ID])
    assert concepts.title.startswith("CAFÉ domain ontology") and "concept" in concepts.title.lower()
    assert list(concepts.headers[:4]) == ["id", "name", "module", "kind"]
    rows = {r[0]: dict(zip(concepts.headers, r)) for r in concepts.rows}
    assert rows["AIAgent"]["name"] == "AI agent" and rows["UseCase"]["parent"] == "AIAgent"
    assert rows["AIAgent"]["owner"] == "EA"                       # a column the fabric never modelled survives
    rel = parse(made[P.RELATIONSHIPS_ID])
    assert list(rel.headers) == ["subject", "predicate", "object", "cardinality", "note"]
    assert rel.rows[0][:3] == ("AIAgent", "realises", "UseCase")


def test_the_master_says_which_version_of_which_vocabulary_it_is():
    """A citation opens this. Without the version a reader cannot tell which publication they are looking at."""
    m = parse(P.masters(SCHEME)[P.CONCEPTS_ID])
    assert m.meta["Vocabulary"] == "cafe" and m.meta["Version"] == "0.3"
    assert "steward" in m.meta["Curated by"].lower() or m.meta["Curated by"]


def test_a_retired_concept_is_published_rather_than_dropped():
    """A consumer joining on the old id must still be able to resolve it — dropping the row is what turns a
    correct historical statement into a dangling one."""
    sc = build(name="cafe", title="t", concepts=[{"id": "A", "name": "A"}, {"id": "B", "name": "B"}])
    sc.retire("B", resolves_to="A", reason="merged")
    m = parse(P.masters(sc)[P.CONCEPTS_ID])
    rows = {r[0]: dict(zip(m.headers, r)) for r in m.rows}
    assert rows["B"]["resolves_to"] == "A"


def test_staging_stores_each_master_by_reference_and_hands_back_the_command():
    calls = []

    async def call(cs):
        calls.extend(cs)
        return [{"ref": f'art://store/{a["name"]}', "name": a["name"]} for _, a in cs]

    import asyncio
    out = asyncio.run(P.stage(SCHEME, call=call))
    assert [t for t, _ in calls] == [SemanticTools.store_page, SemanticTools.store_page]
    assert out[P.CONCEPTS_ID]["ref"] == "art://store/ontology-concepts.md"
    cmd = out[P.CONCEPTS_ID]["command"]
    assert cmd.startswith("python -m lab.substrate.reference.publish publish ontology-concepts")
    assert "--master-ref art://store/ontology-concepts.md" in cmd and "--version 0.3" in cmd
    assert "--kind record" in cmd and "--retrieval whole" in cmd and "--key-fields id" in cmd


def test_the_staged_master_is_exactly_what_the_publisher_will_parse():
    """The chain from master to index is mechanical, not promised: the publisher hashes THIS text and derives
    its records from parsing it, so a master this module renders but the publisher cannot read is a lie."""
    for artifact_id, text in P.masters(SCHEME).items():
        m = parse(text)
        assert m.is_table and m.rows, artifact_id
        assert all(len(r) == len(m.headers) for r in m.rows)
        assert all(h == h.strip() and h for h in m.headers)


def test_a_vocabulary_with_nothing_to_publish_is_refused_rather_than_staged_empty():
    empty = build(name="x", title="t", concepts=[{"id": "A", "name": "A"}])
    made = P.masters(empty)
    assert P.RELATIONSHIPS_ID not in made                          # no relationships: no master, not an empty one
    with pytest.raises(ValueError, match="no concepts"):
        P.masters(build(name="x", title="t", concepts=[]))


def test_a_pipe_in_a_definition_does_not_end_the_column():
    sc = build(name="cafe", title="t",
               concepts=[{"id": "A", "name": "A", "definition": "either | or, and a\nnewline"}])
    m = parse(P.masters(sc)[P.CONCEPTS_ID])
    row = dict(zip(m.headers, m.rows[0]))
    assert row["definition"] == "either | or, and a newline"


def test_the_id_a_consumer_joins_on_is_the_one_the_pipeline_already_uses():
    """The whole point of publishing here: the use-case session's switch is an artifact id, not code."""
    assert (P.CONCEPTS_ID, P.RELATIONSHIPS_ID) == ("ontology-concepts", "ontology-relationships")
    assert json.dumps(P.PUBLISH_ARGS[P.CONCEPTS_ID])              # serialisable: it is printed for an operator


def test_the_publishers_own_deriver_turns_the_staged_master_into_records():
    """The end of the chain, checked with the publisher's code rather than with a promise: it hashes the
    master, PARSES it, and derives the records from what came back. A master this module renders but that
    deriver refuses would publish nothing and pass every test here."""
    from lab.core.reference.derive import records

    for artifact_id, text in P.masters(SCHEME).items():
        m = parse(text)
        rows = [dict(zip(m.headers, row)) for row in m.rows]
        keys = P.PUBLISH_ARGS[artifact_id]["key-fields"].split(",")
        derived = records(artifact_id, rows, key_fields=keys)
        assert derived, artifact_id                                   # "derived nothing" is a publish failure
        assert len({d.record_id for d in derived}) == len(derived)    # two rows sharing a key would refuse
    concepts = parse(P.masters(SCHEME)[P.CONCEPTS_ID])
    derived = records(P.CONCEPTS_ID, [dict(zip(concepts.headers, r)) for r in concepts.rows], key_fields=["id"])
    assert {d.body["id"] for d in derived} == {"AIAgent", "UseCase"}


def test_a_relationship_row_is_keyed_on_all_three_ends():
    """Two concepts may be related twice, differently — `realises` and `dependsOn` between the same pair are
    two statements, and a key of (subject, object) would silently keep one."""
    from lab.core.reference.derive import records

    sc = build(name="cafe", title="t", concepts=[{"id": "A", "name": "A"}, {"id": "B", "name": "B"}],
               relationships=[{"subject": "A", "predicate": "realises", "object": "B"},
                              {"subject": "A", "predicate": "dependsOn", "object": "B"}])
    m = parse(P.masters(sc)[P.RELATIONSHIPS_ID])
    rows = [dict(zip(m.headers, r)) for r in m.rows]
    derived = records(P.RELATIONSHIPS_ID, rows, key_fields=["subject", "predicate", "object"])
    assert len(derived) == 2
