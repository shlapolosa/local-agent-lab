"""Shared HTTP plumbing for every speech provider — the parts that are the same whoever answers.

Four providers are wired here for a bake-off, and each one needs the same four things: a stdlib
transport that can be INJECTED so tests run without a socket, a multipart encoder, a decoded body,
and a provider-level error that the repository turns into a typed domain refusal. Written once.

What is NOT here is anything a provider decides for itself: its auth header, its paths, its error
envelope and its polling shape. Those live in each `*_rest.py`, because that is exactly where they
differ and a shared abstraction over them would be a lie with a config flag.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from typing import Any, Callable, NamedTuple

__all__ = ["TIMEOUT", "Response", "ProviderError", "multipart", "UrllibTransport", "json_body",
           "retry_after", "HttpClient"]

TIMEOUT = 900.0                      # an hour of audio is not quick, and some providers are synchronous


class Response(NamedTuple):
    """A transport's answer: status, LOWER-CASED headers, and the decoded JSON body."""

    status: int
    headers: Mapping[str, str]
    body: Any


class ProviderError(RuntimeError):
    """A provider-level failure, before any domain meaning is attached."""

    def __init__(self, status: int, code: int | str = "", message: str = "",
                 retry_after: float | None = None) -> None:
        self.status, self.code, self.message = status, code, message
        self.retry_after = retry_after
        super().__init__(f"speech provider {status} {code or 'error'}: {message}")


def multipart(filename: str, data: bytes, fields: Mapping[str, str],
              file_field: str = "file") -> tuple[bytes, str]:
    """Encode one file plus simple text fields as `multipart/form-data`.

    Hand-rolled rather than pulled from a dependency: it is twenty lines, it keeps the substrate's
    footprint small on an 8 GB machine, and the alternative would add a transitive HTTP stack for
    one request shape. `file_field` varies by provider — the only part of the encoding that does.
    """
    boundary = f"----lab{uuid.uuid4().hex}"
    sep = f"--{boundary}\r\n".encode()
    out = bytearray()
    for key, value in fields.items():
        out += sep
        out += f'Content-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
    out += sep
    out += f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode()
    out += b"Content-Type: application/octet-stream\r\n\r\n"
    out += data
    out += b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def json_body(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8", "replace") or "{}")
    except ValueError:
        return {"errorMessage": raw[:200].decode("utf-8", "replace")}


def retry_after(headers: Mapping[str, str]) -> float | None:
    try:
        return float(headers.get("retry-after"))
    except (TypeError, ValueError):
        return None


class UrllibTransport:
    """The default transport: stdlib only, no third-party HTTP stack in the substrate."""

    def __init__(self, opener=None) -> None:
        self._opener = opener or urllib.request.build_opener()

    def __call__(self, method: str, url: str, headers: Mapping[str, str],
                 body: bytes | None = None, timeout: float | None = None) -> Response:
        req = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
        try:
            with self._opener.open(req, timeout=timeout or TIMEOUT) as r:
                return Response(r.status, {k.lower(): v for k, v in r.headers.items()},
                                json_body(r.read()))
        except urllib.error.HTTPError as e:            # a status, with a body worth reading
            return Response(e.code, {k.lower(): v for k, v in (e.headers or {}).items()},
                            json_body(e.read()))


class HttpClient:
    """One provider endpoint, with the credential. Subclasses supply auth and error meaning.

    `call` is the whole contract: it never returns a failure, it raises one — so no caller can
    forget to check a status, which is the failure mode a returned-error API invites.
    """

    BASE_URL = ""

    def __init__(self, api_key: str = "", base_url: str = "",
                 transport: Callable[..., Response] | None = None, timeout: float = TIMEOUT) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.timeout = timeout
        self._transport = transport or UrllibTransport()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    # -------------------------------------------------------------- what a provider overrides
    def auth_headers(self) -> dict[str, str]:
        """This provider's credential header. Guessing it costs a failed live probe, so it is
        stated once per provider and nowhere else."""
        raise NotImplementedError

    def error_from(self, status: int, body: Any, headers: Mapping[str, str]) -> ProviderError:
        """Read this provider's error envelope. The default reads the shapes most of them use."""
        env = body if isinstance(body, dict) else {}
        detail = env.get("error") if isinstance(env.get("error"), dict) else env
        return ProviderError(status, detail.get("code", detail.get("errorCode", "")),
                             str(detail.get("message") or detail.get("errorMessage")
                                 or detail.get("detail") or env.get("error") or ""),
                             retry_after(headers))

    # -------------------------------------------------------------- the one way out
    def call(self, method: str, path: str, *, body: bytes | None = None,
             content_type: str = "", accept: str = "application/json",
             timeout: float | None = None) -> Any:
        headers = {**self.auth_headers(), "Accept": accept}
        if content_type:
            headers["Content-Type"] = content_type
        if body is not None:
            headers["Content-Length"] = str(len(body))
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        try:
            r = self._transport(method, url, headers, body, timeout or self.timeout)
        except ProviderError:
            raise
        except Exception as e:                          # a transport-level failure is still an answer
            raise ProviderError(0, "transport", str(e)) from e
        if r.status >= 400:
            raise self.error_from(r.status, r.body, r.headers)
        return r.body

    def post_json(self, path: str, payload: dict, **kw) -> Any:
        return self.call("POST", path, body=json.dumps(payload).encode(),
                         content_type="application/json", **kw)


def poll_until(fetch, done, *, timeout: float = TIMEOUT, interval: float = 3.0, sleep=None) -> Any:
    """Poll `fetch()` until `done(result)`, or raise when the budget runs out.

    Two of these providers are asynchronous: submit, then poll. `sleep` is injected so a test of the
    polling itself runs in no time, and the deadline is real — a job that never terminates must fail
    with a sentence rather than hang a workload for the length of its socket timeout.
    """
    import time
    naptime = sleep or time.sleep
    clock = time.monotonic
    deadline = clock() + timeout
    while True:
        result = fetch()
        if done(result):
            return result
        if clock() >= deadline:
            raise ProviderError(0, "timeout",
                                f"the provider did not finish within {timeout:.0f}s")
        naptime(interval)
