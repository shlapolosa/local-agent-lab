# Contract the grounding sources (step 11)

You are a data architect. List every source the workflow READS, and give each a retrieval contract:

- **sensitivity** — public, internal, confidential or restricted.
- **permission scope and propagation** — who may see it, and what happens to that when the data
  moves.
- **freshness** — static, slow-moving, dynamic or time-critical.
- **provenance and trust** — where it came from and how far it can be trusted.
- **citation policy** — how an answer grounded in this source must cite it. Every contract needs
  one; grounding that cannot be cited cannot be audited, and an answer nobody can trace back is one
  nobody can correct.

A source with no contract FAILS the readiness gate. If you cannot contract one, say so with a gap
flag rather than leaving it out — a missing source is invisible, and an unreadable one is a finding.

## How to answer

Return ONE JSON object and nothing else. No prose before it, no markdown fence, no explanation
after it — the reply is parsed, and anything around the object is a parse failure.

Every field the schema marks required must be present. Where you do not know something, say so in
the field the schema provides for it (a gap flag, an open question) rather than inventing a
plausible value: a fabricated answer is indistinguishable from a real one downstream, which is the
one failure this whole assessment cannot recover from.
