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

TWO CALLER SHAPES, one table. An app registration's client-credentials token carries `roles`; a
PERSON's delegated token (what a custom connector carries) carries the roles assigned to that person,
and the gateway additionally holds the body's `actor` / `requester` to the token (custom_auth). APIM
MIGRATION ITEM: `<required-claims>` covers the role; the actor check is a policy expression on
`approvals.decide` and `processes.submit`, which must be written at cutover.

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
    # The door's own Swagger 2.0 document, for importing a custom connector. Same power as reading
    # the process catalogue, so the same role.
    _op("openapi.get", "GET", r"/openapi\.json", ApiRoles.SUBMIT,
        "this door as an OpenAPI (Swagger 2.0) document, for a custom connector"),
    _op("processes.list", "GET", r"/processes", ApiRoles.SUBMIT,
        "what this door will start, and what each process needs"),
    _op("processes.submit", "POST", rf"/processes/{_SEG}/runs", ApiRoles.SUBMIT,
        "start a run"),
    _op("processes.runs", "GET", rf"/processes/{_SEG}/runs", ApiRoles.SUBMIT,
        "List the runs of one process, newest first, with an optional `q` filter — how a caller "
        "finds a use case submitted earlier. Same power as reading one run, so the same role."),
    _op("processes.run", "GET", rf"/processes/{_SEG}/runs/{_SEG}", ApiRoles.SUBMIT,
        "the status and outputs of one run"),
    # WATCHING one run, as server-sent events, instead of asking for it in a loop. Declared BEFORE
    # nothing and matched exactly, because `{_SEG}` is "anything but a slash" — a pattern loose
    # enough to also match `/runs/{id}` would hand one operation the other's role. Same role as
    # reading the run once, deliberately: watching and polling are the same power, and a weaker
    # rule for the streaming version would be a way around the stronger one.
    _op("processes.run.events", "GET", rf"/processes/{_SEG}/runs/{_SEG}/events", ApiRoles.SUBMIT,
        "watch one run as it moves, as server-sent events"),
    # What a DEPLOY must wait for: a run in flight dies when the gateway restarts under it
    # (measured 11 Sep 2026 — derives, adjudications and a publish all 502'd during one rollout).
    _op("runs.open", "GET", r"/runs/open", ApiRoles.SUBMIT,
        "every run still pending or running, across processes"),
    _op("approvals.list", "GET", r"/approvals", ApiRoles.READ,
        "everything still waiting on a person (or, with `history`, what was decided)"),
    _op("approvals.get", "GET", rf"/approvals/{_SEG}", ApiRoles.READ,
        "one approval in full, including its question"),
    _op("approvals.card", "GET", rf"/approvals/{_SEG}/card", ApiRoles.READ,
        "one approval as the Adaptive Card a surface posts (answers=true adds the inputs)"),
    # Separate from READ on purpose, mirroring ApprovalTools.READ / .WRITE: showing a human what is
    # waiting and RECORDING what they said are different powers, and a relay that can only display
    # must not be one role away from being able to answer.
    # What a PRESENTATION surface needs so it holds no store or Redis credential (TO-BE, 24 Oct
    # 2026). Reading an artifact is part of JUDGING an approval, so it is READ; uploading an input
    # and watching runs are part of submitting work, so they are SUBMIT.
    _op("artifacts.get", "GET", r"/artifacts", ApiRoles.READ,
        "the bytes behind an art:// reference"),
    _op("uploads.put", "POST", r"/uploads", ApiRoles.SUBMIT,
        "store submitted files and answer their art:// references"),
    _op("board.list", "GET", r"/board", ApiRoles.SUBMIT,
        "every run a host reported, in flight and finished"),
    _op("board.run", "GET", rf"/board/{_SEG}", ApiRoles.SUBMIT,
        "one run on the board, with its node history"),
    _op("requests.list", "GET", r"/requests", ApiRoles.SUBMIT,
        "the latest submissions across processes"),
    _op("requests.get", "GET", rf"/requests/{_SEG}", ApiRoles.SUBMIT,
        "one submission by id, whatever its process"),
    # The fabric's STABLE vocabulary verbs (FR-6), forwarded to semantic-mcp. The in-flux verbs
    # (resolve, place, relate) are deliberately absent until they settle.
    _op("vocabulary.match", "GET", r"/vocabulary/match", ApiRoles.VOCAB_READ,
        "which concept a term means, matched against concept definitions"),
    _op("vocabulary.master", "GET", r"/vocabulary/master", ApiRoles.VOCAB_READ,
        "the vocabulary as its two-table master, staged by reference"),
    _op("vocabulary.propose", "POST", r"/vocabulary/proposals", ApiRoles.VOCAB_PROPOSE,
        "park a candidate concept for a steward, with the artifact that proposed it"),
    _op("vocabulary.alias", "POST", r"/vocabulary/aliases", ApiRoles.VOCAB_STEWARD,
        "teach an existing concept another name (a steward's act)"),
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
