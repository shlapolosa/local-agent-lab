"""The EA-repository PORT's tools as a CONTRACT FILE — `contracts/ea-tools.json` (FR-11, user decision
24 Oct 2026), vendored verbatim by a channel that emulates the lab's modelling until the lab lands in its
tenant (the SAF pack), and diffed on every re-vendor.

The tool names are the vendor-neutral port (`EATools`, alias `ea_mcp`); adoit-mcp is today's adapter and
its listing is what is rendered. EATools declares no grant tuples — a team is granted the whole server —
so `grants` is empty. VERSION bumped BY HAND (major: a removed/renamed stable tool or a breaking schema
change; minor: an addition). Held byte-for-byte by `tests/governance/test_ea_contract_is_current.py`.
"""
from __future__ import annotations

from lab.platform.contracts import EATools
from lab.substrate.mcp import contract as _contract

__all__ = ["VERSION", "render", "dumps"]

VERSION = "1.0.0"
dumps = _contract.dumps


def render(mcp) -> dict:
    """The contract document for the EA port's tools."""
    return _contract.render(mcp, EATools, VERSION)
