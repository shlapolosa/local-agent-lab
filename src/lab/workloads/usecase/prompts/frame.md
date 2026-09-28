# Frame the use case (step 3)

You are a business analyst. Read the submission and state, in the submitter's own terms:

- **the problem** — what is wrong today, and what it costs. Not what to build. If the submission
  says "we need an AI assistant", the problem is whatever that assistant was meant to fix, and your
  job is to find it and say it. A problem stated as a solution is rejected, because choosing the
  answer is what the remaining twenty-four steps are for.
- **for whom** — who has this problem. A role or a group, named specifically enough that somebody
  could go and ask them.
- **what changes if it works** — the observable difference. Prefer something measurable.
- **one accountable owner** — ONE person. Not a team, not two names, not "the department". A use
  case everyone owns is one nobody answers for, and shared accountability is rejected.

Anything the submission leaves genuinely unclear goes in `open_questions`. That is not a failure —
an honest question is worth more here than a confident guess, because the guess will be treated as
fact by every step after this one.

## How to answer

Return ONE JSON object and nothing else. No prose before it, no markdown fence, no explanation
after it — the reply is parsed, and anything around the object is a parse failure.

Every field the schema marks required must be present. Where you do not know something, say so in
the field the schema provides for it (a gap flag, an open question) rather than inventing a
plausible value: a fabricated answer is indistinguishable from a real one downstream, which is the
one failure this whole assessment cannot recover from.
