"""How a value becomes a cell of a published master, and how it comes back.

A master is a MARKDOWN TABLE, so everything in it is text — but the artifacts it publishes carry
lists (a family's topologies, a guardrail's sources) and nested objects (a family's variant). Two
functions therefore encode and decode, and they live in ONE module because they are inverses: the
generator that writes the bytes and the adapter that reads them back must agree, and the only way
to keep two functions in step is to be able to test them against each other.

They were not in step. `encode` did two conversions and the mapper reversed one, so a family's
`variant` arrived at the domain as the STRING `'{"name": "federated", ...}'` and `compose` indexed
it as a dict — a `TypeError`, uncaught, on the common case of more than one grounding source.

In `lab.core` rather than beside either caller, because both a generator under `scripts/` and any
adapter under `lab.substrate` need it, and a domain port's mapper is where correctness lives.
"""
from __future__ import annotations

import json
from typing import Any

__all__ = ["LIST_SEP", "decode", "encode"]

#: How a list is joined into one cell. Semicolon because the values that travel this way —
#: identifiers like `T4` or `G07` — never contain one, so the split cannot lose a value.
LIST_SEP = "; "

#: Columns whose published cell is a LIST, whatever it looks like.
#:
#: This has to be declared, and the reason is a property of the FORMAT rather than a gap in the
#: code: a one-element list and a scalar render to the same cell. `["G07"]` and `"G07"` are both
#: `G07`, so `decode` cannot tell them apart by looking, and guessing either way is wrong half the
#: time — a family with one guardrail would come back as a string while a family with two came back
#: as a list, and the domain would index whichever it got.
#:
#: It lives HERE, beside the encoder, rather than beside a reader: it is a property of the
#: artifacts, and a second consumer that re-derived it would drift from the first.
#: Only what the DOMAIN reads as a list. Kept short deliberately — see `decode`.
LIST_COLUMNS = frozenset({"topology", "guardrails", "archetypes", "families"})


def encode(value: Any) -> str:
    """One cell of a rendered table.

    A list becomes `a; b` and a nested object becomes canonical JSON — both so the value SURVIVES
    into the master rather than being rendered as a Python repr no parser can read back. Sorted
    keys, because the master's sha is signed and a dict that rendered in a different order on a
    different day would invalidate a signature without changing a fact.
    """
    if isinstance(value, (list, tuple)):
        return LIST_SEP.join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return "" if value is None else str(value)


def decode(text: Any, name: str = "") -> Any:
    """A published cell, as the domain reads it — `encode`'s inverse, given the column's name.

    The name matters only for `LIST_COLUMNS`, where the format is lossy: a one-element list renders
    exactly like a scalar, so which it is has to be declared rather than guessed.

    Otherwise deliberately conservative: only a cell that LOOKS like an encoded object is parsed as
    one, and anything that does not round-trip comes back as the text it is. Guessing harder would
    turn a capability described as "1; 2" into a list of numbers.
    """
    if not isinstance(text, str):
        return text
    body = text.strip()
    if body.startswith("{") and body.endswith("}"):
        try:
            return json.loads(body)
        except ValueError:
            return text
    # ONLY a declared list column is split. The obvious shortcut — "a cell containing the
    # separator is a list" — is wrong on real data and was: guardrail G04's rule reads "…admitted
    # via the M4 capability map only; projects cannot introduce components unilaterally", and the
    # heuristic turned that sentence into two list items. Prose contains semicolons; a declaration
    # is the only thing that knows the difference.
    if name in LIST_COLUMNS:
        return [part.strip() for part in body.split(";") if part.strip()]
    return text
