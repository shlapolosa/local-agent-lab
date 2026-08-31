"""Bearer-token gate for the lab's MCP servers. On one machine the servers hid behind loopback;
across hosts the gateway must prove itself. MCP_SHARED_SECRET set -> every request needs
`Authorization: Bearer <secret>` (LiteLLM sends it via auth_type=bearer_token); unset -> open,
which is only acceptable when BIND_HOST is 127.0.0.1.
"""
from . import config


class BearerAuthMiddleware:
    def __init__(self, app, secret=None):
        self.app, self.secret = app, (secret or config.MCP_SHARED_SECRET)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.secret:
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        if headers.get("authorization", "") == f"Bearer {self.secret}":
            return await self.app(scope, receive, send)
        got = headers.get("authorization", "<none>")
        print(f"mcpauth DENY {scope.get('method')} {scope.get('path')} auth={got[:24]}…len{len(got)}", flush=True)
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
        await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
