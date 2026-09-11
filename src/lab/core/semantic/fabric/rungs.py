"""The provenance ladder (docs/fabric/notes/2026-09-11-provenance-ladder.md): every assertion enters the
graph at a rung and can be promoted; each rung IS a named graph, so a SPARQL query over a chosen set of
graphs is, literally, a trust policy. Letters, not numbers: they are the names of the graphs."""
from __future__ import annotations

from rdflib import URIRef

OBSERVED, SUGGESTED, EXTRACTED, CONSTRUCTED, CONFIRMED, DERIVED = "O", "S", "X", "C", "H", "D"
RUNGS: tuple[str, ...] = (OBSERVED, SUGGESTED, EXTRACTED, CONSTRUCTED, CONFIRMED, DERIVED)
#: Rungs that live in the graph. OBSERVED is the Change Events product and never becomes a triple.
GRAPH_RUNGS: tuple[str, ...] = (SUGGESTED, EXTRACTED, CONSTRUCTED, CONFIRMED, DERIVED)
#: What impact analysis may traverse — never S (NFR-7): a wrong edge makes impact confidently wrong.
IMPACT_READS: tuple[str, ...] = (CONSTRUCTED, EXTRACTED, CONFIRMED, DERIVED)
#: Trust order, low to high, for "the weakest input" of a derived assertion.
TRUST_ORDER: dict[str, int] = {SUGGESTED: 1, EXTRACTED: 2, CONSTRUCTED: 3, CONFIRMED: 4, DERIVED: 2}

GRAPH_BASE = "urn:fabric:graph:"
PROV_GRAPH = URIRef(GRAPH_BASE + "prov")          # PROV-O records for every assertion
CANDIDATES_GRAPH = URIRef(GRAPH_BASE + "candidates")   # proposed concepts awaiting a steward


def graph_iri(rung: str) -> URIRef:
    if rung not in GRAPH_RUNGS:
        raise ValueError(f"{rung!r} is not a graph rung — one of {list(GRAPH_RUNGS)} (O never becomes a triple)")
    return URIRef(GRAPH_BASE + rung)


def weakest(*rungs: str) -> str:
    """The grade a derived assertion carries: that of its least-trusted input."""
    return min(rungs, key=lambda r: TRUST_ORDER.get(r, 0))


__all__ = ["RUNGS", "GRAPH_RUNGS", "IMPACT_READS", "TRUST_ORDER", "graph_iri", "weakest",
           "PROV_GRAPH", "CANDIDATES_GRAPH", "OBSERVED", "SUGGESTED", "EXTRACTED",
           "CONSTRUCTED", "CONFIRMED", "DERIVED"]
