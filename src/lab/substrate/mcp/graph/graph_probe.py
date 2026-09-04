"""What a refusal MEANS — the capability story, pure and testable.

A bare `403` from Microsoft Graph hides at least four administratively different problems, and the
difference is the whole operating experience of this integration:

0. Graph was never reached at all — DNS, TLS, an outbound proxy, a timeout (status 0);
1. the Graph application permission was never consented (`Authorization_RequestDenied`);
2. the permission IS consented but no **Teams application access policy** grants the app access to
   that user's meetings — a SEPARATE requirement, settable only from PowerShell
   (`New-CsApplicationAccessPolicy` + `Grant-CsApplicationAccessPolicy`), taking up to 30 minutes to
   propagate, and by far the usual cause of a confusing 403 on recordings and transcripts;
3. the tenant switched Graph access to transcripts off (inner code `GraphAccessToTranscriptsDisabled`);
4. the tenant is unlicensed or unbilled for the API (402).

`explain()` turns `(status, code, message, capability)` into `(available, reason, remedy)` and every
tool routes its failures through it, so no caller ever relays a status code to a human.

`capabilities_from_roles()` is the cheap half of the probe: an app-only token DECLARES its consented
permissions in its `roles` claim, so the whole table can be rendered without calling Graph once. It
cannot see problem 2 or 3 — those need a live call, which is what the deep probe is for.

**Metering (verified against live documentation, Sep 2026):** since **25 August 2025 the Teams Graph
APIs are no longer metered** and the `model=A|B` parameter is ignored — the metered list is down to
`driveItem: assignSensitivityLabel` (https://learn.microsoft.com/graph/metered-api-list). So the
per-meeting recording and transcript reads this adapter uses need no billing configuration at all.
What `is_metered()` still gates is the TENANT-WIDE feeds (`/communications/onlineMeetings/
getAllRecordings|getAllTranscripts` and subscriptions on them): beta-only, unbounded in blast radius,
and the historical metered surface. Off unless `GRAPH_ALLOW_METERED` says otherwise.
"""
from __future__ import annotations

from lab.core.collab import CAPABILITIES, CollabThrottled, CollabUnavailable

__all__ = ["PERMISSIONS", "POLICY_CAPABILITIES", "METERED_MARKERS", "SECRET_REMEDY",
           "capabilities_from_roles", "explain", "refusal", "is_metered", "metered_refusal"]

_FILES = ("Files.Read.All", "Files.ReadWrite.All", "Sites.Read.All", "Sites.ReadWrite.All",
          "Sites.Selected", "Sites.FullControl.All")
_SITES = ("Sites.Read.All", "Sites.ReadWrite.All", "Sites.Selected", "Sites.FullControl.All")
_MEETINGS = ("OnlineMeetings.Read.All", "OnlineMeetings.ReadWrite.All", "Calendars.Read",
             "Calendars.ReadBasic", "Calendars.ReadWrite")

# Which Microsoft Graph APPLICATION permissions satisfy each capability the port declares. The first
# entry is the least-privileged one to ask for, which is what the remedy recommends.
PERMISSIONS: dict[str, tuple[str, ...]] = {
    "sites": _SITES,
    "drives": _FILES,
    "items": _FILES,
    "content": _FILES,
    "meetings": _MEETINGS,
    "recordings": ("OnlineMeetingRecording.Read.All",),
    "transcripts": ("OnlineMeetingTranscript.Read.All",),
    # A subscription carries no permission of its own: it needs the permission of the resource being
    # watched. So any read grant makes subscribing possible — which one is enough depends on what is
    # watched, and Graph says so at subscribe time.
    "watches": tuple(dict.fromkeys(_SITES + _FILES + _MEETINGS)),
}
# Every capability the port declares must have a permission here, or it cannot be probed at all —
# asserted by tests/unit/substrate/mcp/graph/test_graph_probe.py rather than at import, because a
# module-level assert is a no-op under `python -O`.

# Reading these on behalf of a user needs the Teams application access policy as well as the grant.
POLICY_CAPABILITIES = ("meetings", "recordings", "transcripts")
# Endpoints kept behind GRAPH_ALLOW_METERED: the tenant-wide beta feeds, and the one API that is
# still billed per call.
METERED_MARKERS = ("getallrecordings", "getalltranscripts", "assignsensitivitylabel")

_POLICY_REMEDY = ("grant the Teams application access policy — `New-CsApplicationAccessPolicy` then "
                  "`Grant-CsApplicationAccessPolicy` in Teams PowerShell (it cannot be done in the "
                  "portal), and allow up to 30 minutes for it to propagate")
# The ONE credential remedy: `graph_auth` raises it when Entra refuses the secret, and `explain()`
# returns it on a 401. Two copies would drift, and this one carries the clock-skew hint that is the
# non-obvious third cause.
SECRET_REMEDY = ("check GRAPH_CLIENT_SECRET has not expired, that ENTRA_TENANT_ID and "
                 "GRAPH_CLIENT_ID name the right app registration, and that this host's clock is "
                 "correct — a skewed clock rejects a valid token")


