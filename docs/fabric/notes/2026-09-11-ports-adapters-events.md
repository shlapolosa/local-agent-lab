# Note 003 — The fabric knows contracts, not sources: ports, adapters and events

**Status:** agreed 2026-09-11 · **Applies to:** the conceptual and logical views (Figure 7/8 re-cuts), the
POC on the lab, Annex D "webhook receivers" and "writeback adapters", capability 5.1 Change Detection.

## Decision

The fabric exposes **contracts** and holds **no source credential**. A per-source **adapter** — owned and
deployed separately, one identity with least privilege on its source — satisfies two ports for that source:

| Port | Direction | Contract the fabric defines | Adapter's job |
|---|---|---|---|
| **Inbound events** | source → fabric | `ArtifactChanged {pointer, source kind, actor, timestamp, tag}` in the ontology's terms, on a durable pub/sub | subscribe to the source (Graph change notifications, ADO service hooks, …), translate, publish |
| **Content by reference** | fabric ↔ source | read-by-pointer, write-draft-by-pointer, as governed tools registered with the gateway; bytes never pass through the caller | resolve the pointer against the source API; enforce the source's access decision at read time |

The fabric therefore knows the **pointer scheme**, the **event contract** and the **ontology** — never a
source API. This is the lab's own shape (an MCP server is the adapter, its tool contract the port;
`storage-mcp` / `collab_mcp` are content-by-reference adapters; `workflow:requests` is the inbound stream)
and the initiative doc's "adding an input source is a one-place change".

## Consequences

1. **Two ports, not one.** Pub/sub alone is not enough: classification, synthesis, reference extraction,
   reconciliation and writeback all read or write sources mid-pipeline. Those go through the content port.
2. **Loop guard spans both ports of one source.** The writeback adapter tags fabric-originated writes in the
   source item's metadata; the inbound adapter of the same source filters on the tag. The fabric's 5.1
   Change Attribution is the backstop, not the primary guard.
3. **The stream is durable, at-least-once, idempotent per pointer** (Redis Streams locally; Service Bus
   topics at Transitional; Eventstreams at Target) — the pointer is the idempotency key, exactly as the lab's
   `submit(idempotency_key)` works today. A new event for a pointer with a pending draft REPLACES the draft
   (doc principle 1).
4. **5.1 Change Detection splits.** Event Capture is the adapter's (pro code, per source — it touches a LoB
   system, note 002). Event Filtering and Change Attribution stay in the fabric on the stream. The
   reconciliation sweep (5.5) is the fallback for missed events and uses the content port.
5. **Least privilege moves to the adapter.** Adapter identity = one app registration per source with the
   narrowest scope; the fabric's identity has none. Mirrors "workloads hold no store credentials".
6. **Adding a source** = one adapter satisfying the two ports + one gateway registration + one grant. No
   fabric change. Swapping a store/event/retrieval technology (phased realisation) = one adapter behind the
   store/event/retrieval port. No fabric change.

## Effect on the maps and views
- Annex D "Webhook receivers" → per-source **inbound adapters**; "Writeback adapters" → per-source
  **content adapters** (read + draft-write). Same components, different ownership boundary.
- Conceptual view (Figure 7 re-cut): sources sit OUTSIDE the fabric behind two ports; the fabric band holds
  the four products (note 004) and the facade.
