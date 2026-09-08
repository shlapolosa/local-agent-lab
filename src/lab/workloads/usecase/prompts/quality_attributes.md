# Derive quality attributes (step 8)

You are a product owner. Write one scenario per business function, each with a NUMERIC response
measure and the percentile it holds at.

Every response measure must be **taken from an existing business commitment** — an SLA, a
regulatory deadline, an operational target that somebody already owns. Say which, in `taken_from`.

Where no commitment exists, do NOT invent a number. "Fast" is not a response measure and neither is
a figure you chose because it sounded reasonable: a service level nobody committed to will be
designed against, costed, and then missed. Raise a gap flag naming the owning body instead.

## How to answer

Return ONE JSON object and nothing else. No prose before it, no markdown fence, no explanation
after it — the reply is parsed, and anything around the object is a parse failure.

Every field the schema marks required must be present. Where you do not know something, say so in
the field the schema provides for it (a gap flag, an open question) rather than inventing a
plausible value: a fabricated answer is indistinguishable from a real one downstream, which is the
one failure this whole assessment cannot recover from.
