"""Seeding the fabric's domain vocabulary from its master.

The ontology is not in the governed corpus, so there is nothing to read there; it arrives the way the licensed
capability workbooks already do — a file the server materialises at start, never a copy committed to this public
repository. What is parsed here is the master's own shape: a markdown table under a heading, which is what the
corpus publisher itself consumes, so the fabric reads the same bytes an operator would later publish.
"""
import pytest

from lab.core.semantic.fabric.vocabulary import DomainScheme
from lab.substrate.mcp.semantic import vocab_seed as V

CONCEPTS_MD = """# Ontology concepts

**Artifact:** ontology_concepts
**Source:** cafe-artifacts.xlsx

| id | name | module | kind | parent | definition |
|---|---|---|---|---|---|
| Referral | Referral | CARE | entity |  | A request to transfer care. |
| UrgentReferral | Urgent referral | CARE | entity | Referral |  |
| DigitalPlatform | Digital platform | ENG | reference |  | A platform that serves care. |
"""

RELATIONSHIPS_MD = """# Ontology relationships

| id | subject | predicate | object | cardinality | note |
|---|---|---|---|---|---|
| R1 | Referral | raisedOn | DigitalPlatform | 1..n |  |
| R2 | UrgentReferral | escalates | Referral |  | urgency is a state |
"""


def test_a_markdown_master_parses_to_rows_by_its_header():
    rows = V.rows(CONCEPTS_MD)
    assert [r["id"] for r in rows] == ["Referral", "UrgentReferral", "DigitalPlatform"]
    assert rows[0]["module"] == "CARE" and rows[0]["definition"] == "A request to transfer care."
    assert rows[1]["parent"] == "Referral" and rows[1]["definition"] == ""      # an empty cell is empty, not None
    assert V.rows("# No table here\n\njust prose\n") == []


def test_a_seed_becomes_a_scheme_with_its_concepts_and_typed_edges(tmp_path):
    (tmp_path / "ontology_concepts.md").write_text(CONCEPTS_MD)
    (tmp_path / "ontology_relationships.md").write_text(RELATIONSHIPS_MD)
    sc = V.load(str(tmp_path), version="v0.30")
    assert isinstance(sc, DomainScheme) and sc.name == V.SCHEME and sc.version == "v0.30"
    assert len(sc.concepts) == 3 and len(sc.relationships) == 2
    assert [c["id"] for c in sc.find("urgent REFERRAL")] == ["UrgentReferral"]
    assert sc.relations_of("DigitalPlatform") == [("raisedOn", "Referral", "in")]


def test_no_master_is_no_scheme_and_says_so_rather_than_half_a_vocabulary(tmp_path, capsys):
    assert V.load(str(tmp_path)) is None
    assert "no ontology master" in capsys.readouterr().out
    (tmp_path / "ontology_concepts.md").write_text(CONCEPTS_MD)
    assert V.load(str(tmp_path)) is None              # concepts without their relationships is not the ontology
    assert "ontology_relationships" in capsys.readouterr().out


def test_a_broken_master_refuses_by_name_rather_than_seeding_a_wrong_graph(tmp_path):
    (tmp_path / "ontology_concepts.md").write_text(CONCEPTS_MD)
    (tmp_path / "ontology_relationships.md").write_text(
        RELATIONSHIPS_MD.replace("| R1 | Referral | raisedOn | DigitalPlatform |", "| R1 | Referral | raisedOn | Ghost |"))
    with pytest.raises(ValueError, match="Ghost"):
        V.load(str(tmp_path))
