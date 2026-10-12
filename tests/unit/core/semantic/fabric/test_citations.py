"""Resolving a citation in a document's prose to the RECORD it names.

Impact answers "what does this change break?" by walking INBOUND over `references`, and until now the
only producer of that edge was a synthesised draft pointing back at its source. Measured 12 Oct 2026:
three eRx documents citing each other in plain prose produced `references=0`, so impact over an authored
document returned nothing and always would have.

The rule here is deliberately strict, because a WRONG edge is worse than a missing one: it would put a
document in the blast radius of a change that cannot affect it, and nothing on screen would say so.
"""
from lab.core.semantic.fabric import citations as C


def cand(iri, title):
    return {"iri": iri, "title": title}


A = cand("urn:fabric:artifact:A", "ADR-041-prescription-identifier.md")
B = cand("urn:fabric:artifact:B", "ADR-042-pharmacy-callback-retry.md")


def test_a_citation_naming_the_document_heading_resolves_to_the_file_record():
    """The shape that actually occurs: prose cites a document by its HEADING while the record is titled
    by its FILE NAME. 'ADR-041 Prescription identifier format' vs 'ADR-041-prescription-identifier.md' —
    the record's title is a prefix of the citation once both are normalised."""
    assert C.resolve("ADR-041 Prescription identifier format", [A, B]) == A["iri"]
    assert C.resolve("ADR-042 Pharmacy callback retry policy", [A, B]) == B["iri"]


def test_an_exact_title_resolves():
    assert C.resolve("ADR-041-prescription-identifier.md", [A, B]) == A["iri"]


def test_an_AMBIGUOUS_citation_resolves_to_NOTHING():
    """Two records share a title — the case the fabric exists to surface. Linking either one would be a
    coin toss presented as a fact, so neither is linked. Same rule as `vocab_link` applies to a term with
    two meanings in one scheme."""
    one = cand("urn:fabric:artifact:1", "Dispensing rules.md")
    two = cand("urn:fabric:artifact:2", "Dispensing rules.md")
    assert C.resolve("Dispensing rules", [one, two]) is None


def test_an_acronym_resolves_to_NOTHING_rather_than_a_guess():
    """'eRx Business Requirements Specification' against a record titled 'eRx-BRS.md' is a real citation
    this rule cannot prove. It stays unlinked: an expansion the rule invented would be the fabric
    asserting a relationship nobody can check."""
    brs = cand("urn:fabric:artifact:C", "eRx-BRS.md")
    assert C.resolve("eRx Business Requirements Specification", [brs]) is None


def test_a_document_never_cites_ITSELF():
    """A document that names its own title in its prose — a heading, a footer — would otherwise acquire a
    self-edge, and impact would report it as its own blast radius."""
    assert C.resolve("ADR-041 Prescription identifier format", [A, B], exclude=A["iri"]) is None


def test_nothing_sensible_resolves_to_nothing():
    assert C.resolve("", [A]) is None
    assert C.resolve("see the other document", [A, B]) is None
    assert C.resolve("ADR-041 Prescription identifier format", []) is None
