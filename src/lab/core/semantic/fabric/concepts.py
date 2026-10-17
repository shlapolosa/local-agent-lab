"""The deterministic lane of the inverted classifier — ground, normalise, match.

The classifier used to be handed ~130 concept definitions and asked which fit. That anchors the answer
(`UseCase` on 37 of the 40 records carrying any subject) and only works while a taxonomy fits in a
prompt. Inverted: a model reads the ARTIFACT and says what it is about in its own words, and everything
after it is this module.

Pure on purpose. The fuzzy half — an embedding — is computed outside and handed in as scores, so every
DECISION here is testable without a model, a gateway or a vector store. The same split as
`citations.py`: search proposes, a rule disposes.

The parameters were MEASURED, not guessed (`scripts/fabric_extraction_probe.py`, 17 Oct 2026, live
records). Two findings shape this file:

  * **97% of evidence spans appear verbatim** in the excerpt, so grounding can be strict. The worry that
    JSON escaping, markdown wrapping and the 2000-character cut would make verbatim matching useless did
    not survive contact with the data — 1 span in 78 needed whitespace tolerance, and 1 failed outright.
  * **The MARGIN decides, not the score.** 'PHI/PII data handling boundaries' matched *PII guardrail* at
    a margin of 0.113; 'proposed decision status' matched *Prior authorisation* at 0.0016 — a coin toss
    between unrelated concepts, which an absolute threshold would have written to the graph as a fact at
    rung X. The median margin across 75 terms was 0.0356, so most terms must fall through to a candidate,
    and that is the vocabulary gap becoming visible rather than a failure.
"""
from __future__ import annotations

import re

_WS = re.compile(r"\s+")
_LEADING_ARTICLE = re.compile(r"^(the|a|an)\s+", re.I)
#: Words that merely END in s. A naive plural rule turns `status` into `statu` and the term stops
#: matching anything at all, which is worse than never having normalised it.
_NOT_PLURAL = re.compile(r"(ss|us|is|as)$", re.I)


def ground(span: str, text: str) -> bool:
    """Is `span` really in `text`?

    A model may NAME a concept the text never names — that is the point of asking a model rather than a
    regex, and 'eventual consistency' is a real subject of a document that never uses the phrase. What it
    may not do is invent the EVIDENCE. So the term survives on inference and the span does not.

    Whitespace-insensitive, and nothing looser. An excerpt is markdown-wrapped and hard-cut mid-word, so
    a model quoting across a line break is quoting honestly; a model quoting with different WORDS is
    paraphrasing, and a paraphrase that counted as evidence would make this check decorative.
    """
    if not span or not text:
        return False
    return _WS.sub(" ", span).strip() in _WS.sub(" ", text)


def normalise(term: str) -> str:
    """The form a term is matched in — what `DomainScheme.find` already does, plus a trailing plural.

    SYMMETRY is the constraint. `find` compares `casefold().strip()` against a label, so normalising the
    term harder than the label LOWERS the hit rate: lemmatising 'referrals' to 'referral' helps only if
    the label is lemmatised too, and the labels belong to a published master that is not ours to rewrite.
    A trailing plural is the one case worth taking, because it is the commonest way a document and a
    vocabulary disagree about the same thing — and it is skipped for words that merely end in s.
    """
    out = _WS.sub(" ", _LEADING_ARTICLE.sub("", str(term or ""))).strip().casefold()
    if out.endswith("s") and not _NOT_PLURAL.search(out) and len(out) > 3:
        out = out[:-1]
    return out


def match(scores: list[dict], *, floor: float, margin: float) -> str | None:
    """The best-scoring concept id, or None. `scores` is `[{id, score}]` as an embedding ranked them.

    TWO gates, and the second is the one that matters. The FLOOR rejects a field of bad answers. The
    MARGIN rejects a field where the top two are indistinguishable — which is what an arbitrary match
    looks like from the inside, and what an absolute threshold cannot see. A 1-2 word term against a
    1-2 sentence definition compresses scores into a narrow band, so "0.71 is high" means nothing on its
    own; "0.71 against a next-best of 0.7084" means the embedding could not tell two unrelated concepts
    apart and must not be believed.

    None is the ordinary answer, not a failure: the term becomes a candidate concept for a steward, which
    is how the vocabulary learns what the corpus needed and it did not have.
    """
    ranked = sorted((s for s in scores or [] if s.get("id")), key=lambda s: s.get("score") or 0.0,
                    reverse=True)
    if not ranked or (ranked[0].get("score") or 0.0) < floor:
        return None
    if len(ranked) > 1 and (ranked[0]["score"] - ranked[1]["score"]) < margin:
        return None
    return str(ranked[0]["id"])


__all__ = ["ground", "normalise", "match"]
