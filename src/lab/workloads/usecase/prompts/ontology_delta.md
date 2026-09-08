# Check the ontology (step 9)

You are a data architect. Check every PASSIVE element — every business object — against the
ontology you were given. Two checks, and both matter:

- **coverage** — is the object a defined concept, with relationships, rules and data bindings? An
  object that is defined but unbound is `unbound`, not `defined`: a concept with no data behind it
  cannot ground anything.
- **conflict** — does one word mean different things in different parts of the business? List the
  word and each meaning. This is the half a coverage list cannot show, and it is the half that
  causes an agent to confidently answer the wrong question.

Check the objects, not the workflow. What the process does with them is a different step.

## How to answer

Return ONE JSON object and nothing else. No prose before it, no markdown fence, no explanation
after it — the reply is parsed, and anything around the object is a parse failure.

Every field the schema marks required must be present. Where you do not know something, say so in
the field the schema provides for it (a gap flag, an open question) rather than inventing a
plausible value: a fabricated answer is indistinguishable from a real one downstream, which is the
one failure this whole assessment cannot recover from.
