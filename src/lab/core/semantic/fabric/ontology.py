"""The fabric's ontology and document-type scheme as Registry entries (the `Ontology` protocol), read from
the Turtle files beside this module — data, not prose, like every other vocabulary in this package."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph, Namespace, URIRef

HERE = Path(__file__).resolve().parent
FAB = Namespace("urn:fabric:ont#")
DT = Namespace("urn:fabric:scheme:doc-types#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
DCT = Namespace("http://purl.org/dc/terms/")

#: The predicates the fabric's callers spell — as strings, because they cross the gateway as tool arguments.
#: Reads (`catalog_get` links) report the SHORT form (`short()`); writes send the full IRI. One home for both.
DELIVERED_UNDER = str(FAB.deliveredUnder)
REFERENCES = str(FAB.references)
DOCUMENT_TYPE = str(FAB.documentType)
OWNED_BY = str(FAB.ownedBy)
SUBJECT = str(DCT.subject)
CONTEXT_IRI = "urn:fabric:context:"
DECISION_RECORD = str(DT["decision-record"])


def short(iri) -> str:
    """The local name a link is reported under: `documentType`, `deliveredUnder`, `subject` …"""
    s = str(iri)
    return s.rsplit("#", 1)[-1] if "#" in s else s.rsplit("/", 1)[-1]


def _load(name: str) -> Graph:
    g = Graph()
    g.parse(HERE / name, format="turtle")
    return g


@dataclass
class FabricOntology:
    """`fab:` — classes, the three axes, custody and provenance properties."""
    name: str = "fabric"
    base: str = str(FAB)

    @property
    def ns(self) -> Namespace:
        return FAB

    def graph(self) -> Graph:
        return _load("fab.ttl")

    def summary(self) -> dict:
        g = self.graph()
        return {"kind": "ontology", "name": self.name, "base": self.base,
                "classes": len(set(g.subjects(URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type"),
                                              URIRef("http://www.w3.org/2002/07/owl#Class")))),
                "triples": len(g)}


@dataclass
class DocumentTypes:
    """The document-type scheme: one skos:Concept per type the workflows produce; `producedBy` names the
    lab process whose output IS that type, so classification of a lab-produced artifact is a fact (rung C)."""
    name: str = "doc-types"
    base: str = str(DT)

    @property
    def ns(self) -> Namespace:
        return DT

    def graph(self) -> Graph:
        return _load("doc-types.ttl")

    def summary(self) -> dict:
        return {"kind": "skos", "name": self.name, "base": self.base, "concepts": len(self.types())}

    def types(self) -> dict[str, dict]:
        """concept IRI -> {label, alt: [...], produced_by}"""
        g = self.graph()
        out: dict[str, dict] = {}
        for c in g.subjects(SKOS.inScheme, DT.scheme):
            out[str(c)] = {
                "label": str(g.value(c, SKOS.prefLabel) or ""),
                "alt": sorted(str(a) for a in g.objects(c, SKOS.altLabel)),
                "produced_by": str(g.value(c, FAB.producedBy) or ""),
            }
        return out

    def for_process(self, process: str) -> str | None:
        """The type a lab process produces, or None — the deterministic classification path."""
        for iri, t in self.types().items():
            if t["produced_by"] == process:
                return iri
        return None


__all__ = ["FabricOntology", "DocumentTypes", "FAB", "DT", "DCT", "DELIVERED_UNDER", "REFERENCES", "DOCUMENT_TYPE",
           "OWNED_BY", "SUBJECT", "CONTEXT_IRI", "DECISION_RECORD", "short"]
