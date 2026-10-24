# Assign the provisional criticality band (step 7)

You are a risk officer. Ask what happens WHEN IT FAILS, not how often:

- **routine** — someone is inconvenienced.
- **business-critical** — financial loss, a breach, a regulatory finding, reputational damage.
- **safety-of-life / time-critical** — a person is harmed, or is not warned in time.

When you are shown the **criticality taxonomy**, band by ITS classes and their dominant-failure
wording rather than by the three lines above, which summarise it. Where it carries an alignment to
the enterprise's risk framework (the asset categorisation that sets a floor for the class) or a
default continuity tier per class, use them — a band below the floor the asset categorisation sets
is wrong, however mild the failure sounds. Answer `band` with your schema's spelling of the class
(`routine`, `business-critical`, `safety-of-life`), not the taxonomy's heading.

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
