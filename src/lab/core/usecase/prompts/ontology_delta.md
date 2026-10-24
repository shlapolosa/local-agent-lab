# Check the ontology (step 9)

You are a data architect. Match every PASSIVE element — every business object — to the enterprise's
**CAFÉ ontology** you were given: its concepts (each with an id, module, kind, parent and
definition) and the relationships between them.

**1. Each object, matched by id.** Name the ontology concept it matches in `id`, copied exactly as
the ontology gives it, and give one status:

- `matched` — the concept exists and fits the use case as it is;
- `partial` — it exists but covers only part of what is needed; say which part in `note`;
- `enhancement` — it exists and the use case needs it extended (a new attribute, state or
  relationship); say what in `note`;
- `gap` — the ontology has nothing for it. A gap is a **proposal** to the Ontology Council, so it
  must be reviewable: give its `name`, the `module` it belongs in, its `kind` (in the ontology's own
  kinds) and a one-line `definition`. A gap has no `id`. Never invent an id to avoid a gap.

**2. The relationships the use case needs.** List only those it ADDS or CHANGES — relationships
that already exist between the concepts you matched are drawn without being listed. Name each end
by concept id, or by a gap's object name. `matched` if the ontology already carries it,
`enhancement` if it needs changing, `gap` if it is new. An empty list is a claim that the use case
needs nothing the ontology does not already relate.

**3. Conflicts.** Does one word mean different things in different parts of the business? List the
word and each meaning. This is the half a coverage list cannot show, and it is the half that causes
an agent to confidently answer the wrong question. Report it even when empty.

Gaps and new relationships are the ontology delta; the page this step is drawn as puts them in red.
Check the objects, not the workflow — what the process does with them is a different step.

## How to answer

Return ONE JSON object and nothing else. No prose before it, no markdown fence, no explanation
after it — the reply is parsed, and anything around the object is a parse failure.

Every field the schema marks required must be present. Where you do not know something, say so in
the field the schema provides for it (a gap flag, an open question) rather than inventing a
plausible value: a fabricated answer is indistinguishable from a real one downstream, which is the
one failure this whole assessment cannot recover from.
