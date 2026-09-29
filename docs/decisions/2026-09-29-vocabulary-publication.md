# The fabric stages its vocabulary; an operator publishes it

29 September 2026 · Documentation Fabric, WP26

## The decision

The Documentation Fabric **renders and stages** the vocabulary it owns as a governed artifact's master, and an
**operator signs and publishes** it into the reference corpus. The fabric does not publish, and gains no tool
that could.

Published under `ontology-concepts` and `ontology-relationships`, `kind: record`, `retrieval: whole` — the ids
the use-case pipeline already joins on, so its switch from a packaged copy to the fabric's is an artifact id and
not a line of code.

## Why the fabric cannot publish

Three independent facts, none of which is an oversight to be fixed:

1. **Publication has no tool surface.** `lab.substrate.reference.publish` is an operator CLI. Nothing exposes
   it through the gateway, so no agent and no workload can reach it.
2. **The signing seed is off every service.** `var/run/reference_signing_key` is deliberately absent from
   `.env` and from `LAB_ENV`. A service that could sign a version could mint one nobody decided.
3. **The corpus reader holds SELECT.** `lab_reference_reader` can insert into `ref_pin` and `ref_consumption`
   and nothing else — DR-03 as a GRANT rather than as a convention.

So the honest split is the one the licensed workbooks already use in reverse: the private, tenant-sourced
content travels **by reference** through the artifact store, and a person with the seed releases it.

`semantic_vocab_master(scheme)` renders the two masters, stores each by `art://` ref, and returns the exact
command to run. It stages; it cannot release.

## Why the master is the source, not a by-product

DR-02 says the master and the agent-readable form are the same artifact at the same version, and
`derived_from = master_sha256` says the second was derived from the first. That is only TRUE if the derivation
actually happens. The publisher hashes the master, **parses it**, and derives its records from what came back —
so this module renders markdown and emits no second, independently-built form. A master that rendered here but
that `lab.core.reference.derive.records` refused would publish nothing while passing every test that only
looked at the rendering, which is why the round trip is asserted with the publisher's own deriver.

## What is deliberately NOT done

**semantic-mcp is not wired to read the corpus.** The plan called for `REFERENCE_PROVIDER=mcp` on its
`SUBSTRATE` row plus `REFERENCE_MCP_URL`/`REFERENCE_RING` in its `ROLE_ENV`. Measured: **semantic-mcp calls
`server.reference()` nowhere**, so those variables would be configuration that nothing reads — and the hazard
is real, not cosmetic: `REFERENCE_PROVIDER` defaults to postgres and `REFERENCE_DB_URL` falls back to
`DATABASE_URL`, so a half-wired reference client points at the LiteLLM registry and says nothing.

The consumer of this publication is the **use-case pipeline**, which already reads the corpus through
reference-mcp under a pin. It needs no change here beyond the artifact id.

The wiring becomes real when the fabric SEEDS its vocabulary from the corpus rather than from
`FABRIC_VOCAB_REFS` — closing the loop so the fabric reads back what it published. That is a genuine next
step and a different change, and it should carry the two deploy lines with it, together, because either alone
fails and one of them fails silently.

## Consequences

- A vocabulary version is published only when a person runs the command, so the corpus never moves under a
  consumer because a sweep decided something.
- Retired concepts are published, not dropped: a consumer joining on an old id still resolves it.
- The master is a document a steward can open. It carries the vocabulary, the version, and the sentence that
  says admissions and retirements are recorded with the name of whoever made them.
- The staged content is tenant-sourced and stays out of this repository: it is stored by `art://` ref and
  never logged.
