"""HTTP transport for ElevenLabs Scribe. Its credential and wire format live here only.

Two wire details, each stated once so no caller guesses: auth is the `xi-api-key` header (not a
bearer token), and the audio field of the multipart body is named `file`.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lab.substrate.mcp.speech.http import HttpClient, multipart

__all__ = ["BASE_URL", "TRANSCRIBE", "ElevenClient"]

BASE_URL = "https://api.elevenlabs.io"
TRANSCRIBE = "/v1/speech-to-text"


class ElevenClient(HttpClient):
    BASE_URL = BASE_URL

    def auth_headers(self) -> dict[str, str]:
        return {"xi-api-key": self.api_key}

    def post_audio(self, path: str, filename: str, data: bytes,
                   fields: Mapping[str, str]) -> dict[str, Any]:
        body, content_type = multipart(filename, data, fields)
        out = self.call("POST", path, body=body, content_type=content_type)
        return out if isinstance(out, dict) else {}
