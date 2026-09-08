# Assign the facet vectors (step 17)

You are a risk officer. Give every step its facet vector, defaulting from the activity verb using
the defaults table you were given, and OVERRIDE only where this step genuinely differs.

Every override carries a written justification. Not "seemed right" — the reason this step is not
like others of its activity. Each override is also a gap flag candidate: if the default is wrong
often enough, the default is wrong.

Do not derive exposure or influence. Those follow from these facets by a published derivation and
belong to a deterministic service — deciding them here would make the derivation an opinion.

## How to answer

Return ONE JSON object and nothing else. No prose before it, no markdown fence, no explanation
after it — the reply is parsed, and anything around the object is a parse failure.

Every field the schema marks required must be present. Where you do not know something, say so in
the field the schema provides for it (a gap flag, an open question) rather than inventing a
plausible value: a fabricated answer is indistinguishable from a real one downstream, which is the
one failure this whole assessment cannot recover from.