def _consent_remedy(capability: str) -> str:
    grants = PERMISSIONS.get(capability, ())
    wanted = f"grant the application permission {grants[0]}" if grants else "grant the application permission"
    alternatives = f" (or one of {', '.join(grants[1:])})" if len(grants) > 1 else ""
    remedy = f"{wanted}{alternatives} to the app registration and give it admin consent"
    if capability in POLICY_CAPABILITIES:
        remedy += f"; then {_POLICY_REMEDY}, which is required in addition to the permission"
    return remedy


def capabilities_from_roles(roles) -> dict[str, CollabUnavailable | None]:
    """The capability table an app-only token declares — one live call cheaper than probing, because
    the `roles` claim already lists what the tenant consented to. It cannot see a missing Teams
    application access policy or a tenant switch: only a real call finds those."""
    held = tuple(roles or ())
    declared = f"the token declares {', '.join(held)}" if held else \
        "the token declares no Microsoft Graph application permissions at all"
    table: dict[str, CollabUnavailable | None] = {}
    for capability in CAPABILITIES:
        if set(held) & set(PERMISSIONS[capability]):
            table[capability] = None
        else:
            table[capability] = CollabUnavailable(capability, declared, _consent_remedy(capability))
    return table


def explain(status: int, error_code: str = "", message: str = "",
            capability: str = "") -> tuple[bool, str, str]:
    """`(available, reason, remedy)` for one Graph answer. The classification order is deliberate:
    the most specific evidence (an inner code, an explicit message) wins over the status alone."""
    if status <= 0:
        # The transport reports 0 when Graph was never reached (DNS, TLS, a proxy, a timeout). Read
        # as "not >= 400" this would come back AVAILABLE — a capability table that says yes because
        # the network is down is worse than no table at all.
        return False, f"Microsoft Graph could not be reached{f': {message}' if message else ''}", \
            "check this host's network path to Microsoft Graph — DNS, TLS, an outbound proxy or a " \
            "firewall — then re-run the probe"
    if status < 400:
        return True, "", ""
    text, code = f"{message} {error_code}".lower(), (error_code or "").lower()
    if status == 401:
        return False, (f"Microsoft Graph rejected the adapter's own credential (401 "
                       f"{error_code or 'unauthorized'})"), SECRET_REMEDY
    if status == 429:
        return False, "Microsoft Graph is throttling this application", \
            "slow down; the adapter already honours the provider's Retry-After"
    if status >= 500:
        return False, f"Microsoft Graph itself failed ({status} {error_code or 'server error'})", \
            "transient on the provider's side — try again shortly"
    if status == 404:
        return False, "the resource does not exist (or is not visible to this application)", \
            "check the id — a 404 is absence, not a permission problem; per-site access grants " \
            "make an unshared site look absent"
    if status == 402 or "licen" in text or "billing" in text or "azure subscription" in text:
        return False, "the tenant is not licensed or billed for this Microsoft Graph API", \
            "link an Azure subscription to the app for the metered API, or use the per-meeting " \
            "path, which needs no billing configuration"
    if "graphaccesstotranscriptsdisabled" in text:
        return False, "this tenant has switched Microsoft Graph access to meeting transcripts off", \
            "a Teams admin must enable Graph API access to meeting transcripts for the tenant"
    if "application access policy" in text or (status == 403 and "authorization_requestdenied" not in code
                                               and capability in POLICY_CAPABILITIES):
        return False, ("the Teams application access policy is missing — this is separate from the "
                       "Microsoft Graph permission, which may well be consented"), _POLICY_REMEDY
    if status == 403:
        return False, "the Microsoft Graph permission this needs is not consented for the application", \
            _consent_remedy(capability)
    return False, f"Microsoft Graph refused the call ({status} {error_code or 'error'}): {message}".strip(), \
        "check the request against the Microsoft Graph documentation for this resource"


def refusal(status: int, error_code: str = "", message: str = "", capability: str = "",
            retry_after: float | None = None) -> CollabUnavailable | CollabThrottled | None:
    """`explain()` as the typed error a tool raises — `None` when the call actually succeeded."""
    available, reason, remedy = explain(status, error_code, message, capability)
    if available:
        return None
    if status == 429:
        return CollabThrottled(capability, retry_after)
    return CollabUnavailable(capability, reason, remedy)


def is_metered(path: str) -> bool:
    """Whether an endpoint is one of the gated ones (see the module docstring: the tenant-wide beta
    meeting feeds and the one still-billed API), rather than the ordinary per-meeting path."""
    return any(marker in str(path or "").lower() for marker in METERED_MARKERS)


def metered_refusal(capability: str, path: str) -> CollabUnavailable:
    return CollabUnavailable(
        capability,
        f"{path} is a tenant-wide/metered Microsoft Graph endpoint and this deployment does not allow one",
        "set GRAPH_ALLOW_METERED=true (and confirm the tenant's billing) to use it, or stay on the "
        "per-meeting path, which is neither metered nor tenant-wide")
