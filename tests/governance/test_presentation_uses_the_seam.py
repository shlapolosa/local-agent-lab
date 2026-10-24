"""Presentation is a CLIENT of the seam, never a peer of the service layer (TO-BE, 24 Oct 2026).

Two rings sit OUTSIDE the application, and they are held to different rules:

  PRESENTATION — the review app, the fabric's Teams tab. A surface reaches the lab only through
  `/api` or MCP via the gateway. It may import the domain library, its own package and the few platform
  modules in SURFACE_MAY_IMPORT (config, contracts, identity, the MCP client) — an ALLOW-list. Reaching
  anything else in-process is exactly what makes a surface impossible to replace with a low-code one.

  INBOUND ADAPTERS — the approval channels and the meeting app's bot. The TO-BE diagram puts a
  "queue consumer" here, BELOW the seam: a channel consumes `approvals:requests` and relays a human's
  answer, so it legitimately drives the approval API and the streams. What it may NOT do is reach a
  store: bytes are a provider's business.

KNOWN is a ratchet of today's accepted reaches — shrink it, never grow it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_import_boundaries import _imports, _modules  # noqa: E402

PRESENTATION = ("lab.substrate.review", "lab.substrate.fabricapp")
#: What a surface MAY import beyond the domain library and its own package — an ALLOW-list, so a new
#: reach (a server module, the token validator, a store) fails here instead of slipping past a deny-list.
SURFACE_MAY_IMPORT = ("lab.core", "lab.platform.config", "lab.platform.contracts",
                      "lab.platform.credential", "lab.platform.filetypes", "lab.platform.identity",
                      "lab.platform.mcp_client", "lab.platform.otel",
                      "lab.substrate.netbind",          # binding a socket, nothing more
                      "lab.substrate.fabric_gateway")   # the fabric's gateway identity (a credential, not a store)
ADAPTERS = ("lab.substrate.channels", "lab.substrate.meetingapp")
STORES = ("lab.substrate.artifacts", "lab.substrate.container", "lab.substrate.reference")
INTERNALS = STORES + ("lab.substrate.approvals", "lab.platform.runlog", "lab.platform.workflows",
                      "lab.platform.redis_client", "lab.platform.streams")

KNOWN = {
    # The meeting app's channel REBUILDS the lane comparison and writes it back to the store, and its
    # tab serves stored files: a channel doing a provider's work. Debt, named — see CLAUDE.md TO-BE.
    ("lab.substrate.meetingapp.channel", "lab.substrate.artifacts"),
    ("lab.substrate.meetingapp.service", "lab.substrate.artifacts"),
}


def _reaches():
    mods = _modules()
    out, inbound = set(), set()
    outside = PRESENTATION + ADAPTERS
    for mod, path in mods.items():
        imported = set(_imports(mod, path, mods))
        if mod.startswith(PRESENTATION):
            own = next(p for p in PRESENTATION if mod.startswith(p))
            out |= {(mod, i) for i in imported if i.startswith("lab.")
                    and not i.startswith(SURFACE_MAY_IMPORT + (own,))}
        elif mod.startswith(ADAPTERS):
            out |= {(mod, i) for i in imported if i.startswith(STORES)}
        else:
            inbound |= {(mod, i) for i in imported if i.startswith(outside)}
    return out, inbound


def test_no_surface_or_adapter_reaches_what_its_ring_may_not():
    reaches, _ = _reaches()
    new = reaches - KNOWN
    assert not new, ("a surface reached substrate internals, or an adapter reached a store — "
                     f"go through /api or MCP: {sorted(new)}")


def test_the_ratchet_only_shrinks():
    reaches, _ = _reaches()
    stale = KNOWN - reaches
    assert not stale, f"these reaches are gone — delete them from KNOWN: {sorted(stale)}"


def test_nothing_below_the_seam_imports_a_surface_or_an_adapter():
    _, inbound = _reaches()
    assert not inbound, f"a service imports a presentation surface or an adapter: {sorted(inbound)}"
