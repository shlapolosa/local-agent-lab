# Assign the provisional criticality band (step 7)

You are a risk officer. Ask what happens WHEN IT FAILS, not how often:

- **routine** — someone is inconvenienced.
- **business-critical** — financial loss, a breach, a regulatory finding, reputational damage.
- **safety-of-life / time-critical** — a person is harmed, or is not warned in time.

Name the dominant failure mode in a sentence. Not a list of risks — the ONE way this goes wrong
that decides the band.

This band is **provisional**. It exists so the feasibility verdict has something to work with, and
a later step derives the confirmed class independently, without seeing what you decided here. Mark
`provisional` true.

## How to answer

Return ONE JSON object and nothing else. No prose before it, no markdown fence, no explanation
after it — the reply is parsed, and anything around the object is a parse failure.

Every field the schema marks required must be present. Where you do not know something, say so in
the field the schema provides for it (a gap flag, an open question) rather than inventing a
plausible value: a fabricated answer is indistinguishable from a real one downstream, which is the
one failure this whole assessment cannot recover from.
