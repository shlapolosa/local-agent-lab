"""HTTP transport for Microsoft Graph — everything about the wire, nothing about the domain.

It mirrors `mcp/adoit/adoit_rest.py` (a thin `_request`/`get` facade over urllib, no SDK) and adds
the four things Graph makes unavoidable:

* **Paging.** A collection answers with `value` plus an `@odata.nextLink`; the link is handed back as
  an opaque CURSOR and is only followed again after being checked to point at Graph itself, because
  a cursor makes a round trip through an agent and comes back as caller input.
* **Throttling.** Graph answers 429 (and 503) with `Retry-After`, in SECONDS or as an HTTP-date. Both
  are honoured, the wait is INJECTED (`sleep=`) so tests assert it instead of enduring it, the delay
  is capped so a hostile header cannot hang a run, and retries are bounded.
* **The redirect that leaks a bearer token.** `GET /drives/{d}/items/{i}/content` answers 302 with a
  pre-authenticated Azure Blob URL — Microsoft documents that no Authorization header is needed there
  — but `urllib`'s default redirect handler copies every header except the content ones onto the new
  request, so the token would travel to a CDN under someone else's control. `AuthStrippingRedirectHandler`
  removes it on the hop; that is the single reason this module builds its own opener.
* **Streaming.** `stream()` returns the response BODY UNREAD, so a meeting recording goes straight
  into `Store.put_stream` without ever being materialised. The SIZE CEILING is not applied here: the
  repository applies it, because only the repository knows which capability was attempted and can
  therefore say which one is unavailable. The mid-stream ceiling (for an absent or lying length) is
  the store's `_CappedReader`, which already enforces it on every backend — one home, not two.

Failures leave here as `GraphError`: status, Graph's error code, its message and any inner code —
including the ones with no response at all (DNS, TLS, a proxy, a timeout), which get status 0. What
that MEANS — a missing consent, a missing Teams policy, an unlicensed tenant — is `graph_probe`'s
job, because only the caller knows which capability it was attempting.
"""
from __future__ import annotations

import email.utils
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import BinaryIO, Callable, Mapping, NamedTuple

from lab.core.collab import clamp_limit
from lab.platform import config

__all__ = ["GraphError", "Response", "Content", "AuthStrippingRedirectHandler", "UrllibTransport",
           "GraphClient", "RETRY_STATUS", "MAX_RETRY_DELAY"]

RETRY_STATUS = (429, 503)          # Graph's two "come back later" answers
MAX_RETRY_DELAY = 60.0             # a Retry-After is a hint, not an instruction to hang the run
_TAGS = re.compile(r"<[^>]+>")


