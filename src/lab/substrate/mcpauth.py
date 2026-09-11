"""Bearer-token gate for the lab's MCP servers. On one machine the servers hid behind loopback;
across hosts the gateway must prove itself. MCP_SHARED_SECRET set -> every request needs
`Authorization: Bearer <secret>` (LiteLLM sends it via auth_type=bearer_token); unset -> open,
which is only acceptable when BIND_HOST is 127.0.0.1.
"""
import hashlib

from lab.platform import config


def fingerprint(value: str) -> str:
    """Short, non-reversible identifier for a credential in logs (never the credential itself)."""
    return hashlib.sha256(value.encode()).hexdigest()[:8]


class BearerAuthMiddleware:
    """`public_paths` are the few routes a THIRD PARTY calls without our secret — a provider's
    change-notification callback — and they must prove themselves another way (a client state the
    route checks). Exact paths only, declared by the server that owns them: an exemption is a hole,
    and a hole you cannot list is one you cannot audit."""

    def __init__(self, app, secret=None, public_paths=()):
        self.app, self.secret = app, (secret or config.MCP_SHARED_SECRET)
        self.public_paths = frozenset(public_paths)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.secret or scope.get("path") in self.public_paths:
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        if headers.get("authorization", "") == f"Bearer {self.secret}":
            return await self.app(scope, receive, send)
        got = headers.get("authorization", "<none>")
        print(f"mcpauth DENY {scope.get('method')} {scope.get('path')} "
              f"auth=sha256:{fingerprint(got)} len={len(got)}", flush=True)
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b"Bearer")]})
        await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
