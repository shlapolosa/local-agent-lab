"""The Microsoft Graph ADAPTER satisfying `lab.core.collab.CollabRepository`.

The domain port is vendor-neutral ("collaboration": sites, drives, items, meetings, recordings,
transcripts, watches); this package is the one place that knows the provider is Microsoft Graph, and
it lives in the SUBSTRATE because that is where the credentials live. Layered so each concern is
testable alone and offline:

    graph_auth        the app-only credential — a short-lived token from a long-lived secret
    graph_rest        transport — paging, throttling, redirects, streaming; nothing domain-shaped
    graph_map         PURE Graph JSON -> domain objects (and domain -> request bodies)
    graph_probe       PURE classification of a refusal into a sentence a person can act on
    graph_repository  `GraphCollabRepository` — composes the four, implements the port
    server            graph-mcp: the port as governed tools under the gateway alias `collab_mcp`.
                      It talks to the PORT only (through the container's `collab` provider), never
                      to anything above — so it is the collaboration server, not the Graph server,
                      and a second provider replaces this package without touching it.

Nothing here imports `lab.workloads`: the substrate cannot depend on a workload, and the app-only
credential is deliberately a sibling of `lab.workloads.identity` rather than a widening of it — an
agent's gateway credential and a substrate server's Graph credential are different things, and
sharing one helper is how a workload would start minting its own tenant tokens.
"""
