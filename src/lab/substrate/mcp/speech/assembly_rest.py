"""HTTP transport for AssemblyAI. Its credential and wire format live here only.

Three wire details, each stated once: auth is the raw key in `authorization` with NO `Bearer`
prefix; audio is uploaded as RAW BYTES to `/v2/upload` (not multipart) and answered with an
`upload_url` that only this account can read; and transcription is asynchronous, so a submit is
followed by polling `/v2/transcript/{id}` until the status is terminal.
"""
from __future__ import annotations

from typing import Any

from lab.substrate.mcp.speech.http import HttpClient, poll_until

__all__ = ["BASE_URL", "UPLOAD", "TRANSCRIPT", "AssemblyClient"]

BASE_URL = "https://api.assemblyai.com"
UPLOAD = "/v2/upload"
TRANSCRIPT = "/v2/transcript"


class AssemblyClient(HttpClient):
    BASE_URL = BASE_URL

    def auth_headers(self) -> dict[str, str]:
        return {"authorization": self.api_key}

    def upload(self, data: bytes) -> str:
        out = self.call("POST", UPLOAD, body=data, content_type="application/octet-stream")
        url = (out or {}).get("upload_url") if isinstance(out, dict) else ""
        if not url:
            raise ValueError("the provider accepted the upload but returned no url")
        return str(url)

    def transcribe(self, body: dict, *, terminal: set[str], interval: float = 3.0,
                   sleep=None) -> dict[str, Any]:
        """Submit, then poll to a terminal status. Returns the completed transcript object."""
        created = self.post_json(TRANSCRIPT, body)
        job_id = (created or {}).get("id") if isinstance(created, dict) else ""
        if not job_id:
            raise ValueError("the provider accepted the job but returned no id")
        return poll_until(lambda: self.call("GET", f"{TRANSCRIPT}/{job_id}"),
                          lambda r: isinstance(r, dict) and r.get("status") in terminal,
                          timeout=self.timeout, interval=interval, sleep=sleep)
