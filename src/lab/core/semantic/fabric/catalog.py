"""The Catalog product's PORT (note 004): one row per artifact — identity, custody pointer, the classified
facets, lifecycle — plus the embedding index that is NOT a product but lives beside the rows it indexes.
Metadata only: there is no field a body could go in, and the closed SHACL shape says the same of the graph.

`MemoryCatalog` is the in-process adapter (tests, a laptop); the substrate's Postgres adapter satisfies the
same port over two tables in the database semantic-mcp already reaches."""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Iterable, Protocol, runtime_checkable
from urllib.parse import quote

from lab.core.ids import POINTER_ID_FIELDS      # one home, rdflib-free: the contract and the row agree on it

#: Lifecycle, as the catalog spells it (the graph spells it `fab:Pending` …, see `STATE_IRI`).
STATES: tuple[str, ...] = ("pending", "in-review", "published", "withdrawn")
STATE_IRI: dict[str, str] = {"pending": "urn:fabric:ont#Pending", "in-review": "urn:fabric:ont#InReview",
                             "published": "urn:fabric:ont#Published", "withdrawn": "urn:fabric:ont#Withdrawn"}
#: The classified facets — each is asserted at a provenance rung, never merely set (note 005).
FIELDS: tuple[str, ...] = ("document_type", "owner", "sensitivity_label")
MAX_TITLE = 300


_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)
CUSTODY = "urn:fabric:custody:"


def pointer_id(pointer: dict) -> str:
    """The one field that names the item in its system of record."""
    ident = next((pointer[k] for k in POINTER_ID_FIELDS if pointer.get(k)), None)
    if not pointer.get("source") or ident is None:
        raise ValueError(f"a pointer carries a source and one of {list(POINTER_ID_FIELDS)}: {pointer!r}")
    return str(ident)


def pointer_key(pointer: dict) -> str:
    """`<source>:<item id>` — the identity of an artifact in its system of record."""
    ident = pointer_id(pointer)
    return f"{pointer['source']}:{ident}"


#: every character an IRI may carry unencoded (RFC 3986 reserved + unreserved, and `%` so an already-encoded
#: id stays itself). What is NOT here — space, `<>"{}|\^\`` — is what rdflib refuses to serialise.
_IRI_SAFE = "!#$%&'()*+,/:;=?@[]-._~"


def iri_safe(ident: str) -> str:
    """An absolute id made serialisable: only the characters no IRI may carry are percent-encoded, so a
    legal IRI passes through unchanged. Measured 12 Sep 2026: a minutes ref with spaces in its file name went
    into graph C verbatim and every persist of the fabric failed until it was encoded."""
    return quote(ident, safe=_IRI_SAFE)


def custody_iri(pointer: dict) -> str:
    """The IRI the graph points at for custody (`dcat:accessURL`): the item id itself when it IS an
    absolute IRI (`art://`, `collab://`) — made serialisable — else a fabric custody IRI over the pointer
    key: a bare work-item or EA object id must never be minted as a relative IRI that happens to reparse."""
    ident = pointer_id(pointer)
    return iri_safe(ident) if _SCHEME.match(ident) else CUSTODY + quote(pointer_key(pointer), safe="")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class CatalogEntry:
    iri: str
    pointer: dict
    title: str = ""
    document_type: str = ""          # a doc-types concept IRI
    owner: str = ""                  # a person IRI (urn:fabric:person:<oid>)
    sensitivity_label: str = ""
    state: str = "pending"
    produced_by: str = ""            # the lab process whose run wrote it, if any
    context: str = ""                # the delivery-context key it was delivered under (`<kind>:<id>`)
    source_kind: str = ""
    baseline_version: str = ""
    unassociated: bool = False
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not str(self.iri or "").strip():
            raise ValueError("a catalog entry has an IRI")
        pointer_key(self.pointer)
        if self.state not in STATES:
            raise ValueError(f"state must be one of {list(STATES)}, not {self.state!r}")
        if len(self.title) > MAX_TITLE:
            raise ValueError(f"a title is a label, not a body: {MAX_TITLE} characters")

    @property
    def pointer_key(self) -> str:
        return pointer_key(self.pointer)

    @property
    def custody_iri(self) -> str:
        return custody_iri(self.pointer)

    def with_(self, **changes) -> "CatalogEntry":
        return replace(self, updated_at=_now(), **changes)

    def to_dict(self) -> dict:
        return asdict(self)


