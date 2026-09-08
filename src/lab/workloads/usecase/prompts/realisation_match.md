# Match realisations (step 6)

You are an application architect. For each ACTIVE element that is not itself an AI capability, say
what already realises it in the landscape you were given.

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
