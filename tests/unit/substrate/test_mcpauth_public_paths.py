"""A declared public path bypasses the bearer; everything else still needs it."""
import asyncio

from lab.substrate.mcpauth import BearerAuthMiddleware


def _call(mw, path, auth=None):
    sent = []
    scope = {"type": "http", "path": path, "method": "POST", "headers": ([(b"authorization", auth.encode())] if auth else [])}

    async def receive():
        return {"type": "http.request"}

    async def send(msg):
        sent.append(msg)

    asyncio.run(mw(scope, receive, send))
    return sent


def test_public_path_passes_without_a_bearer():
    hit = []

    async def app(scope, receive, send):
        hit.append(scope["path"])

    mw = BearerAuthMiddleware(app, secret="shh", public_paths=("/notifications",))
    assert _call(mw, "/notifications") == [] and hit == ["/notifications"]
    sent = _call(mw, "/mcp")
    assert sent and sent[0]["status"] == 401 and hit == ["/notifications"]
    _call(mw, "/mcp", auth="Bearer shh")
    assert hit == ["/notifications", "/mcp"]
    assert _call(mw, "/notifications/extra") and hit[-1] == "/mcp", "exact paths only"
