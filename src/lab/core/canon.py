"""Name canonicalisation — the dedup key for cross-view / cross-source component matching.

Objects in this lab are deduplicated BY NAME: ADOIT's Excel import matches on name, the
`resolve_existing` step searches ADOIT by name, and the staged-object registry is keyed by
canonical name. Transcription variance across views and sources ("API Gateway (Kong)",
"Kong API Gateway", "api-gateway (kong)") must collapse to ONE key, while genuinely different
things ("Payment Service" vs "Payment Gateway") must stay apart. The policy is CONSERVATIVE:
a missed merge is a duplicate a reviewer can spot; a wrong merge silently corrupts the model.

Pure Python, deterministic, no LLM, no network, no state.

Normalisation steps (`canonical()`), in order:
  0. `aliases` (optional, human-curated): if the stripped input equals an alias key — exactly,
     or case-insensitively as a fallback — the alias VALUE replaces the whole name before any
     normalisation. This is the only place explicit equivalences ("PAS" == "Policy Admin
     System") are expressed; it is never inferred.
  1. Unicode NFKC normalisation (full-width/compatibility forms → canonical ASCII where possible,
     e.g. "ＡＰＩ" → "API", "ﬁ" → "fi"; accents are kept).
  2. Case-fold (lowercase).
  3. "&" → " and " ("R&D" → "r and d").
  4. Apostrophes (' ’ `) are DELETED, not split ("Bob's" → "bobs"), so possessives do not leave
     a stray "s" token.
  5. Every other non-alphanumeric character — punctuation, brackets, slashes, hyphens,
     underscores, dots — becomes whitespace. Bracket CONTENT is kept: "(Kong)" contributes the
     token "kong"; "Payer/TPA" → "payer tpa"; "api-gateway" → "api gateway".
  6. Split on whitespace (collapses runs of spaces).
  7. Drop the connective stop-words {"the", "a", "an", "of", "for", "and"} — unless doing so would
     leave no tokens at all (a name consisting only of stop-words keeps them). Nothing else is
     dropped: domain words, acronyms ("PAS", "AFM"), version tokens ("v2", "0") are all kept.
     No stemming, no singularisation ("Providers" != "Provider").
  8. Sort the remaining tokens and join with a single space.

  "API Gateway (Kong)" / "Kong API Gateway" / "api-gateway (kong)"  →  "api gateway kong"

KNOWN LIMITATION (by design): token-sort ignores word ORDER, so two distinct concepts that share
the same token SET merge — e.g. "Service Gateway" and "Gateway Service", or "Customer Order"
and "Order Customer". In EA naming this is rare and the merged pair is at least visibly related;
the alternative (order-sensitive keys) would miss the far more common "X (Y)" vs "Y X"
transcription variance. Anything more aggressive is deliberately NOT done: no fuzzy /
Levenshtein / phonetic matching (over-merges "Payment Service" into "Payment Gateway"-class
neighbours), no stemming, no abbreviation expansion. Explicit equivalences go in `aliases`.

A second, much blunter normaliser lives here too — `squash()` — for VOCABULARY matching
(an ArchiMate type name against a template sheet name or a stencil token: "ApplicationComponent"
== "Application Component" == "application_component"). It is not a dedup key for names — it
drops every separator, so it would merge far too eagerly for that; use `canonical()` there.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Optional

__all__ = ["STOP_WORDS", "tokens", "canonical", "same", "group", "pick_display", "squash"]

# Connective words only. Deliberately small: every extra entry is a potential wrong merge.
STOP_WORDS = frozenset({"the", "a", "an", "of", "for", "and"})

_APOSTROPHES = re.compile(r"['’‘`]")
_NON_ALNUM = re.compile(r"[^0-9a-zÀ-ɏ]+")  # keep latin letters incl. accented; split on the rest
_PUNCT = re.compile(r"[^\w\s]")
_NOT_ASCII_ALNUM = re.compile(r"[^a-z0-9]")


def squash(s: object) -> str:
    """Punctuation-squash normaliser for vocabulary matching: lowercase ASCII letters and digits
    ONLY, everything else removed — "Course of Action" -> "courseofaction".

    ASCII-fold policy (deliberate, deterministic): the text is NFKD-decomposed and combining marks
    are dropped BEFORE the squash, so an accented letter folds to its base letter ("é" -> "e",
    "ＡＰＩ" -> "api") instead of silently disappearing; a letter with no ASCII base ("Ω", CJK)
    IS dropped, because the vocabularies this matches against (ArchiMate types, template sheet
    names, stencil tokens) are ASCII. Non-strings are stringified; None -> "".
    """
    text = "" if s is None else str(s)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return _NOT_ASCII_ALNUM.sub("", text.lower())


def _apply_aliases(name: str, aliases: Optional[Dict[str, str]]) -> str:
    if not aliases:
        return name
    if name in aliases:
        return aliases[name]
    folded = name.casefold()
    for key, value in aliases.items():  # deterministic: dict order; exact match already tried
        if key.strip().casefold() == folded:
            return value
    return name


def tokens(name: str, aliases: Optional[Dict[str, str]] = None) -> List[str]:
    """The sorted token list behind `canonical()` (steps 0–8 above, minus the final join)."""
    if name is None:
        return []
    text = _apply_aliases(name.strip(), aliases)
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()
    text = text.replace("&", " and ")
    text = _APOSTROPHES.sub("", text)
    text = _NON_ALNUM.sub(" ", text)
    toks = text.split()
    kept = [t for t in toks if t not in STOP_WORDS]
    if not kept:
        kept = toks  # never reduce a non-empty name to nothing
    return sorted(kept)


def canonical(name: str, aliases: Optional[Dict[str, str]] = None) -> str:
    """Deterministic dedup key for a component/object name (see module docstring)."""
    return " ".join(tokens(name, aliases))


def same(a: str, b: str, aliases: Optional[Dict[str, str]] = None) -> bool:
    """True when two names map to the same canonical key."""
    return canonical(a, aliases) == canonical(b, aliases)


def group(names: Iterable[str], aliases: Optional[Dict[str, str]] = None) -> Dict[str, List[str]]:
    """canonical key → the distinct original names (stripped, first-seen order) that map to it.

    Keys appear in first-seen order; exact duplicates are collapsed. Use it to REPORT merges
    before committing them: any key with more than one original is a merge decision.
    """
    out: Dict[str, List[str]] = {}
    for raw in names:
        if raw is None:
            continue
        original = raw.strip()
        if not original:
            continue
        key = canonical(original, aliases)
        bucket = out.setdefault(key, [])
        if original not in bucket:
            bucket.append(original)
    return out


def _display_rank(name: str):
    # Most informative first: longest, then most punctuation (brackets/slashes carry the
    # qualifier), then most upper-case letters (proper casing over "api-gateway"), then
    # lexicographic as the final, total tie-break. Independent of input order.
    return (-len(name), -len(_PUNCT.findall(name)), -sum(1 for c in name if c.isupper()), name)


def pick_display(names: Iterable[str]) -> str:
    """A stable display name for a group of equivalent originals.

    Picks the longest original, then the most punctuated, then the one with the most upper-case
    letters, then the lexicographically smallest — so the result is identical whatever order the
    names arrive in. Returns "" for an empty group.
    """
    cleaned = sorted({n.strip() for n in names if n is not None and n.strip()}, key=_display_rank)
    return cleaned[0] if cleaned else ""
