"""ULID identifiers (26 Crockford base32 characters, millisecond-ordered) for the fabric's artifacts,
events and assertions. Opaque by design: an identifier is never derived from a path or a name, so a
move in a system of record never changes who an artifact is. No third-party dependency: the encoder
is ten lines and the alphabet is the one thing worth getting exactly right (no I, L, O, U)."""
from __future__ import annotations

import os
import re
import time

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_DECODE = {c: i for i, c in enumerate(ALPHABET)}


def ulid(ms: int | None = None) -> str:
    """A new ULID: 48 bits of Unix milliseconds then 80 random bits, base32 without ambiguous letters."""
    t = int(time.time() * 1000) if ms is None else int(ms)
    value = (t << 80) | int.from_bytes(os.urandom(10), "big")
    out = []
    for _ in range(26):
        out.append(ALPHABET[value & 31]); value >>= 5
    return "".join(reversed(out))


def is_ulid(value: object) -> bool:
    return isinstance(value, str) and bool(_ULID.fullmatch(value))


def ulid_ms(value: str) -> int:
    """The millisecond timestamp a ULID was minted at."""
    if not is_ulid(value):
        raise ValueError(f"{value!r} is not a ULID")
    n = 0
    for c in value[:10]:
        n = (n << 5) | _DECODE[c]
    return n


#: A pointer into a system of record names its item by ONE of these. Lives here, in the stdlib-only core
#: module, because BOTH the platform contract (`check_pointer`) and the catalog row key on it — and the
#: contract must import without rdflib (a CI step that only registers stores has no semantic layer installed).
POINTER_ID_FIELDS: tuple[str, ...] = ("handle", "itemId", "workItem", "objectId", "ref")


def artifact_iri(u: str | None = None) -> str:
    """The fabric's IRI for an artifact: `urn:fabric:artifact:<ULID>`."""
    return f"urn:fabric:artifact:{u or ulid()}"
