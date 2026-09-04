"""HTTP transport for the speech provider. Credentials and wire format live here and nowhere else.

The transport is INJECTED (`transport=`), the same seam `graph_rest` uses, so every test above this
runs offline without a socket. This module knows the provider's auth header, its multipart shape and
its error envelope; it knows nothing about the domain, and it raises its own error type which the
repository translates into the domain's typed refusals.

Two wire details cost a failed probe when they were guessed rather than read, so they are pinned in
one place: the path prefix is `/api/v1`, and auth is the provider's own key header — a bearer token
is rejected.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from typing import Any, Callable, NamedTuple

__all__ = ["BASE_URL", "MunsitError", "Response", "UrllibTransport", "MunsitClient", "multipart",
           "TRANSCRIBE", "DIARIZE"]

BASE_URL = "https://api.munsit.com/api/v1"
TRANSCRIBE = "/audio/transcribe"
DIARIZE = "/audio/diarization/transcribe"
TIMEOUT = 900.0                      # transcription is synchronous and an hour of audio is not quick


class Response(NamedTuple):
    """A transport's answer: status, LOWER-CASED headers, and the decoded JSON body."""

    status: int
    headers: Mapping[str, str]
    body: Any


class MunsitError(RuntimeError):
    """A provider-level failure, before any domain meaning is attached."""

    def __init__(self, status: int, code: int | str = "", message: str = "",
                 retry_after: float | None = None) -> None:
        self.status, self.code, self.message = status, code, message
        self.retry_after = retry_after
        super().__init__(f"speech provider {status} {code or 'error'}: {message}")


def multipart(filename: str, data: bytes, fields: Mapping[str, str]) -> tuple[bytes, str]:
    """Encode one file plus simple text fields as `multipart/form-data`.

    Hand-rolled rather than pulled from a dependency: it is twenty lines, it keeps the substrate's
    footprint small on an 8 GB machine, and the alternative would add a transitive HTTP stack for
    one request shape.
    """
    boundary = f"----lab{uuid.uuid4().hex}"
    sep = f"--{boundary}\r\n".encode()
    out = bytearray()
    for key, value in fields.items():
        out += sep
        out += f'Content-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
    out += sep
    out += f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
    out += b"Content-Type: application/octet-stream\r\n\r\n"
    out += data
    out += b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


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
                                _json(r.read()))
        except urllib.error.HTTPError as e:            # a status, with a body worth reading
            return Response(e.code, {k.lower(): v for k, v in (e.headers or {}).items()},
                            _json(e.read()))


def _json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8", "replace") or "{}")
    except ValueError:
        return {"errorMessage": raw[:200].decode("utf-8", "replace")}


class MunsitClient:
    """One provider endpoint, with the credential. Returns the decoded body or raises `MunsitError`."""

    def __init__(self, api_key: str = "", base_url: str = BASE_URL,
                 transport: Callable[..., Response] | None = None, timeout: float = TIMEOUT) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or BASE_URL).rstrip("/")
        self.timeout = timeout
        self._transport = transport or UrllibTransport()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def post_audio(self, path: str, filename: str, data: bytes,
                   fields: Mapping[str, str]) -> dict[str, Any]:
        body, content_type = multipart(filename, data, fields)
        headers = {"x-api-key": self.api_key, "Content-Type": content_type,
                   "Content-Length": str(len(body))}
        try:
            r = self._transport("POST", f"{self.base_url}{path}", headers, body, self.timeout)
        except MunsitError:
            raise
        except Exception as e:                          # a transport-level failure is still an answer
            raise MunsitError(0, "transport", str(e)) from e
        if r.status >= 400:
            envelope = r.body if isinstance(r.body, dict) else {}
            raise MunsitError(r.status, envelope.get("errorCode", ""),
                              str(envelope.get("errorMessage") or envelope.get("message") or ""),
                              _retry_after(r.headers))
        return r.body if isinstance(r.body, dict) else {}


def _retry_after(headers: Mapping[str, str]) -> float | None:
    try:
        return float(headers.get("retry-after"))
    except (TypeError, ValueError):
        return None
