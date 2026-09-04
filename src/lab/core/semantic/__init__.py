"""Lab semantic layer — vocabularies as data, served as RDF/SPARQL to agents.

Target state: many vocabularies (ArchiMate 3.x now; DOH business glossary, FHIR, TOGAF,
etc. later) behind one registry and one query surface, so agents classify, validate and
ask cross-cutting questions the same way regardless of the domain. Deterministic and
in-process (rdflib) — no server, no embeddings; the store interface is the seam for a
persistent triple store when enterprise scale needs it.
"""
from .ontology import META, Ontology, Registry, SemanticStore, Vocabulary  # noqa: F401
