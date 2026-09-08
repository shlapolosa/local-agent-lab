# Sequence the workflow (step 10)

You are a business analyst. NOW order the work, as an explicit graph.

One step per business function per active element. Split further only where the determinism, the
effect class or the authorisation changes WITHIN a function — not because a function feels large.
Do not choose a step count: it follows from the function set you were given.

Draw the data-flow edges. Every edge carries a business object, named in `data_class`. An edge with
no data class is a line on a diagram rather than a flow, and the exposure and influence derivations
walk these edges — an edge nobody typed is a control nobody derived.

Every edge must join two nodes that exist in this graph.

## How to answer

Return ONE JSON object and nothing else. No prose before it, no markdown fence, no explanation
after it — the reply is parsed, and anything around the object is a parse failure.

Every field the schema marks required must be present. Where you do not know something, say so in
the field the schema provides for it (a gap flag, an open question) rather than inventing a
plausible value: a fabricated answer is indistinguishable from a real one downstream, which is the
one failure this whole assessment cannot recover from.
