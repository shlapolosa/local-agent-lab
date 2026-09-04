## Output mode: BUILD the model with tools — do NOT write the JSON spec yourself

You have deterministic tools that build the ArchiMate model spec and validate every item as you go —
including **ArchiMate 3.1 relationship legality** against the full relationship matrix. Do not output
the JSON spec. Work like this:

1. `set_model(name, id?)` — first (id: a stable slug of the system name).
2. `add_elements(items)` — batches of at most 12. Each item `{id, type, name, doc?, folder?}`:
   `type` must be the EXACT ArchiMate 3.1 type name (the tool suggests the right one if you misspell);
   `id` is a stable slug — or, for an element matched to an EXISTING repository object, that object's
   `adoit_id` VERBATIM (so it is updated, not duplicated). READ the result and fix only `rejected` items.
3. `add_relations(items)` — batches of at most 12: `{type, src, tgt, accessType?}`. Both ends must be
   added ids. If a relation is **not permitted** between those two types, the tool rejects it and lists
   the ALLOWED types — pick the one that expresses the true meaning (a component *realizes* a service and
   is *assigned to* a function; it does not "aggregate" them; technology *realizes* an application
   component). Never force an illegal relation through a different pair.
4. `add_view(id, title, element_ids)` — one view per meaningful diagram, over added ids only.
5. Call `finish()` LAST. If it returns `ok: false`, fix exactly what it lists and call `finish()` again.

Then reply with the single line `done`. Everything you would otherwise have put in the spec goes
through these tools — the same modelling rules, id reuse, and domain `folder` apply.
