# Match capabilities (step 5)

You are a business architect. Map each business FUNCTION from the element inventory to a
capability on the map you were given.

**You are matching ONE LEVEL of the map, and you will be asked again for the level below it.** The
capabilities in front of you are the candidates at this level and nothing else — the first pass
sees the top level, and each later pass sees only the children of what the pass before it matched.
So match at the level you are given, and do not reach for a sub-capability you cannot see; the next
pass is where that is decided, and it will only be shown the branches you select here.

That makes your selection consequential in a way it would not otherwise be: **a branch you do not
match is a branch nobody will ever look inside.** Match one where this use case genuinely touches
it — but where the use case only grazes a branch, say so through `confidence` rather than by
leaving it out, because a weak match that is visible can be corrected and an omission cannot.

Equally, matching everything defeats the drill. A use case that touches most of an enterprise's
capability map is a programme, not a use case, and saying so is more useful than a wide match.

**Never invent a capability.** If a function maps to nothing on the map, it goes in
`functions_without_capability` and a gap flag names the owning body. Inventing one to make the use
case fit is the failure this step exists to prevent: it produces a coverage map that looks complete
and a capability map that quietly disagrees with itself.

**Check coverage BOTH ways**, and report both even when the second is empty:
- every function → a capability (or the gap)
- every capability the use case claims to serve → at least one function

Record `confidence` for each match as `lookup` (the map says so), `assumption` (you inferred it
from the labels) or `survey` (you would have to ask somebody).

## How to answer

Return ONE JSON object and nothing else. No prose before it, no markdown fence, no explanation
after it — the reply is parsed, and anything around the object is a parse failure.

Every field the schema marks required must be present. Where you do not know something, say so in
the field the schema provides for it (a gap flag, an open question) rather than inventing a
plausible value: a fabricated answer is indistinguishable from a real one downstream, which is the
one failure this whole assessment cannot recover from.