@runtime_checkable
class Catalog(Protocol):
    """What the fabric service needs of a catalog store. `put` is an upsert keyed on `iri`."""

    def get(self, iri: str) -> CatalogEntry | None: ...
    def by_pointer(self, key: str) -> CatalogEntry | None: ...
    def put(self, entry: CatalogEntry) -> CatalogEntry: ...
    def put_embedding(self, iri: str, vector: list[float], model: str) -> None: ...
    def embedding(self, iri: str) -> tuple[list[float], str] | None: ...
    def similar(self, vector: list[float], limit: int = 5, *, exclude: str = "",
                model: str = "") -> list[tuple[str, float]]: ...
    def unindexed(self, model: str) -> list[CatalogEntry]:
        """Rows with no vector in `model`'s space (none, or another model's) — never the withdrawn."""
        ...


def subject_labels(links: Iterable[dict]) -> list[str]:
    """The subject concepts a record is linked to, by label when the link carries one (a reference concept's
    id is a hash of its label path — unreadable) and by local name otherwise."""
    return [l.get("label") or str(l["object"]).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
            for l in links if l.get("predicate") == "subject"]


def describe(title: str, document_type: str, subjects: Iterable[str]) -> str:
    """The ONE descriptive text the index is built on — title · type · subjects. Never a body: the index
    proposes neighbours from facets, so re-indexing after an embedder switch needs nothing but the catalog."""
    parts = [title, document_type.rsplit("#", 1)[-1] if document_type else "", *subjects]
    return " · ".join(p for p in parts if p)


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"vectors differ in dimension: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return 0.0 if not na or not nb else dot / (na * nb)


class MemoryCatalog:
    """The port over dicts — what a test, and a server with no `FABRIC_DB_URL`, runs."""

    def __init__(self) -> None:
        self._rows: dict[str, CatalogEntry] = {}
        self._vectors: dict[str, tuple[list[float], str]] = {}

    def get(self, iri: str) -> CatalogEntry | None:
        return self._rows.get(iri)

    def by_pointer(self, key: str) -> CatalogEntry | None:
        return next((e for e in self._rows.values() if e.pointer_key == key), None)

    def put(self, entry: CatalogEntry) -> CatalogEntry:
        self._rows[entry.iri] = entry
        return entry

    def put_embedding(self, iri: str, vector: list[float], model: str) -> None:
        if iri not in self._rows:
            raise LookupError(f"no catalog entry {iri}")
        self._vectors[iri] = (list(vector), model)

    def embedding(self, iri: str) -> tuple[list[float], str] | None:
        return self._vectors.get(iri)

    def similar(self, vector: list[float], limit: int = 5, *, exclude: str = "",
                model: str = "") -> list[tuple[str, float]]:
        """Nearest rows by cosine — within ONE embedding space: with `model`, only vectors of that model
        are compared, so two models' vectors are never ranked against each other."""
        scored = [(iri, cosine(vector, v)) for iri, (v, m) in self._vectors.items()
                  if iri != exclude and (not model or m == model)]
        return sorted(scored, key=lambda t: -t[1])[:max(int(limit), 0)]

    def unindexed(self, model: str) -> list[CatalogEntry]:
        return [e for e in self._rows.values()
                if e.state != "withdrawn" and (e.iri not in self._vectors or self._vectors[e.iri][1] != model)]

    def __len__(self) -> int:
        return len(self._rows)


__all__ = ["Catalog", "CatalogEntry", "MemoryCatalog", "POINTER_ID_FIELDS", "STATES", "STATE_IRI", "FIELDS",
           "MAX_TITLE", "CUSTODY", "pointer_id", "pointer_key", "custody_iri", "iri_safe", "cosine", "describe", "subject_labels"]
