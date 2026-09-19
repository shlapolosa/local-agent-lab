"""Where the rung graphs live between restarts: one N-Quads artifact per named graph in the artifact store,
and a Redis hash (`fabric:graphs`) naming the LATEST ref of each. The in-memory Dataset stays the working
copy (rdflib, SPARQL over vocabularies + fabric in one place); this is its durable shadow.

Why not a triple store: the POC's graph is thousands of quads, not millions, and the substrate already holds
an artifact store and Redis — a second stateful service would be cost without a question it answers. When
the graph outgrows this, `FabricService.on_write` + `snapshot`/`restore` are the one seam: a store adapter
(a managed quad store, or per-assertion appends) replaces this module and nothing above it changes.

SINGLE WRITER, stated plainly: the working copy is per process. Two semantic-mcp replicas would each hold a
divergent Dataset and each publish whole-graph snapshots — last writer wins, the other's assertions gone. So
`save` runs under the platform lock `fabric-graphs`, which serialises writers and makes a second replica
WAIT rather than clobber; it does not merge. The deployment runs ONE semantic-mcp replica until the seam
above is exercised."""
from __future__ import annotations

from typing import Callable, Iterable

from lab.core.semantic.fabric.service import FabricService
from lab.platform import locks

KEY = "fabric:graphs"
LOCK = "fabric-graphs"
CONTENT_TYPE = "application/n-quads"


def _s(v) -> str:
    return v.decode() if isinstance(v, bytes) else str(v)


class RungStore:
    """`artifacts` and `redis` are CALLABLES returning the clients, so the store can be composed at import
    (with the server) and the clients resolved — and overridden by a test — at first use."""

    def __init__(self, artifacts: Callable, redis: Callable) -> None:
        self._artifacts = artifacts
        self._redis = redis

    def save(self, fabric: FabricService, names: Iterable[str]) -> dict[str, str]:
        """Persist the named graphs; returns name -> ref. Called by the service after every conforming write."""
        wanted = [n for n in names if n in fabric.PERSISTED]
        if not wanted:
            return {}
        refs: dict[str, str] = {}
        with locks.lock(LOCK, ttl=60, wait=30, client=self._redis()):
            for name in wanted:
                text = fabric.snapshot(name)
                refs[name] = self._artifacts().put(f"fabric-graph-{name}.nq", text.encode("utf-8"), CONTENT_TYPE)
            self._redis().hset(KEY, mapping=refs)
        return refs

    def refs(self) -> dict[str, str]:
        return {_s(k): _s(v) for k, v in (self._redis().hgetall(KEY) or {}).items()}

    def restore(self, fabric: FabricService) -> dict[str, int]:
        """Load every persisted graph into the service's dataset; returns name -> quads loaded.

        A ref the store no longer holds is SKIPPED and named, never raised. The index lives in
        Redis and the graphs in the artifact store — two stores with independent lifetimes — so
        they can disagree, and on 19 Sep 2026 they did: the artifact store was rebuilt while Redis
        kept its index, every ref pointed at nothing, and the `KeyError` came out of module import.
        semantic-mcp crash-looped, the gateway could then list none of its tools, and every
        workload's preflight refused with "gateway does not expose ['semantic_store_spec']". One
        missing file stopped every business process in the lab.

        A graph that cannot be read is a graph to rebuild. It is printed rather than swallowed,
        because a server that comes up empty and silent is one nobody knows is empty.
        """
        loaded: dict[str, int] = {}
        store = self._artifacts()
        for name, ref in self.refs().items():
            if name not in fabric.PERSISTED:
                continue
            try:
                text = store.get(ref).decode("utf-8")
            except Exception as e:            # noqa: BLE001 — see the docstring
                print(f"rung graph {name!r} not restored from {ref}: {type(e).__name__} — "
                      f"it will be rebuilt on the next conforming write", flush=True)
                continue
            loaded[name] = fabric.restore([text])
        return loaded


__all__ = ["RungStore", "KEY", "LOCK", "CONTENT_TYPE"]
