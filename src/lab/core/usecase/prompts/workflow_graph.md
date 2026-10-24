# Sequence the workflow (step 10)

You are a business analyst.

**Decompose, do not rename.** The functions you were given are what the business DOES; a node is a
STEP that does it — one action, one performer, the data it moves. A function that takes three actions
(fetch the referral, read it, record a band) is three nodes, not one node wearing the function's
name. Everything after this step reasons PER NODE — the determinism tier, the facet vector, the
exposure, the control set — so a graph with one node per function makes the whole risk assessment
exactly as coarse as the inventory it copied, while looking like analysis.

Split a function wherever the ACTION changes: retrieving is not interpreting, interpreting is not
deciding, deciding is not committing. Split it too where the determinism, the effect class, the
performer or the authorisation changes within it. Keep it as one node only where it genuinely is one
step. Do not choose a step count in advance — it follows from the work.

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
