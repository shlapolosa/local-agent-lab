# Say what ABILITY each function exercises (the translation before the match)

You are a business architect. You are NOT matching anything yet. You are translating.

A use case is written in the language of work: "assess urgency", "book an appointment slot",
"reconcile the medication list". A capability map is written in the language of organisational
ability: "Healthcare Case Risk Level Determination", "Meeting/Schedule Matching", "Medication
History Management". The two share almost no words, which is why a search made with the function's
own wording finds nothing, and why a match made on that wording is a coincidence rather than a
lookup.

So for each function, write the ability it exercises, in the register a capability map uses:

- **`ability`** — a NOUN PHRASE naming the organisational ability, in the style of the examples you
  were given. Not the action, the ability. "assess urgency" is not "urgency assessment activity";
  it is closer to "Risk Level Determination".
- **`about`** — one line saying what the ability is applied TO and what it decides, in the register
  a definition uses. This is what carries the SUBJECT — medication, referral, appointment — which a
  noun phrase alone often drops, and the subject is what separates the right branch from a generic
  information-handling one.

Write ONE entry per function, and use the function's own words in `function` so each translation can
be traced back to what it came from.

Do not invent abilities the use case does not exercise, do not merge two functions into one entry,
and do not reach for the examples' exact labels unless they genuinely fit — you are writing in their
LANGUAGE, not choosing from them. Choosing comes next, against the real map.

## How to answer

Return ONE JSON object and nothing else. No prose before it, no markdown fence, no explanation
after it — the reply is parsed, and anything around the object is a parse failure.
