"""lab.substrate.meetingapp.subscriptions — the ONE Graph subscription that makes opting in work.

`appCatalogs/teamsApps/{catalog id}/installedToOnlineMeetings/getAllRecordings`, by resource-specific
consent: every meeting the app is added to, and no other. Owned by the MEETING APP's identity, never
the tenant-wide reader — that identity is the whole bound. Kept short-lived (under an hour needs no
lifecycle endpoint) and renewed on a timer; a lapsed one is simply created again.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/meetingapp/test_subscriptions.py"""
import json
from datetime import datetime, timedelta, timezone

from fixtures.graph import FakeSleep, FakeTokens, FakeTransport
from lab.substrate.mcp.graph.graph_rest import GraphClient
from lab.substrate.meetingapp import subscriptions

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
CATALOG, BASE, STATE = "2f2be8d5-56d2-4788-8e4a-0e7855cc40b2", "https://app.example", "s3cret"
RESOURCE = subscriptions.resource(CATALOG)


def keep(transport):
    client = GraphClient(FakeTokens("app-token", ()), transport=transport, sleep=FakeSleep(), now=lambda: 0.0)
    return subscriptions.ensure(client, catalog_id=CATALOG, base_url=BASE, client_state=STATE, now=lambda: NOW)


def sub(expires, url=f"{BASE}/graph/notifications", resource=RESOURCE):
    return {"id": "sub-1", "resource": resource, "notificationUrl": url,
            "expirationDateTime": expires.strftime("%Y-%m-%dT%H:%M:%SZ")}


def test_with_none_it_creates_the_app_wide_recordings_subscription_by_consent():
    t = FakeTransport().expect("/subscriptions", method="GET", body={"value": []}).expect(
        "/subscriptions", method="POST", body={"id": "new"})
    assert keep(t) == "created"
    body = json.loads(t.calls[-1]["body"])
    assert body["resource"] == (f"appCatalogs/teamsApps/{CATALOG}/installedToOnlineMeetings/getAllRecordings"
                                "?useResourceSpecificConsentBasedAuthorization=true")
    assert body["notificationUrl"] == f"{BASE}/graph/notifications" and body["clientState"] == STATE
    assert body["changeType"] == "created"
    expires = datetime.fromisoformat(body["expirationDateTime"].replace("Z", "+00:00"))
    assert NOW < expires < NOW + timedelta(hours=1), "under an hour: no lifecycle endpoint needed"


def test_one_that_expires_soon_is_renewed_in_place():
    t = FakeTransport().expect("/subscriptions", method="GET", body={"value": [sub(NOW + timedelta(minutes=10))]}
                               ).expect("/subscriptions/sub-1", method="PATCH", body={"id": "sub-1"})
    assert keep(t) == "renewed"
    assert t.calls[-1]["method"] == "PATCH"


def test_one_with_time_left_is_left_alone():
    t = FakeTransport().expect("/subscriptions", method="GET", body={"value": [sub(NOW + timedelta(minutes=50))]})
    assert keep(t) == "current" and len(t.calls) == 1


def test_another_deployments_subscription_is_not_mistaken_for_ours():
    """dev and prod are different apps, but a stale subscription pointing at an old host must not
    count — notifications would go somewhere nobody listens."""
    t = FakeTransport().expect("/subscriptions", method="GET",
                               body={"value": [sub(NOW + timedelta(minutes=50), url="https://old.example/graph/notifications")]}
                               ).expect("/subscriptions", method="POST", body={"id": "new"})
    assert keep(t) == "created"
