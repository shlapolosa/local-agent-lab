"""lab.substrate.meetingapp.service — the translation layer's two testable pieces.

The SDK wiring itself is exercised in Teams; what is pinned here is the workaround that made the
organiser's view loadable at all, and the Graph route's handshake and hand-off.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/meetingapp/test_service.py"""
import asyncio
import json

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from lab.substrate.meetingapp import service


def echo_app():
    inner = FastAPI()

    @inner.post("/api/messages")
    async def messages(request: Request):
        return {"body": await request.json(), "auth": request.headers.get("authorization")}

    @inner.post("/other")
    async def other(request: Request):
        return await request.json()
    inner.add_middleware(service.AutomaticRefresh)
    return TestClient(inner)


def test_an_automatic_refresh_reaches_the_sdk_without_the_field_it_cannot_parse():
    got = echo_app().post("/api/messages", headers={"Authorization": "Bearer jwt"},
                          content=json.dumps({"type": "invoke", "value": {"trigger": "automatic",
                                                                          "action": {"verb": "refresh"}}})).json()
    assert got["body"]["value"] == {"action": {"verb": "refresh"}}
    assert got["auth"] == "Bearer jwt", "authentication is never touched"


def test_a_manual_action_and_any_other_route_pass_through_unchanged():
    client = echo_app()
    manual = {"type": "invoke", "value": {"trigger": "manual", "action": {"verb": "submit"}}}
    assert client.post("/api/messages", content=json.dumps(manual)).json()["body"] == manual
    other = {"value": {"trigger": "automatic"}}
    assert client.post("/other", content=json.dumps(other)).json() == other


def test_the_graph_route_echoes_the_validation_token_as_plain_text():
    client = TestClient(service.web(client_state="s"))
    r = client.post("/graph/notifications?validationToken=abc%20123")
    assert r.status_code == 200 and r.text == "abc 123" and r.headers["content-type"].startswith("text/plain")


def test_a_notification_is_answered_at_once_and_handled_with_the_configured_secret():
    seen = []
    client = TestClient(service.web(client_state="s3cret", handle=lambda body, **kw: seen.append((body, kw))))
    r = client.post("/graph/notifications", json={"value": [{"resource": "x"}]})
    assert r.status_code == 202
    for _ in range(50):                             # handled off the event loop
        if seen:
            break
        asyncio.run(asyncio.sleep(0.01))
    assert seen == [({"value": [{"resource": "x"}]}, {"client_state": "s3cret"})]
    assert client.post("/graph/notifications", content=b"{").status_code == 400
    assert client.get("/healthz").json() == {"ok": True}
