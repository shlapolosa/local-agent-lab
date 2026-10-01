"""`HttpEmbedder` — the `SpeakerEmbedder` port, as speech-mcp reaches the voiceprint service.

A failure to reach the model is a TYPED refusal (`SpeechUnavailable("voiceprints", ...)`) naming the
setting, never a stack trace: identifying a voice is a convenience, and every caller of it degrades to
"no suggestion" rather than failing the meeting.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Callable, Sequence

from lab.core.speech import SpeechUnavailable

CAPABILITY = "voiceprints"
SETTING = "VOICEPRINT_URL"


class HttpEmbedder:
    # BELOW the gateway's MCP tool timeout (300 s): a slow model must surface as this adapter's
    # sentence, not as the gateway abandoning the call and the caller hanging on a closed stream —
    # which is exactly what a 300 s timeout here produced on 1 Oct 2026.
    def __init__(self, url: str, secret: str = "", *, timeout: float = 240.0,
                 opener: Callable = urllib.request.urlopen) -> None:
        self.url, self._secret, self._timeout, self._open = (url or "").rstrip("/"), secret or "", timeout, opener
        self.model = ""                  # learned from the service's answer: it, not the caller, knows

    def embed(self, clips: Sequence[bytes]) -> list[tuple[float, ...]]:
        if not self.url:
            raise SpeechUnavailable(CAPABILITY, "no voiceprint service is configured", f"set {SETTING}")
        if not clips:
            return []
        body = json.dumps({"clips": [base64.b64encode(c).decode() for c in clips]}).encode()
        headers = {"Content-Type": "application/json"}
        if self._secret:
            headers["Authorization"] = f"Bearer {self._secret}"
        req = urllib.request.Request(f"{self.url}/embed", data=body, headers=headers, method="POST")
        try:
            with self._open(req, timeout=self._timeout) as r:
                got = json.load(r)
        except urllib.error.HTTPError as e:
            raise SpeechUnavailable(CAPABILITY, f"the voiceprint service refused the clips (HTTP {e.code})",
                                    "check the service log; clips must be 16 kHz mono WAV") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise SpeechUnavailable(CAPABILITY, f"the voiceprint service at {self.url} did not answer ({e})",
                                    f"start it, or check {SETTING}") from e
        vectors = [tuple(float(x) for x in v) for v in got.get("vectors") or []]
        if len(vectors) != len(clips):
            raise SpeechUnavailable(CAPABILITY, f"asked for {len(clips)} vectors and got {len(vectors)}")
        self.model = str(got.get("model") or "")
        return vectors
