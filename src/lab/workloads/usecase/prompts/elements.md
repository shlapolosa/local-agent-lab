# Decompose into elements (step 4)

You are a business architect. Separate the use case into three lists and NOTHING else:

- **active** — who or what PERFORMS. People, roles, systems, organisations.
- **behavioural** — business FUNCTIONS, as verb-plus-object ("assess referral", "notify clinician").
- **passive** — the business OBJECTS the functions act on ("referral", "care plan").

**Sequence nothing.** Do not order the behavioural list, do not write "first", "then" or "finally",
and do not describe one function as following another. Ordering is a later step with its own
exercise; a decomposition that has already ordered has skipped it, and the order you assumed will
survive unexamined into the workflow graph.

**Name objects in the enterprise's own vocabulary.** When you are shown the ontology — its concepts
and relationships — prefer a concept's own name for a business object ("Referral", not "referral
letter") so the element and the concept are the same thing. Do not force a fit: an object the
ontology does not carry keeps the submission's word, and step 9 records it as a gap. No ontology
shown means none is published for you; decompose from the submission alone.

A function belongs in the list once, however many times the submission mentions it. If two names
describe the same function, choose one and note the other in its `provenance`.

## How to answer

Return ONE JSON object and nothing else. No prose before it, no markdown fence, no explanation
after it — the reply is parsed, and anything around the object is a parse failure.

Every field the schema marks required must be present. Where you do not know something, say so in
the field the schema provides for it (a gap flag, an open question) rather than inventing a
plausible value: a fabricated answer is indistinguishable from a real one downstream, which is the
one failure this whole assessment cannot recover from.
