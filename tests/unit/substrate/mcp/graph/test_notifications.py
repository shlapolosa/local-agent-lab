"""graph-mcp's inbound door: the validation handshake, the client-state check, and one event per resource."""
import json

from starlette.testclient import TestClient

from fixtures.fakes import FakeRedis
from fixtures.graph import FakeGraph
from lab.core.collab import DriveItem
from lab.platform import config, fabric_events
from lab.platform.contracts import ArtifactChanged
from lab.substrate import mcpserver
from lab.substrate.mcp.graph import notifications as notif
from lab.substrate.mcp.graph import server as srv

ITEM = DriveItem(id="item-1", name="ADR-014.docx", drive_id="drive-1", modified="2026-09-11T08:10:31Z", parent="folder-1")


def _graph():
    g = FakeGraph()
    g.items_by_id = {"item-1": ITEM}
    g.item = lambda handle: ITEM if handle.id == "item-1" else (_ for _ in ()).throw(KeyError(handle.id))
    return g


def _app(secret="shh"):
    return mcpserver.app_for(srv.server.mcp, routes=[notif.route_for(srv.server)], public_paths=(notif.PATH,))


def test_validation_handshake_echoes_the_token_without_a_bearer(monkeypatch):
    monkeypatch.setattr(config, "MCP_SHARED_SECRET", "shh")
    with TestClient(_app()) as c:
        r = c.post(notif.PATH + "?validationToken=abc%20123")
        assert r.status_code == 200 and r.text == "abc 123" and r.headers["content-type"].startswith("text/plain")
        assert c.get("/mcp").status_code == 401, "the MCP path itself still needs the bearer"


def test_a_batch_with_the_right_client_state_publishes_one_event_per_item(monkeypatch):
    monkeypatch.setattr(config, "MCP_SHARED_SECRET", "shh")
    monkeypatch.setattr(config, "FABRIC_NOTIFY_CLIENT_STATE", "s3cret")
    r = FakeRedis()
    with srv.server.container.collab.override(_graph()), srv.server.container.redis.override(r), TestClient(_app()) as c:
        body = {"value": [{"subscriptionId": "sub", "clientState": "s3cret", "changeType": "updated",
                           "resource": "drives/drive-1/items/item-1", "resourceData": {"lastModifiedBy": {"user": {"id": "oid-9"}}}},
                          {"subscriptionId": "sub", "clientState": "s3cret", "changeType": "updated", "resource": "users/x/mailFolders"}]}
        resp = c.post(notif.PATH, json=body)
        assert resp.status_code == 202 and resp.json() == {"accepted": 1}
    got = fabric_events.events(client=r)
    assert len(got) == 1
    e = ArtifactChanged.from_fields(got[0][1])
    assert e.pointer == {"source": "collab", "handle": "collab://item/drive-1/item-1", "version": "2026-09-11T08:10:31Z"}
    assert e.actor_oid == "oid-9" and e.change == "updated" and not e.is_fabric_originated


def test_a_wrong_or_missing_client_state_publishes_nothing(monkeypatch):
    monkeypatch.setattr(config, "MCP_SHARED_SECRET", "shh")
    monkeypatch.setattr(config, "FABRIC_NOTIFY_CLIENT_STATE", "s3cret")
    r = FakeRedis()
    with srv.server.container.collab.override(_graph()), srv.server.container.redis.override(r), TestClient(_app()) as c:
        resp = c.post(notif.PATH, json={"value": [{"clientState": "wrong", "resource": "drives/drive-1/items/item-1"}]})
        assert resp.status_code == 202 and resp.json()["accepted"] == 0
        assert c.post(notif.PATH, content=b"not json", headers={"content-type": "application/json"}).status_code == 400
        assert c.get(notif.PATH).status_code == 405
    assert r.xlen(fabric_events.STREAM) == 0
    monkeypatch.setattr(config, "FABRIC_NOTIFY_CLIENT_STATE", "")
    assert notif.handle_batch({"value": [{"clientState": "", "resource": "drives/d/items/i"}]}, client_state="", collab=_graph(), redis=r)["accepted"] == 0


def test_a_deleted_item_is_still_an_event():
    e = notif.event_from_notification({"changeType": "deleted", "resource": "drives/drive-1/items/gone"}, collab=_graph(), now="2026-09-11T10:00:00Z")
    assert e.change == "deleted" and "version" not in e.pointer and e.occurred_at == "2026-09-11T10:00:00Z"
