"""Admin replaces a reference artifact's master — validated, diffed, staged. Never published.

The split, and why it is not squeamishness. The corpus publisher holds the Ed25519 signing seed,
which the publish CLI keeps off `.env` and `LAB_ENV` on the grounds that it "belongs on the
publishing workstation only". Putting it behind a web session would make the thing that signs the
corpus reachable by anyone who reaches the page. So this module does the part that actually prevents
a bad corpus — parse, derive, refuse, diff — and an operator does the part that needs the key.

**The validation is the publisher's own.** `master.parse` then `derive.records` with the artifact's
declared `key_fields` are exactly what the publisher runs, so an upload that stages here is an
upload that will publish there. Re-implementing the rules would let the two drift, and the drift
would only surface at release — which is the moment it is most expensive.

What an admin gets that a file handed over out of band does not: a refusal that names the row, and a
DIFF against what is released. They are approving a CHANGE, and a record count cannot be checked
against intent.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from lab.core.reference import derive, master

__all__ = ["Staged", "StagingError", "artifact_names", "key_fields_for", "list_staged", "stage"]

#: Where a candidate lives between staging and release. Deliberately a module-level dict rather than
#: Redis or the store: a candidate is not governed content, it must not be mistaken for the corpus,
#: and it should not survive a restart — an operator who has not released it within the life of the
#: app should be handed the file again rather than find it waiting.
_STAGED: dict[str, dict] = {}


class StagingError(ValueError):
    """The upload cannot be staged, and the message says which row and why. Raised rather than
    returned, because a half-validated candidate is the thing this module exists to prevent."""


@dataclass(frozen=True)
class Staged:
    """What was staged, and what it would change."""

    artifact_id: str
    records: int
    added: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    changed: list[dict] = field(default_factory=list)

    @property
    def unchanged(self) -> bool:
        return not (self.added or self.removed or self.changed)


def _catalogue() -> dict[str, tuple[str, str, str]]:
    """The artifact table the publisher publishes from — `id -> (record_type, key_fields, owner)`.

    Imported lazily and by path because it lives in `scripts/`, which is not an importable package.
    A missing catalogue is an empty one: the page then says so rather than offering a list it cannot
    validate against.
    """
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location(
        "_publish_corpus", root / "scripts" / "publish_usecase_corpus.py")
    if not spec or not spec.loader:
        return {}
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return dict(module.ARTIFACTS)
    except Exception:                    # noqa: BLE001 — an unreadable catalogue is not a crash
        return {}


def artifact_names() -> list[str]:
    """Every artifact an admin may replace, in the order a person reads them."""
    return sorted(_catalogue())


def key_fields_for(artifact_id: str) -> list[str]:
    entry = _catalogue().get(artifact_id)
    if not entry:
        raise StagingError(f"{artifact_id!r} is not a published artifact — have {artifact_names()}")
    return [f.strip() for f in str(entry[1]).split(",") if f.strip()]


def _rows(parsed: master.Master) -> list[dict]:
    return [dict(zip(parsed.headers, row)) for row in parsed.rows]


def _diff(new: list[dict], released: Mapping[str, Mapping[str, Any]],
          keys: list[str]) -> tuple[list[dict], list[dict], list[dict]]:
    def ident(row: Mapping[str, Any]) -> str:
        return " · ".join(str(row.get(k, "")).strip() for k in keys)

    now = {ident(r): r for r in new}
    added = [dict(r) for k, r in now.items() if k not in released]
    removed = [dict(r) for k, r in released.items() if k not in now]
    changed = []
    for k, row in now.items():
        was = released.get(k)
        if not was:
            continue
        moved = sorted(f for f in set(row) | set(was)
                       if str(row.get(f, "")).strip() != str(was.get(f, "")).strip())
        if moved:
            changed.append(dict(row, fields=", ".join(moved)))
    return added, removed, changed


def stage(artifact_id: str, body: bytes, *, actor: str, store: dict | None = None,
          released: Mapping[str, Mapping[str, Any]] | None = None) -> Staged:
    """Validate an uploaded master and hold it as this artifact's candidate.

    `released` is what the corpus currently serves, keyed by natural key — supplied by the caller so
    this stays pure and testable. Absent, everything reads as added, which is the honest answer when
    nothing is known rather than a claim that nothing changed.
    """
    keys = key_fields_for(artifact_id)                 # refuses an unknown artifact first
    try:
        parsed = master.parse(body.decode("utf-8", errors="replace"))
    except master.MasterError as bad:
        raise StagingError(f"{artifact_id}: {bad}") from bad
    rows = _rows(parsed)
    try:
        # The PUBLISHER's own derivation: a missing key field, a duplicate natural key and a master
        # that derives nothing are all refused here, by the same code and with the same message.
        derived = derive.records(artifact_id, rows, key_fields=keys)
    except derive.DerivationError as bad:
        raise StagingError(f"{artifact_id}: {bad}") from bad
    if not derived:
        raise StagingError(f"{artifact_id}: the master derived no records. An empty register "
                           f"releases as 'nothing is relevant' to every consumer that reads it "
                           f"whole, which is indistinguishable from a blank file being uploaded.")

    added, removed, changed = _diff(rows, released or {}, keys)
    where = _STAGED if store is None else store

    # ONE candidate per artifact: an operator releasing "the staged one" must not have to choose
    # between three, and the newest upload is what the admin meant.
    where[artifact_id] = {
        "artifact_id": artifact_id, "actor": actor, "records": len(derived),
        "staged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha256": hashlib.sha256(body).hexdigest(), "master": body.decode("utf-8", "replace"),
        "diff": json.dumps({"added": len(added), "removed": len(removed), "changed": len(changed)}),
    }
    return Staged(artifact_id=artifact_id, records=len(derived),
                  added=added, removed=removed, changed=changed)


def list_staged(store: dict | None = None) -> list[dict]:
    where = _STAGED if store is None else store
    return [{k: v for k, v in c.items() if k != "master"}
            for c in sorted(where.values(), key=lambda c: c["staged_at"])]
