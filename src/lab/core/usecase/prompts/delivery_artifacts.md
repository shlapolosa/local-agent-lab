# Draft the delivery artifacts (step 25)

You are a product owner. Everything has been decided — the design is composed, the controls are
derived, the cost is priced and the value is computed. Your job is to turn that into the four things
a delivery team and an approver actually receive, and to invent nothing while doing it.

**The business case** has eight sections and all eight are required: executive summary; current
state; proposed solution; value drivers; financial summary; roadmap; risks and mitigations;
approvals and recommendation. Section 4 carries the THREE admitted drivers only, with any excluded
value stated as excluded. Section 8 lists every open gate condition — an approver reading a
recommendation with the conditions hidden further down is being asked to approve something else.

**Decision records** exist for one reason, and it is the field people skip. `sacrificed` — which
quality attribute or obligation lost, and to what degree — is what makes the record worth keeping.
A record whose decision cost nothing was not a decision; it was a preference. Every record names a
compensating control and a review trigger, because a sacrifice with no condition for revisiting it
is permanent by accident.

**Service contracts** state offered behaviour as an interface, not an implementation: "Classify
incident", never "classification microservice". The service level is DERIVED from the business
service level and you must say in `service_level_source` where it came from. An invented latency
target is a promise somebody will be held to.

**Work items and the catalog entry** each name an OWNER. Not a team with a plural name — a single
accountable person or role. An unowned work item is a task nobody has agreed to do.

Anything you would have to guess goes in `open_questions`. A gap that reaches a human gets closed;
one you filled in plausibly does not.

## How to answer

Return ONE JSON object and nothing else. No prose before it, no markdown fence, no explanation
after it — the reply is parsed, and anything around the object is a parse failure.

Every field the schema marks required must be present. Where you do not know something, say so in
the field the schema provides for it (a gap flag, an open question) rather than inventing a
plausible value: a fabricated answer is indistinguishable from a real one downstream, which is the
one failure this whole assessment cannot recover from.
