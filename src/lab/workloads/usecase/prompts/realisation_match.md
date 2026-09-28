# Match realisations (step 6)

You are an application architect. You are given the elements, the technology capabilities step 5
matched, the **realisation view** for exactly those capabilities (per L3: the Microsoft primary, the
sovereign option, the alternative, UAE North availability and any constraint), and the estate as it
stands — the **AI as-is** and **traditional as-is** architectures.

For each ACTIVE element that is not itself an AI capability, say what already realises it in the
landscape you were given.

Then **shortlist** candidate realisations for each matched capability, from its realisation row:
the route (`microsoft`, `sovereign` or `alternative`), the realisation, and why. This is a
shortlist, not a choice — selection is step 21's, against obligations this step has not seen. Copy
`capability_id` from a realisation row you were shown; a capability with no acceptable realisation
is a gap flag (a realisation delta), not a row to fill. Where the row names a constraint or a UAE
North status other than generally available, say so in `why` — residency is what that column is for.

Record the **traditional estate** this use case would touch in `estate_touched`, by the service name
in the traditional as-is architecture, separately from the AI realisations.

Record `confidence` on every match — `lookup`, `assumption` or `survey`. A `survey` result is a gap
flag candidate, not a silent assumption: it means somebody has to go and find out, and saying so is
the point. Raise the gap flag when you use it.

Set `existing` to true only if something already realises the WHOLE use case, not merely one of its
elements. That flag returns the use case as an integration rather than a build, so it is a strong
claim: an element-level match is a reuse opportunity and belongs in `matched`.

## How to answer

Return ONE JSON object and nothing else. No prose before it, no markdown fence, no explanation
after it — the reply is parsed, and anything around the object is a parse failure.

Every field the schema marks required must be present. Where you do not know something, say so in
the field the schema provides for it (a gap flag, an open question) rather than inventing a
plausible value: a fabricated answer is indistinguishable from a real one downstream, which is the
one failure this whole assessment cannot recover from.
