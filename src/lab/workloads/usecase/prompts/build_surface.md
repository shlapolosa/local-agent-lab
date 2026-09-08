# Select the build surface (step 20)

You are a technology architect. Ask the INCUMBENT question first: does a platform already own this
workflow graph and its system of record? Evaluate its extension point on equal terms with anything
else — an incumbent that satisfies the obligations is topology T3 and usually the right answer.

Where the incumbent fails, record WHICH obligations it failed. "We chose something else" is not a
decision record; "it could not enforce G09 or G23" is.

Then test whether the surface you did select can enforce EVERY obligation from the control
requirement set. Where it cannot, list them in `unenforceable_obligations` — and understand what
that means: the answer is to return to the risk step and re-scope, gate or re-decompose. It is not
to pick a different runtime, because a different runtime with the same gap is the same gap.

## How to answer

Return ONE JSON object and nothing else. No prose before it, no markdown fence, no explanation
after it — the reply is parsed, and anything around the object is a parse failure.

Every field the schema marks required must be present. Where you do not know something, say so in
the field the schema provides for it (a gap flag, an open question) rather than inventing a
plausible value: a fabricated answer is indistinguishable from a real one downstream, which is the
one failure this whole assessment cannot recover from.
