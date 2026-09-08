"""HTTP transport for Soniox. Its credential and wire format live here only.

Four wire details, each stated once: auth is a BEARER token; a file is uploaded multipart to
`/v1/files` and answered with an id; a transcription is created from that id at `/v1/transcriptions`
and is ASYNCHRONOUS; and the finished text is fetched from a SEPARATE endpoint,
`/v1/transcriptions/{id}/transcript` — polling the job itself returns status, never tokens.
"""
from __future__ import annotations

from typing import Any

from lab.substrate.mcp.speech.http import HttpClient, multipart, poll_until

__all__ = ["BASE_URL", "FILES", "TRANSCRIPTIONS", "SonioxClient"]

BASE_URL = "https://api.soniox.com"
FILES = "/v1/files"
TRANSCRIPTIONS = "/v1/transcriptions"


class SonioxClient(HttpClient):
    BASE_URL = BASE_URL

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def upload(self, filename: str, data: bytes) -> str:
        body, content_type = multipart(filename, data, {})
        out = self.call("POST", FILES, body=body, content_type=content_type)
        file_id = (out or {}).get("id") if isinstance(out, dict) else ""
        if not file_id:
            raise ValueError("the provider accepted the file but returned no id")
        return str(file_id)

    def transcribe(self, body: dict, *, terminal: set[str], interval: float = 3.0,
                   sleep=None) -> dict[str, Any]:
        """Create, poll to a terminal status, then fetch the tokens from their own endpoint."""
        created = self.post_json(TRANSCRIPTIONS, body)
        job_id = (created or {}).get("id") if isinstance(created, dict) else ""
        if not job_id:
            raise ValueError("the provider accepted the job but returned no id")
        state = poll_until(lambda: self.call("GET", f"{TRANSCRIPTIONS}/{job_id}"),
                           lambda r: isinstance(r, dict) and r.get("status") in terminal,
                           timeout=self.timeout, interval=interval, sleep=sleep)
        if state.get("status") == "error":
            return state
        out = self.call("GET", f"{TRANSCRIPTIONS}/{job_id}/transcript")
        return out if isinstance(out, dict) else {}
