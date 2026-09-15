# Assign the facet vectors (step 17)

You are a risk officer. Give every step its facet vector, defaulting from the activity verb using
the defaults table you were given, and OVERRIDE only where this step genuinely differs.

**One vector per node of the workflow graph, and every node — no exceptions.** The graph in your
context lists the node ids; your answer carries exactly those ids, one entry each. Everything after
this step reads your set AS the workflow: a set covering three of ten nodes derives a control set
for three steps and reports it as the design's. If a node is hard to classify, classify it anyway
and say why in an override — leaving it out is the one thing that cannot be seen downstream.

**`activity` is one of the seven published verbs**, not the node's own wording: a node called
"assess business-capability match" is `interpret`; "submit a use case" is `retrieve` or `commit`
depending on what it does; "produce recommendation" is `decide`. Map each node to the nearest verb
and record an override if the fit is poor.

Every override carries a written justification. Not "seemed right" — the reason this step is not
like others of its activity. Each override is also a gap flag candidate: if the default is wrong
often enough, the default is wrong.

Do not derive exposure or influence. Those follow from these facets by a published derivation and
belong to a deterministic service — deciding them here would make the derivation an opinion.

## The conditions

Each step also answers the prose conditions the published guardrail predicates ask — "step invokes
any registered tool", "step reads any grounding source", "the step can conclude that nothing is
wrong". Answer **every one** for every step, `true` or `false`.

These describe the step you are already describing; they are not a judgement about controls and you
are not shown which guardrails they turn on. Leaving one out does not make it false — the
derivation REFUSES, because a guardrail that silently fails to fire is invisible, and a control set
that is quietly one short looks exactly like a complete one.

## How to answer

Return ONE JSON object and nothing else. No prose before it, no markdown fence, no explanation
after it — the reply is parsed, and anything around the object is a parse failure.

Every field the schema marks required must be present. Where you do not know something, say so in
the field the schema provides for it (a gap flag, an open question) rather than inventing a
plausible value: a fabricated answer is indistinguishable from a real one downstream, which is the
one failure this whole assessment cannot recover from.
