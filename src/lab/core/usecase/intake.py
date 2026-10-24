"""What a submitter answered, checked against what the corpus publishes.

`InputField._mapping` validates the SHAPE of an intake — a label is a non-empty string, the whole
thing fits its bounds — and it cannot validate the labels themselves, because the published field
list lives in the corpus and the contract does no I/O. So an agent that paraphrases a question
produces an intake that is accepted, stored, carried into the business case and read by nothing,
with no surface saying so.

The CSV path already names every field it could not match (`intake_csv.parse`). This is the same
report for every other door, so the same mistake is not loud in one and silent in the other.

REPORTED, never refused. A label the corpus does not publish may be a paraphrase, or a field
published since this image was built — and refusing the submission for either would lose the
answers that were fine. It becomes a gap flag the business case carries to the approver, which is
what everything else unresolved here does.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

__all__ = ["gap_flags", "unmatched"]

#: Who closes it. A gap flag with no owner is a complaint.
OWNER = "the submitting channel — a label the corpus does not publish reaches no step"


def _norm(label: str) -> str:
    return " ".join(str(label).split()).casefold()


def unmatched(intake: Mapping[str, Any] | None, published: Sequence[str]) -> list[str]:
    """The intake labels no published field matches, in the order they were given.

    Case and surrounding space are not mistakes and are ignored. NOTHING published means the check
    could not run — an unreadable corpus must not report every label as unmatched, which would
    bury the real ones and blame a submitter for an artifact they cannot reach.
    """
    known = {_norm(name) for name in published or () if str(name).strip()}
    if not known:
        return []
    return [str(label) for label in (intake or {}) if _norm(label) not in known]


def gap_flags(unknown: Sequence[str], published: Sequence[str]) -> list[dict]:
    """ONE gap flag naming every unmatched label — not one per label, which would bury the record
    under a bad paraphrase — in the shape every other gap flag here has."""
    named = [str(label) for label in unknown or () if str(label).strip()]
    if not named:
        return []
    return [{"what": f"{len(named)} intake label(s) match no published field and reach no step: "
                     f"{', '.join(named[:12])}"
                     f"{' …' if len(named) > 12 else ''}. The published fields are "
                     f"{', '.join(list(published)[:6])}"
                     f"{' …' if len(published) > 6 else ''}.",
             "owning_body": OWNER}]
