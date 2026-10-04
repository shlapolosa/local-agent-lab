"""The REFERENCE CORPUS feature's slice of the contract. Re-exported by `lab.platform.contracts` for the callers that
predate the split; a NEW name here is imported from this module directly.

Imported by the package `__init__` AFTER the kernel types it builds on are defined — so import it only
through `lab.platform.contracts` (Python runs that `__init__` first either way).
"""
from __future__ import annotations

from lab.platform.contracts import ToolCatalogue


class ReferenceTools(ToolCatalogue):
    """reference-mcp — the GOVERNED CORPUS: signed, versioned artifacts, read only under a pin.

    Two verbs because there are two problems. `lookup` is exact over records — a nearly-right
    predicate or price line is worse than a failed lookup, so a miss is a legitimate answer and a
    near miss is reported separately from the records. `search` is semantic over the artifacts
    declared `vector` — prose, and record artifacts that also index, whose hits name the record —
    and refuses on a stale or differently-embedded index rather than ranking what it has (CR-12).

    There is deliberately NO WRITE tuple. Publication is an operator CLI holding the signing key and
    the publisher DSN; the server runs as a reader role that the database itself refuses writes
    from (DR-03). There is no tool a workload could be granted that mutates the corpus.
    """
    SERVER = "reference_mcp"
    catalogue = "reference_catalogue"
    pin = "reference_pin"
    #: A pin the caller already holds, rehydrated — what lets a REMOTE reader (decision-mcp,
    #: valuation-mcp, which hold no corpus credential) satisfy the port over these tools.
    pin_info = "reference_pin_info"
    lookup = "reference_lookup"
    search = "reference_search"
    record = "reference_record"
    consumers = "reference_consumers"

    READ = (catalogue, pin, pin_info, lookup, search, record)
    #: The reverse index spans RUNS, so it answers "what else consumed this version" — an audit
    #: question, not a derivation one. Granted separately, and never to a workload's own agents.
    AUDIT = (consumers,)



class VectorStores:
    """The relevance stores the gateway registers (`vector_store_registry`), one per vector-mode
    reference artifact — the store id IS the artifact id.

    A store is a GRANT unit: `object_permission.vector_stores` names stores, so one store per
    artifact lets the screening team hold the capability map and nothing else. A caller searches
    it through the gateway's OpenAI vector-store API, which reaches reference-mcp's façade over the
    same `search` the MCP tool uses — under a pin, attributed, and refused on a stale index. This
    catalogue is the ONE declaration: `scripts/register_vector_stores.py` reconciles the gateway's
    database to it on every deploy (a yaml `vector_store_registry` is deleted from memory by the
    list endpoint whenever a database is configured — verified), and a store here that the gateway
    does not register fails that step loudly rather than a run twenty minutes in.
    """
    CAPABILITY_MAP_HEALTHCARE = "capability-map-healthcare-provider-v2.0"
    CAPABILITY_MAP_INSURANCE = "capability-map-insurance-v5.0"

    #: What a person sees in the gateway UI beside the id.
    DESCRIPTION = {
        CAPABILITY_MAP_HEALTHCARE: "BA Guild Healthcare Provider capability map v2.0 (L1-L3 with "
                                   "path), read under a pin through reference-mcp",
        CAPABILITY_MAP_INSURANCE: "BA Guild Insurance capability map v5.0 (L1-L3 with path), read "
                                  "under a pin through reference-mcp",
    }
    #: The LiteLLM provider every store is served by: the OpenAI-compatible HTTP client that
    #: reference-mcp's façade satisfies.
    PROVIDER = "pg_vector"

    @classmethod
    def names(cls) -> frozenset[str]:
        return frozenset(v for k, v in vars(cls).items()
                         if not k.startswith("_") and k not in ("PROVIDER",) and isinstance(v, str))

    @classmethod
    def for_scheme(cls, scheme: str) -> str:
        """The store (= the corpus artifact) that holds a semantic scheme's capability map. The id
        is `capability-map-<scheme>` by construction, and a scheme with no store refuses here rather
        than at a search that would read as "the map has nothing on this"."""
        store = f"capability-map-{scheme}"
        if store not in cls.names():
            raise ValueError(f"no relevance store holds the capability map for scheme {scheme!r}; "
                             f"the stores are {sorted(cls.names())}")
        return store


# WHAT THIS SLICE CONTRIBUTES — the kernel's registries are assembled from these.
PROCESSES: tuple = ()
AGENTS: tuple = ()
CATALOGUES: tuple[type[ToolCatalogue], ...] = (ReferenceTools,)

__all__ = ["ReferenceTools", "VectorStores", "PROCESSES", "AGENTS", "CATALOGUES"]
