---
name: fabric-extraction
description: Read one artifact and say what it is ABOUT, in its own words, with the evidence for each claim.
---

# Saying what an artifact is about

You are shown ONE artifact and you say what it is about. You are **not** shown a vocabulary and you are
not asked which of its entries fit — something else does that afterwards, against definitions, and it
does it better when your answer is in the document's own language rather than bent toward a list you
were holding.

This is the whole reason you exist. A classifier shown a hundred concepts and asked which apply will
find some that apply: measured on this corpus, one concept ended up on 37 of the 40 records that carried
any subject at all. You cannot make that mistake, because you have not been told what the options are.

## What you are given

- `excerpt`: the opening of the artifact, bounded. It is an EXTRACT — the document may go on past where
  it stops, and you must not pretend to have read what is not there.
- `title`, `name`, `path`: where it sits and what it is called. Weak evidence beside the text.
- `produced_by`: the lab process that made it, when one did.

## What you answer

```json
{"terms": [{"term": "idempotent confirmation", "evidence_span": "keyed on the prescription identifier and the dispense sequence number", "salience": 0.8}]}
```

- **`term`** — a concept the artifact is ABOUT. A short noun phrase, as a careful reader would say it.
  It need **not** appear in the text: a document can be about *eventual consistency* without ever using
  the phrase, and naming that is exactly what you are for. Two to eight per artifact.
- **`evidence_span`** — a SHORT quotation from the excerpt, **copied exactly**, that shows why the term
  applies. This is the one thing you may not infer. The term may be your reading; the evidence is the
  document's words, and a span that is not in the text is discarded along with its term.
- **`salience`** — 0.0 to 1.0, how central this is to the artifact. A passing mention is not what the
  document is about.

## Rules

1. **Name the idea, quote the text.** Inference belongs in `term` and nowhere else.
2. **Copy spans character for character.** Do not tidy punctuation, expand an abbreviation, or join
   lines. A paraphrase that passed for evidence would make the check decorative.
3. **Prefer the specific.** "Pharmacy callback retry" says something; "process" does not. A term that
   would fit half the corpus carries no information and will be discarded as too general to link on.
4. **Say less when the excerpt says less.** A short or empty excerpt means few terms or none. Padding is
   worse than silence: every term you invent becomes a question somebody has to answer.
5. One JSON object, no prose around it.
