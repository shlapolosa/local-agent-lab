"""The EA-of-the-corpus port: what the domain needs of a governed reference library.

ONE port with distinct verbs, not two ports. The spec's binding sentence is "a human-readable
signed master and an agent-readable form — **the same artifact at the same version**", and that
invariant lives BETWEEN the two forms and ACROSS both access modes. Two ports would mean two
adapters each minting their own notion of "current", and DR-02 would degrade from an invariant into
a reconciliation the caller performs — which is exactly the failure the spec warns about, because a
run that reads a price at v3 and its rationale at v2 has produced a defect nothing would catch.

The two verbs stay distinct, though, and must never collapse into one `query(mode=...)`: `lookup`
has a MISS (zero rows is a legitimate, meaningful answer) and `search` has a RANKING (zero rows
above threshold is emphatically not an all-clear). One error policy cannot serve both.

Nothing here knows Postgres, pgvector or an embedding model. The adapter is chosen by configuration
in `lab.substrate.container`, and on Azure the same port is satisfied by AI Search without a line
changing in the domain.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from lab.core.reference.model import (
    ArtifactHead,
    Consumption,
    PassageResult,
    Pin,
    Record,
    RecordResult,
    RunRef,
)

__all__ = ["ReferenceLibrary"]


@runtime_checkable
class ReferenceLibrary(Protocol):
    """A governed corpus: signed, versioned, released per ring, and read only under a pin."""

    def catalogue(self) -> list[ArtifactHead]:
        """Every artifact this instance may consult, at the version its ring resolves to.

        Never empty on a healthy library. An empty catalogue is indistinguishable from a library
        that is not there, so an adapter raises `ReferenceUnavailable` rather than answering `[]`.
        """
        ...

    def pin(self, artifact_ids: Sequence[str] = ()) -> Pin:
        """Freeze the versions this run will consult; `()` means the whole corpus.

        The ONE place a version is chosen. Every signature and digest is re-verified HERE, on every
        pin rather than once at publish, and any failure fails the WHOLE pin — a run must not begin
        with a partially trustworthy corpus.
        """
        ...

    def pin_by_id(self, pin_id: str) -> Pin:
        """Rehydrate a pin the caller already took, by its id.

        A remote surface is stateless: only the pin_id crosses the wire, and the VERSIONS stay the
        server's record. That is not a convenience — if a caller sent the version set back, it
        could claim a pin it was never given, and the whole point of pinning is that the server
        decided which versions this run reads. Raises `PinExpired` for a pin that has aged out.
        """
        ...

    def lookup(self, pin: Pin, *, record_type: str, key: Mapping[str, Any],
               run: RunRef, limit: int = 20) -> RecordResult:
        """EXACT retrieval. `key` is matched by equality on the published natural key, never
        fuzzily. A miss is a legitimate answer and returns no records; anything that merely
        resembles the key appears under `near`, which is documented as not an answer."""
        ...

    def search(self, pin: Pin, *, question: str, run: RunRef,
               artifact_ids: Sequence[str] = (), k: int = 5) -> PassageResult:
        """SEMANTIC retrieval over prose, with citations.

        Raises `IndexUnavailable` when the pinned version's index is absent, incomplete, or was
        embedded with a different model or dimension than the query — a degraded answer is refused
        rather than ranked (CR-12)."""
        ...

    def record(self, pin: Pin, *, artifact_id: str, record_id: str, run: RunRef) -> Record:
        """One record by the id a citation carries — how a cited answer is re-opened at review."""
        ...

    def consumers(self, *, artifact_id: str, version: str) -> list[Consumption]:
        """The reverse index (FR-45): which runs, and which derived fields, consulted this version.

        Read-only and separately granted — it spans runs, so it is an audit surface rather than
        something a workload's own agents should hold."""
        ...
