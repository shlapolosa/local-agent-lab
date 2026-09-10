"""Rules from the governed corpus, under a caller's pin — what decision-mcp and valuation-mcp share.

Both servers derive from published artifacts and both must say which versions they obeyed. The
policy is one and lives here: NO pin, no derivation (a packaged fallback answers from the image
and changes when the image does); a pin that LACKS an artifact this derivation reads REFUSES
rather than answering from anywhere else while still claiming the corpus; every read is by
artifact AND record type (a type is a classification two artifacts may share); and the provenance
returned names the pin and every version in it, so the answer carries what it obeyed.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from fastmcp.exceptions import ToolError

from lab.core.reference import cells
from lab.core.reference.errors import ReferenceError
from lab.core.reference.model import RunRef

__all__ = ["rules"]


def rules(library: Any, pin_id: str, run_id: str, process: str, field: str, *,
          table: Mapping[str, tuple[str, str]], needs: Iterable[str],
          reads: Iterable[str]) -> tuple[dict, dict]:
    """(rules by key, provenance). `table` maps a key to `(artifact_id, record_type)`; `needs`
    names the keys THIS derivation reads; `reads` is the contract's list of artifacts a caller
    must pin, for the sentence a caller with no pin is told."""
    if not pin_id:
        raise ToolError(
            "a derivation reads the governed corpus under a pin: call reference_pin for "
            f"{list(reads)} first and pass its pin_id (with run_id, process and the derived "
            "field), so the rules this answer obeyed are the released ones and are recorded "
            "against the field")
    try:
        pin = library.pin_by_id(pin_id)
        run = RunRef(run_id=run_id, process=process, field=field)
        found: dict[str, list[dict]] = {}
        pinned = {v.artifact_id for v in pin.versions}
        for key in needs:
            artifact_id, record_type = table[key]
            if artifact_id not in pinned:
                raise ToolError(
                    f"the pin does not carry {artifact_id!r}, which this derivation reads. A "
                    f"result derived without it would be silently short, and the answer would "
                    f"still claim the governed corpus. Re-pin once {artifact_id!r} is released to "
                    f"this ring.")
            result = library.lookup(pin, artifact_id=artifact_id, record_type=record_type,
                                    key={}, run=run, limit=500)
            found[key] = cells.rows(result.records)
        return found, {"kind": "governed corpus", "pin_id": pin.pin_id,
                       "versions": [{"artifact_id": v.artifact_id, "version": v.version}
                                    for v in pin.versions]}
    except ReferenceError as exc:
        raise ToolError(exc.sentence) from exc
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
