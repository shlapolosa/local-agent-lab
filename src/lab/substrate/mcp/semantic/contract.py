"""The semantic tools as a CONTRACT FILE — `contracts/semantic-tools.json`, vendored verbatim by an
external consumer (the SAF pack) and diffed on every re-vendor (user decision 24 Oct 2026, FR-5).

Rendering is the shared `lab.substrate.mcp.contract`; this module holds what is semantic-mcp's own: the
VERSION (bumped BY HAND — major for a removed or renamed stable tool or a breaking schema change, minor
for an addition) and which grant tuples the file publishes. Held byte-for-byte by
`tests/governance/test_semantic_contract_is_current.py`.
"""
from __future__ import annotations

from lab.platform.contracts import SemanticTools
from lab.substrate.mcp import contract as _contract

__all__ = ["VERSION", "render", "dumps"]

VERSION = "1.1.0"
_GRANTS = ("READ", "PIPELINE", "PROMOTE", "REINDEX", "WALK", "RECLASSIFY", "VIEWS", "WRITE")
dumps = _contract.dumps


def render(mcp) -> dict:
    """The contract document for semantic-mcp's tools."""
    return _contract.render(mcp, SemanticTools, VERSION, _GRANTS)
