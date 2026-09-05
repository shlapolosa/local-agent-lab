"""Which Entra app role each `/api` operation requires — the authorisation POLICY, declared once and
kept apart from whoever enforces it.

WHY ITS OWN MODULE. Two things could plausibly own this table and neither should. The router
(`lab.substrate.mcp.workflow.rest`) knows the paths but is the wrong place to decide who may reach
them, because the front door is not where the caller's identity exists. The gateway hook
(`lab.substrate.gateway.custom_auth`) has the identity but should not carry the front door's URL
shapes as literals. So the policy is a third thing both import: a declarative table of
`(method, path, required role)` that names no enforcement mechanism at all.

That separation is the migration story, not tidiness. Today LiteLLM's `custom_auth` reads this table,
which CLAUDE.md already calls the APIM `validate-jwt` analogue. On Azure the same table becomes APIM
per-operation `<required-claims>` in an inbound policy, and — if the backend is also to check, which
is the zero-trust posture — Container Apps' built-in Entra auth validates at ingress and hands the
claims to the app. In every one of those worlds the TABLE is unchanged and only the reader moves.

WHY NOT PER-TOOL ACLs. The gateway's `mcp_tool_permissions` gates MCP tools by server and tool name.
REST paths are neither, so an ACL cannot see them: before this table, any credential that reached the
gateway could call any `/api` route. That is the hole this closes.

WHAT THIS TABLE DELIBERATELY DOES NOT DO. It does not decide which PROCESS a caller may start. That
question belongs to the process (`ProcessSpec.external`), because "this process may only be started by
approving the question that produced its input" is true of every caller — including the master key,
which no role check would have stopped.

DEFAULT DENY. A path under the prefix that matches no operation is refused rather than allowed: a
route added without a policy entry must fail closed, and a test asserts every generated route matches
exactly one entry.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from lab.platform.contracts import ApiRoles

__all__ = ["API_PREFIX", "Operation", "OPERATIONS", "governs", "operation", "role_for"]

API_PREFIX = "/api"

# One URL path segment: anything but a slash. Process names and opaque ids both live here, and
# neither is validated at this layer — authorisation decides WHO may call, the handler decides
# whether the thing exists. Conflating them leaks which ids are real to a caller with no rights.
_SEG = r"[^/]+"


@dataclass(frozen=True)
class Operation:
    """One addressable operation and the app role it requires."""

    name: str
    method: str
    pattern: re.Pattern[str]
    role: str
    description: str

    def matches(self, method: str, path: str) -> bool:
        return method.upper() == self.method and bool(self.pattern.fullmatch(path.rstrip("/") or path))


def _op(name, method, path, role, description) -> Operation:
    return Operation(name, method, re.compile(re.escape(API_PREFIX) + path), role, description)


# The order is documentation, not precedence: the patterns are disjoint and a test proves it, so a
# reader never has to work out which entry wins.
OPERATIONS: tuple[Operation, ...] = (
    _op("processes.list", "GET", r"/processes", ApiRoles.SUBMIT,
        "what this door will start, and what each process needs"),
    _op("processes.submit", "POST", rf"/processes/{_SEG}/runs", ApiRoles.SUBMIT,
        "start a run"),
    _op("processes.run", "GET", rf"/processes/{_SEG}/runs/{_SEG}", ApiRoles.SUBMIT,
        "the status and outputs of one run"),
    _op("approvals.list", "GET", r"/approvals", ApiRoles.READ,
        "everything still waiting on a person"),
    _op("approvals.get", "GET", rf"/approvals/{_SEG}", ApiRoles.READ,
        "one approval in full, including its question"),
    # Separate from READ on purpose, mirroring ApprovalTools.READ / .WRITE: showing a human what is
    # waiting and RECORDING what they said are different powers, and a relay that can only display
    # must not be one role away from being able to answer.
    _op("approvals.decide", "POST", rf"/approvals/{_SEG}/decide", ApiRoles.DECIDE,
        "record a human's decision, relayed by a client that authenticated them"),
)


def governs(path: str) -> bool:
    """Is this path one this policy is responsible for? Everything under the REST prefix is, INCLUDING
    paths that match no operation — otherwise a typo'd or newly added route would fall outside the
    policy entirely and be allowed by default."""
    p = path or ""
    return p == API_PREFIX or p.startswith(API_PREFIX + "/")


def operation(method: str, path: str) -> Operation | None:
    """The operation this request addresses, or None — which callers must treat as DENY."""
    return next((o for o in OPERATIONS if o.matches(method, path)), None)


def role_for(method: str, path: str) -> str | None:
    """The app role required to make this call, or None when no operation matches (deny)."""
    op = operation(method, path)
    return op.role if op else None
