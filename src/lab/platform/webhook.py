"""The lab's outbound JSON calls — one POST, one GET — over the standard library.

CLAUDE.md states an exception to gateway-only egress: a channel — and now the meeting notifier —
posts DIRECTLY to a fixed configured URL, carrying counts, ids and links and no model content. An
exception with more than one instance needs one implementation, or the next thing added to the list
will differ from the others by accident rather than by decision.

It is also where the Azure move lands. If outbound notification ever goes behind APIM, an Event Grid
topic or a Service Bus queue, that is this function and nothing else — three call sites would each
have had to be found.

Deliberately thin: no retry, no back-off, no queue. Every caller already has a policy for a failed
send (a channel leaves the stream entry unacked; the notifier logs and moves on), and a retry hidden
in here would silently take that decision away from them.
"""
from __future__ import annotations

import json
import urllib.request

TIMEOUT_S = 30


def post_json(url: str, payload: dict, *, headers: dict | None = None,
              timeout: int = TIMEOUT_S) -> str:
    """POST `payload` as JSON and return the response body as text. Raises on a transport or HTTP
    error, so the caller decides what a failed send means.

    `headers` are merged over the defaults, for callers that must authenticate — the gateway
    embeddings call carries a virtual key. A channel passes none: its URL IS its credential, which
    is exactly why a webhook URL is treated as a secret."""
    # `application/json` bare, not with `; charset=utf-8`: JSON is UTF-8 by definition (RFC 8259)
    # and this is the header the live Teams Workflows webhook has been verified against. The body is
    # still UTF-8 encoded — `json.dumps` escapes non-ASCII by default, so Arabic survives either way.
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def get_json(url: str, *, headers: dict | None = None, timeout: int = TIMEOUT_S) -> str:
    """GET and return the body as text. The same thinness as `post_json`: the caller owns what a
    failure means. Exists for the one read a workload makes that is not a tool call — asking the
    gateway which relevance stores it registers, before a run spends anything."""
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json",
                                                             **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()
