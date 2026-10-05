"""The ONE Graph subscription that makes opting in work — kept alive by the meeting app itself.

`appCatalogs/teamsApps/{catalog id}/installedToOnlineMeetings/getAllRecordings`, authorised by
resource-specific consent: Microsoft notifies about every meeting the app was ADDED to and no other.
It is created with the MEETING APP's own credential, never graph-mcp's tenant-wide reader — the
identity that owns it is the whole bound on what it reports (measured 5 Oct 2026: accepted with no
tenant-wide permission, notification 36 s after the meeting ended).

Short-lived on purpose: under an hour, Graph needs no lifecycle endpoint, so there is one less public
route and one less failure mode. The service calls `ensure` on a timer; a subscription that lapsed
anyway (the service was down) is simply created again. A recording finished while it was lapsed is not
announced — the stated gap, closed later by a meeting-end poll if it ever matters."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from lab.substrate.mcp.graph.graph_rest import GraphClient

__all__ = ["resource", "ensure", "LIFETIME", "RENEW_BEFORE"]

LIFETIME = timedelta(minutes=55)        # under Graph's one-hour no-lifecycle ceiling
RENEW_BEFORE = timedelta(minutes=25)    # renewed on a ~15-minute timer, so one missed tick is harmless


def resource(catalog_id: str) -> str:
    return (f"appCatalogs/teamsApps/{catalog_id}/installedToOnlineMeetings/getAllRecordings"
            "?useResourceSpecificConsentBasedAuthorization=true")


def _stamp(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _expiry(s: dict) -> datetime:
    return datetime.fromisoformat(str(s.get("expirationDateTime") or "1970-01-01T00:00:00Z").replace("Z", "+00:00"))


def ensure(client: GraphClient, *, catalog_id: str, base_url: str, client_state: str,
           now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> str:
    """'created' | 'renewed' | 'current'. Ours = the same resource AND the same destination: a
    subscription left pointing at an old host would look healthy and deliver nowhere."""
    want, url = resource(catalog_id), f"{base_url.rstrip('/')}/graph/notifications"
    t = now()
    # no $top: Graph refuses a page size on /subscriptions (measured by graph-mcp's adapter)
    items, _ = client.paged("/subscriptions", None, None, None, top=False)
    ours = [s for s in items if s.get("resource") == want and s.get("notificationUrl") == url]
    if not ours:
        client.post("/subscriptions", {"changeType": "created", "notificationUrl": url, "resource": want,
                                       "expirationDateTime": _stamp(t + LIFETIME), "clientState": client_state})
        return "created"
    current = max(ours, key=_expiry)
    if _expiry(current) - t > RENEW_BEFORE:
        return "current"
    client.patch(f"/subscriptions/{current['id']}", {"expirationDateTime": _stamp(t + LIFETIME)})
    return "renewed"
