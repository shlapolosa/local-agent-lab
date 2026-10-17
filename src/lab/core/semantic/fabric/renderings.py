"""How the text a concept was grounded in was OBTAINED — and how far that is from the artifact itself.

A concept grounded in the words of a document is stronger evidence than the same concept grounded in a
machine transcript of a meeting, and that one is stronger than a concept grounded in a translation of such a
transcript. The intake pipeline reads all three and, until now, recorded them identically: the assertion said
`label-match` whether the matched term came from a `.docx` or from the English rendering of an Arabic turn
that a provider may have dropped altogether.

**Fidelity is a RANK, not a score, and that is deliberate.** The honest claim is an ORDERING — a translated
transcript is further from the artifact than a verbatim one — and this lab has the measurements to make that
ordering rather than a probability. Three, all on one 91.8-second bilingual recording (12 Sep 2026): the
tenant's own transcript returned 53 words and silently dropped every Arabic turn; the same audio through a
verbatim provider returned 86-97 words with both turns present; and a provider asked for the English
rendering returned 97 with both turns translated. There is no experiment here that yields "a transcript is
0.7 of a document", and a number invented to look rigorous would be read as one that was measured. A rank
supports what a reader actually needs — "is this evidence weaker than that evidence" — and nothing it cannot.

So this module is a REGISTRY, and adding a rendering is one line: a new input source (a video, a PDF scan, a
second ASR provider) declares where it sits and why, and every reader orders it without being changed.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Rendering", "RENDERINGS", "DEFAULT", "of", "weaker", "rank_of"]


@dataclass(frozen=True)
class Rendering:
    """One way text reaches the fabric. `rank` is distance FROM the artifact: 0 is the artifact's own words."""
    name: str
    rank: int
    note: str


#: Ordered by how much machinery sits between the artifact and the text a term was grounded in. The note is
#: what a reviewer reads, so it says what can go wrong at that step rather than restating the name.
RENDERINGS: dict[str, Rendering] = {r.name: r for r in (
    Rendering("document", 0, "the artifact's own text, extracted from the file"),
    Rendering("structured", 0, "a structured artifact's own fields — the lab's outputs, read not interpreted"),
    Rendering("page-image", 1, "a page rasterised and read with vision: the layout survives, small text may not"),
    Rendering("figure", 1, "a figure embedded in a document, read with vision"),
    Rendering("transcript", 2, "a machine transcript: a provider may mis-hear a word, or transliterate it into "
                               "the wrong script while getting every word right"),
    Rendering("transcript-translated", 3, "a machine transcript rendered into another language — the words a "
                                          "reader sees are the provider's, not the speaker's"),
)}

#: What an input that does not say how it was read is treated as. The WEAKEST declared rendering, never the
#: strongest: an unstated provenance is the one case where the fabric knows least, and defaulting it to "the
#: document itself" would make the least trustworthy evidence indistinguishable from the most.
DEFAULT = "transcript-translated"


def of(name: str) -> Rendering:
    """The declared rendering, or the DEFAULT for one this lab has not declared. Never raises: an input source
    nobody has classified yet must still be ingestible, and treating it as the weakest evidence is the
    conservative reading — the same stance a screening step takes when its corpus is unpublished."""
    return RENDERINGS.get(str(name or "").strip()) or RENDERINGS[DEFAULT]


def rank_of(name: str) -> int:
    return of(name).rank


def weaker(name: str, than: str) -> bool:
    """Is evidence from `name` further from the artifact than evidence from `than`?

    Strictly further — two renderings at the same rank are not ordered, because the measurements that justify
    this ladder separate a transcript from a document, not a page image from a figure."""
    return rank_of(name) > rank_of(than)
