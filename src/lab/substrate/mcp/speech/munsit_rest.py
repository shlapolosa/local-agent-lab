"""HTTP transport for the Munsit speech provider. Its credential and wire format live here only.

The generic plumbing — transport injection, multipart, the decoded body, the provider error — is
shared with every other speech provider in `http.py`. What stays here is what only this provider
decides: two wire details that each cost a failed probe when they were guessed rather than read, so
they are pinned in one place — the path prefix is `/api/v1`, and auth is the provider's own key
header, `x-api-key`; a bearer token is rejected.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lab.substrate.mcp.speech.http import (TIMEOUT, HttpClient, ProviderError, Response,
                                           UrllibTransport, multipart, retry_after)

__all__ = ["BASE_URL", "MunsitError", "Response", "UrllibTransport", "MunsitClient", "multipart",
           "TRANSCRIBE", "DIARIZE", "TIMEOUT"]

BASE_URL = "https://api.munsit.com/api/v1"
TRANSCRIBE = "/audio/transcribe"
DIARIZE = "/audio/diarization/transcribe"

MunsitError = ProviderError          # this provider adds no failure mode of its own


class MunsitClient(HttpClient):
    """One Munsit endpoint, with the credential."""

    BASE_URL = BASE_URL

    def auth_headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key}

    def error_from(self, status: int, body: Any, headers: Mapping[str, str]) -> ProviderError:
        env = body if isinstance(body, dict) else {}
        return ProviderError(status, env.get("errorCode", ""),
                             str(env.get("errorMessage") or env.get("message") or ""),
                             retry_after(headers))

    def post_audio(self, path: str, filename: str, data: bytes,
                   fields: Mapping[str, str]) -> dict[str, Any]:
        body, content_type = multipart(filename, data, fields)
        out = self.call("POST", path, body=body, content_type=content_type)
        return out if isinstance(out, dict) else {}