def _int(value) -> int:
    """A header's byte count, or 0 when there isn't one — a `/content` response is served by a CDN
    after the redirect, and a size that cannot be read must not become a traceback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class GraphError(RuntimeError):
    """One refused Graph call, as the wire described it. Deliberately NOT a `CollabError`: the
    transport does not know which capability was attempted, so it cannot write the sentence."""

    def __init__(self, status: int, code: str = "", message: str = "", inner_code: str = "",
                 retry_after: float | None = None) -> None:
        self.status, self.code, self.message = status, code, message
        self.inner_code, self.retry_after = inner_code, retry_after
        super().__init__(f"Microsoft Graph {status} {code or 'error'}: {message}")

    @property
    def detail(self) -> str:
        """Message plus the inner code — sometimes the only real diagnosis (a `Forbidden` whose
        inner code is `GraphAccessToTranscriptsDisabled` is a tenant switch, not a grant)."""
        return f"{self.message} ({self.inner_code})" if self.inner_code else self.message


class Response(NamedTuple):
    """A transport's answer: the status, LOWER-CASED headers, and the body as a file-like that has
    not been read — so one seam carries both a JSON reply and a gigabyte of video."""

    status: int
    headers: Mapping[str, str]
    body: BinaryIO


class Content(NamedTuple):
    """Streamed content: the unread body, its media type, and its declared size (0 = unknown)."""

    fileobj: BinaryIO
    content_type: str
    size: int


class AuthStrippingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects WITHOUT the Authorization header.

    urllib's own handler drops only `Content-Length`/`Content-Type` when it rebuilds the request, so
    a bearer minted for `graph.microsoft.com` would be sent to whatever host Graph redirects to — for
    `/content` that is a pre-authenticated `*.blob.core.windows.net` URL that needs no credential at
    all. The base class still decides WHETHER to follow; this only edits the headers it produced."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            for store in (new.headers, new.unredirected_hdrs):
                for key in [k for k in store if k.lower() == "authorization"]:
                    del store[key]
        return new


class UrllibTransport:
    """The real transport: stdlib only, one opener carrying the redirect handler above.

    An HTTP error status is RETURNED as a `Response` rather than raised, so the client has exactly
    one shape to reason about — `urllib.error.HTTPError` is itself a readable response object, which
    is what makes that honest rather than a trick. Being UNABLE TO REACH Graph is different in kind
    (there is no response at all) and is raised as a `GraphError` with status 0, so the one failure
    type still covers every way a call can fail."""

    def __init__(self, opener=None) -> None:
        self.opener = opener or urllib.request.build_opener(AuthStrippingRedirectHandler())

    def __call__(self, method: str, url: str, headers: Mapping[str, str], body: bytes | None = None,
                 timeout: float = 30.0) -> Response:
        req = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
        try:
            resp = self.opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:                 # an error response IS a response
            resp = e
        except (urllib.error.URLError, OSError) as e:
            # NOT an HTTPError (which is a subclass of URLError, not the reverse): Graph was never
            # reached. Status 0 is the one shape the repository already explains, so an unreachable
            # provider becomes a sentence like every other refusal instead of a urllib traceback.
            raise GraphError(0, "Unreachable",
                             f"Microsoft Graph could not be reached: {e}") from e
        return Response(getattr(resp, "status", None) or resp.getcode(),
                        {k.lower(): v for k, v in resp.headers.items()}, resp)


class GraphClient:
    """Graph over one injected transport. `tokens` is a `graph_auth.TokenSource`; `sleep` and `now`
    are injected so throttling is deterministic in tests; `max_fetch_bytes` defaults to the
    deployment's ceiling but enters through the constructor, never read from the environment here."""

    def __init__(self, tokens, base_url: str = "", transport: Callable[..., Response] | None = None,
                 sleep: Callable[[float], None] = time.sleep, now: Callable[[], float] = time.time,
                 timeout: float = 30.0, max_retries: int = 3) -> None:
        self.tokens = tokens
        self.base_url = (base_url or config.GRAPH_BASE_URL).rstrip("/")
        self.transport = transport or UrllibTransport()
        self.sleep, self._now = sleep, now
        self.timeout, self.max_retries = timeout, max_retries

    # ------------------------------------------------------------------ verbs
    def get(self, path: str, params: Mapping[str, object] | None = None) -> dict:
        return self._json(self._request("GET", self._url(path, params)))

    def post(self, path: str, body: Mapping[str, object]) -> dict:
        return self._json(self._request("POST", self._url(path), body))

    def patch(self, path: str, body: Mapping[str, object]) -> dict:
        return self._json(self._request("PATCH", self._url(path), body))

    def delete(self, path: str) -> dict:
        return self._json(self._request("DELETE", self._url(path)))

    def paged(self, path: str, params: Mapping[str, object] | None = None, cursor: str | None = None,
              limit: int | None = None) -> tuple[list[dict], str | None]:
        """One page: the raw items and the next cursor (`None` on the last page). `limit` is clamped
        through the DOMAIN's one page-size policy, so no adapter invents its own cap."""
        if cursor:
            if not str(cursor).startswith(self.base_url):
                raise ValueError(f"a cursor must be a Microsoft Graph link under {self.base_url}: {cursor!r}")
            url = cursor
        else:
            url = self._url(path, {**dict(params or {}), "$top": clamp_limit(limit)})
        data = self._json(self._request("GET", url))
        value = data.get("value")
        items = value if isinstance(value, list) else [data]
        return items, data.get("@odata.nextLink")

    def stream(self, path: str, params: Mapping[str, object] | None = None) -> Content:
        """The body, UNREAD — for `Store.put_stream`. The declared size travels with it so the
        caller can refuse an over-large object before a byte moves."""
        resp = self._request("GET", self._url(path, params))
        return Content(resp.body, resp.headers.get("content-type", "application/octet-stream"),
                       _int(resp.headers.get("content-length")))

    # ------------------------------------------------------------------ plumbing
    def _url(self, path: str, params: Mapping[str, object] | None = None) -> str:
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v not in (None, "")},
                                       quote_via=urllib.parse.quote)
        return f"{url}{'&' if '?' in url else '?'}{query}" if query else url

    def _headers(self, has_body: bool) -> dict:
        headers = {"Authorization": f"Bearer {self.tokens.token()}", "Accept": "application/json"}
        if has_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _request(self, method: str, url: str, body: Mapping[str, object] | None = None) -> Response:
        raw = json.dumps(body).encode() if body is not None else None
        for attempt in range(self.max_retries + 1):
            resp = self.transport(method, url, self._headers(raw is not None), raw, self.timeout)
            if resp.status not in RETRY_STATUS or attempt == self.max_retries:
                break
            delay = self._delay(resp.headers, attempt)
            resp.body.close()                 # the retried answer is abandoned: do not leak its socket
            self.sleep(delay)
        if resp.status >= 400:
            raise self._error(resp)
        return resp

    def _delay(self, headers: Mapping[str, str], attempt: int) -> float:
        """`Retry-After` as seconds or as an HTTP-date; exponential back-off when it says nothing or
        says nonsense; never longer than `MAX_RETRY_DELAY`."""
        hint = self._retry_after(headers)
        return min(hint if hint and hint > 0 else 2.0 ** attempt, MAX_RETRY_DELAY)

    def _retry_after(self, headers: Mapping[str, str]) -> float | None:
        value = (headers.get("retry-after") or "").strip()
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            pass
        try:
            return email.utils.parsedate_to_datetime(value).timestamp() - self._now()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _json(resp: Response) -> dict:
        """The parsed body, or `{}` for an empty (204) one. A 200 that is not JSON is a GATEWAY
        answering, not Graph — the same lesson `adoit_rest` learned from a CE edge serving an HTML
        block page — so it becomes a `GraphError` the caller can explain, never a JSONDecodeError."""
        raw = resp.body.read().strip()
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            text = " ".join(_TAGS.sub(" ", raw.decode(errors="replace")).split())[:200]
            raise GraphError(resp.status, "NonJsonResponse",
                             f"the response is not JSON — something between the lab and Microsoft "
                             f"Graph answered instead: {text!r}") from None

    def _error(self, resp: Response) -> GraphError:
        raw = resp.body.read().decode(errors="replace").strip()
        try:
            err = json.loads(raw).get("error") or {}
            message, code = str(err.get("message") or raw[:200]), str(err.get("code") or "")
            inner = str((err.get("innerError") or {}).get("code") or "")
        except ValueError:                                   # an edge or proxy answering HTML
            message, code, inner = " ".join(_TAGS.sub(" ", raw).split())[:200], "", ""
        return GraphError(resp.status, code, message, inner, self._retry_after(resp.headers))
