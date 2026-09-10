"""The embedding port — an infrastructure port, so it lives here rather than in the domain.

It has no domain meaning: `(base_url, credential)` plus a model name is the shape CLAUDE.md already
calls "already satisfied by the gateway", and it is the same shape every other model call in this
lab uses. The reference layer therefore holds a VIRTUAL KEY and never an upstream credential —
which is what keeps "which embedding upstream" a configuration question (one `model_list` entry,
one `.env` line) rather than a code one, and why an unresolved upstream never blocked building
anything above it.

Everything defensive here is about not MIS-ATTRIBUTING a vector. A batch is positional: the caller
zips the vectors back onto its own rows, so a response that is short, long, reordered or of the
wrong width does not fail loudly on its own — it attaches the wrong text to the wrong vector and
retrieval is quietly, permanently wrong. Every one of those is a refusal.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Protocol, Sequence, runtime_checkable

from lab.platform.webhook import post_json

__all__ = ["DEFAULT_BATCH", "EmbedError", "Embedder", "GatewayEmbedder", "PURPOSES"]

#: Asymmetric models want to know which side of the comparison they are embedding. Sending both as
#: the same kind costs recall in a way that looks like a bad corpus rather than a bad call.
PURPOSES = {"document": "search_document", "query": "search_query"}

#: Texts per call, and how long one call may take. Measured 10 Sep 2026 against the substrate's
#: own CPU embedder: a 64-text batch of capability rows outran the 60 s default and the publish
#: died on `TimeoutError` a thousand rows in. Smaller batches, and a timeout sized for a model
#: that runs without a GPU — an index build is an operator step, and waiting is the right answer.
DEFAULT_BATCH = 32
DEFAULT_TIMEOUT_S = 300


class EmbedError(RuntimeError):
    """The embedder did not return vectors we would attach to anything."""


@runtime_checkable
class Embedder(Protocol):
    """Text in, vectors out — one vector per input, in the caller's order."""

    model: str
    dim: int

    def embed(self, texts: Sequence[str], *, purpose: str) -> list[list[float]]:
        ...


def _http(url: str, payload: dict, headers: dict | None = None, timeout: int | None = None) -> str:
    return post_json(url, payload, headers=headers, timeout=timeout or 60)


class GatewayEmbedder:
    """Embeds through the lab gateway's `/v1/embeddings`, authenticated with a virtual key."""

    def __init__(self, *, base_url: str, credential: str, model: str, dim: int,
                 http: Callable[..., str] | None = None,
                 batch_size: int = DEFAULT_BATCH, timeout: int = DEFAULT_TIMEOUT_S) -> None:
        self.base_url = base_url.rstrip("/")
        self.credential = credential
        self.model = model
        self.dim = int(dim)
        self.batch_size = max(1, int(batch_size))
        self.timeout = int(timeout)
        self._http = http or _http

    def embed(self, texts: Sequence[str], *, purpose: str) -> list[list[float]]:
        if purpose not in PURPOSES:
            raise EmbedError(f"{purpose!r} is not an embedding purpose; expected one of "
                             f"{sorted(PURPOSES)} — an asymmetric model needs to know which side "
                             f"of the comparison it is embedding")
        batch = list(texts)
        if not batch:
            return []
        out: list[list[float]] = []
        for start in range(0, len(batch), self.batch_size):
            chunk = batch[start:start + self.batch_size]
            out.extend(self._one_batch(chunk, PURPOSES[purpose]))
        return out

    def _one_batch(self, chunk: list[str], input_type: str) -> list[list[float]]:
        body = self._http(
            f"{self.base_url}/v1/embeddings",
            {"model": self.model, "input": chunk, "input_type": input_type},
            {"Authorization": f"Bearer {self.credential}",
             "Content-Type": "application/json"},
            self.timeout)
        return _vectors(body, expected=len(chunk), dim=self.dim, model=self.model)


def _vectors(body: str, *, expected: int, dim: int, model: str) -> list[list[float]]:
    """Parse a response into exactly `expected` vectors of width `dim`, in index order."""
    try:
        parsed: Any = json.loads(body)
    except (TypeError, ValueError) as exc:
        raise EmbedError(f"{model}: the gateway did not return JSON ({exc}). Body began: "
                         f"{str(body)[:200]!r}") from exc

    data = parsed.get("data") if isinstance(parsed, dict) else None
    if not isinstance(data, list):
        detail = ""
        if isinstance(parsed, dict) and parsed.get("error"):
            error = parsed["error"]
            detail = error.get("message", str(error)) if isinstance(error, dict) else str(error)
        raise EmbedError(f"{model}: the response carried no embeddings"
                         f"{f' — {detail}' if detail else ''}")

    # Providers may answer out of order, so place by the index THEY report rather than by arrival.
    placed: dict[int, list[float]] = {}
    for entry in data:
        index = entry.get("index", len(placed)) if isinstance(entry, dict) else None
        vector = entry.get("embedding") if isinstance(entry, dict) else None
        if not isinstance(index, int) or not isinstance(vector, list):
            raise EmbedError(f"{model}: an entry carried no index and embedding: {entry!r}")
        if index in placed:
            raise EmbedError(f"{model}: index {index} came back twice — letting the last one win "
                             f"would attach one row's vector to another")
        if len(vector) != dim:
            raise EmbedError(f"{model}: returned a {len(vector)}-wide vector where the index "
                             f"expects {dim}; a mismatched width cannot be compared")
        placed[index] = [float(v) for v in vector]

    if len(placed) != expected or set(placed) != set(range(expected)):
        raise EmbedError(
            f"{model}: asked for {expected} vectors and got {len(placed)} "
            f"(indices {sorted(placed)}). Zipping these onto the inputs would attach the wrong "
            f"text to the wrong vector, so nothing is attached")
    return [placed[i] for i in range(expected)]
