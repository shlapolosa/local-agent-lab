"""A deterministic offline `Embedder`.

Nothing above the adapter should need a live embedding upstream to be tested, and — more to the
point — nothing should need one to be BUILT. The upstream is still an open decision (`.env` names
OCI but the key file is absent), and the whole reason `Embedder` is a port is that the decision
changes one `model_list` entry rather than any code above it.

Hashing gives the two properties the tests actually rely on: the same text always embeds to the
same vector, and different texts differ. It gives no semantic similarity at all, so a test that
asserted "these two sentences rank close together" would be asserting nothing — such a test belongs
in the integration suite against a real model.
"""
from __future__ import annotations

import hashlib
import math
from typing import Sequence

__all__ = ["HashEmbedder"]


class HashEmbedder:
    """`Embedder` over sha256. Deterministic, offline, and honestly not semantic."""

    def __init__(self, *, model: str = "test-embed", dim: int = 8) -> None:
        self.model = model
        self.dim = dim
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def embed(self, texts: Sequence[str], *, purpose: str) -> list[list[float]]:
        self.calls.append((tuple(texts), purpose))
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = [digest[i % len(digest)] / 255.0 for i in range(self.dim)]
        norm = math.sqrt(sum(v * v for v in raw)) or 1.0
        return [v / norm for v in raw]        # unit length, so cosine and dot agree
