"""Why the reference library did not answer — TYPED, so a caller can say a SENTENCE.

CR-12 and G17 make this more than tidiness: **no all-clear may be inferred from a stale or
unavailable artifact index; retrieval fails closed.** An empty list is the single most dangerous
return value in this layer, because "no guardrail matched" and "the index is not there" look
identical to a caller iterating results, and only one of them means the step is safe.

So nothing here ever degrades into `[]`. Each refusal is its own type and each renders one
sentence: WHAT is unavailable, WHY, and WHAT TO DO about it — the same shape as
`lab.core.collab.errors`, so every surface renders them the same way.

The distinction that matters operationally is between an untrustworthy ARTIFACT and a broken
CONFIGURATION. `ArtifactUnverified` is fixed by re-publishing; a bad trust store is fixed by an
operator. Collapsing them sends whoever is on call to the wrong place.
"""
from __future__ import annotations

__all__ = [
    "ArtifactUnverified", "CorpusUnreachable", "IndexUnavailable", "PinExpired",
    "ReferenceError", "ReferenceUnavailable", "UnknownRecordType",
]


def _sentence(head: str, tail: str = "") -> str:
    out = head.strip().rstrip(".") + "."
    return f"{out} Remedy: {tail.strip().rstrip('.')}." if tail.strip() else out


class ReferenceError(Exception):
    """Base of every reference-library refusal — catch this to handle "the corpus did not answer"."""

    artifact_id: str = ""

    @property
    def sentence(self) -> str:
        return str(self)

    def to_dict(self) -> dict[str, object]:
        return {"artifact": self.artifact_id, "sentence": self.sentence}


class ReferenceUnavailable(ReferenceError):
    """No signed release of this artifact for the ring the caller resolves to.

    Not "the artifact is empty" — nobody has published it to this audience yet, which is an
    administrative state with an owner and a fix.
    """

    def __init__(self, artifact_id: str, ring: int, remedy: str = "") -> None:
        self.artifact_id, self.ring = artifact_id, ring
        super().__init__(_sentence(
            f"{artifact_id!r} has no signed release for ring {ring}",
            remedy or "publish it and release it to this ring before a run pins it"))


class IndexUnavailable(ReferenceError):
    """The pinned version's semantic index is absent, incomplete, or embedded differently.

    A truncated result set would be indistinguishable from a thorough search that found little, so
    the search refuses instead. The model/dimension check is the part people forget: comparing a
    query embedded by one model against passages embedded by another returns plausible nonsense.
    """

    def __init__(self, artifact_id: str, version: str, reason: str) -> None:
        self.artifact_id, self.version = artifact_id, version
        super().__init__(_sentence(
            f"the index for {artifact_id!r} at {version} cannot be searched: {reason}",
            "re-index this version; a partial answer here is worse than none"))


class ArtifactUnverified(ReferenceError):
    """A signature, digest or key check failed. The artifact is not what it claims to be."""

    def __init__(self, artifact_id: str, version: str, reason: str) -> None:
        self.artifact_id, self.version = artifact_id, version
        super().__init__(_sentence(
            f"{artifact_id!r} at {version} failed verification: {reason}",
            "re-publish it from its master; do not serve it in the meantime"))


class PinExpired(ReferenceError):
    """The run's pin has aged out. Reads must not silently drift onto a newer version mid-run."""

    def __init__(self, pin_id: str) -> None:
        super().__init__(_sentence(
            f"pin {pin_id} has expired, and continuing would read a different version from the one "
            f"this run has already cited",
            "take a fresh pin and re-derive, or replay the run"))


class UnknownRecordType(ReferenceError):
    """A lookup for a record type no published artifact declares."""

    def __init__(self, record_type: str, known: list[str]) -> None:
        super().__init__(_sentence(
            f"no published artifact declares the record type {record_type!r}; known types are "
            f"{known}"))


class CorpusUnreachable(ReferenceError):
    """The store behind the corpus could not be read at all.

    Distinct from `ReferenceUnavailable`, which means "nobody has published this to your ring" —
    an administrative state with an owner. This one means the corpus itself is not there: the
    tables have never been created, the credential is wrong, or the database is down. The remedy is
    an operator's, not a publisher's, and telling a caller to "publish it" when the schema does not
    exist sends them to the wrong place.

    Its reason is deliberately the driver's own words, trimmed. A caller cannot act on
    `UndefinedTable` and an operator can, so the sentence carries it rather than flattening it into
    something tidier and less useful.
    """

    def __init__(self, reason: str, remedy: str = "") -> None:
        super().__init__(_sentence(
            f"the reference corpus could not be read: {reason.strip().splitlines()[0][:200]}",
            remedy or "run `python -m lab.substrate.reference.publish init --grants` if the corpus "
                      "has never been created, and check REFERENCE_DB_URL otherwise"))
