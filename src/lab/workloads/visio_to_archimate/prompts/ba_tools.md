## Output mode: BUILD the description with tools — do NOT write the JSON yourself

You have deterministic tools that build the system description for you and validate every item as
you go. Do not output the JSON document. Instead, work like this:

1. `set_system(systemName, summary)` — first.
2. `add_elements(items)` — in batches of at most 12. Each item:
   `{group: actors|components|data|behaviors, name, role, layer, aspect, candidateType,
     provenance: {source, representation}, sourceShapeIds?}`.
   READ the tool result: `rejected` lists exactly what is wrong with an item (an invalid `layer`, an
   unknown field, a bad `candidateType`…) — fix and re-add ONLY those items. `added`/`updated` are done.
3. `add_relationships(items)` — batches of at most 12: `{from, to, type, intent}`. Both `from` and `to`
   must already be added (the tool tells you if one is missing — add that element first).
4. `note_questions(items)` — every open question, contradiction, or unreadable shape.
5. Call `finish()` LAST. If it returns `ok: false`, fix exactly what it lists and call `finish()` again.

Then reply with the single line `done`. Everything you would otherwise have put in the JSON goes
through these tools — the same classification rules, layers, evidence and provenance apply.
