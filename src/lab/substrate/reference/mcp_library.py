"""The reference port over reference-mcp's TOOLS — for a substrate server that holds no corpus
credential.

decision-mcp and valuation-mcp derive from the published rules but are deliberately handed no
reader DSN (a credential a pure derivation has no business holding); what they are handed is
reference-mcp's address and the substrate's shared secret. So this adapter satisfies
`lab.core.reference.port.ReferenceLibrary` by CALLING reference-mcp — substrate to substrate,
the same trust the gateway extends to every MCP server — and the pin, the signature check and
the consumption row all stay where they are: on the one server that reads the tables.

Each call runs a fresh event loop on its own thread. A tool body may be invoked with or without
a running loop depending on the server that hosts it, and a thread of its own is the one place
`asyncio.run` is always legal. `call` is injected, so the mapping is tested without a socket.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, Callable, Mapping, Sequence

from lab.core.reference.errors import ReferenceError
from lab.core.reference.model import (
    ArtifactHead,
    ArtifactKind,
    ArtifactVersion,
    Citation,
    Consumption,
    Passage,
    PassageResult,
    Pin,
    Record,
    RecordResult,
    Retrieval,
    RunRef,
)
from lab.platform import config
from lab.platform.contracts import ReferenceTools

__all__ = ["McpReferenceLibrary", "build"]


def _remote_call(url: str, headers: Mapping[str, str]) -> Callable[[str, dict], Any]:
    """`call(tool, args) -> data`, over fastmcp, each call on a loop of its own."""
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport
    from fastmcp.exceptions import ToolError

    async def one(tool: str, args: dict) -> Any:
        async with Client(StreamableHttpTransport(url, headers=dict(headers))) as client:
            return (await client.call_tool(tool, args)).data

    def call(tool: str, args: dict) -> Any:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            try:
                return pool.submit(lambda: asyncio.run(one(tool, args))).result()
            except ToolError as exc:
                # The server's refusal is already a sentence (its `_guard` renders every typed
                # refusal); it travels as the base type so a caller's `except ReferenceError`
                # still holds and the sentence reaches whoever asked.
                raise ReferenceError(str(exc)) from exc
    return call


class McpReferenceLibrary:
    """A governed corpus reached through reference-mcp's read tools."""

    def __init__(self, *, url: str, secret: str = "", ring: int = 0,
                 call: Callable[[str, dict], Any] | None = None) -> None:
        self.url = url
        self.ring = int(ring)
        headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        self._call = call or _remote_call(url, headers)

    # ---------------------------------------------------------------- catalogue and pin

    def catalogue(self) -> list[ArtifactHead]:
        out = self._call(ReferenceTools.catalogue, {})
        return [ArtifactHead(artifact_id=a["artifact_id"], kind=ArtifactKind(a["kind"]),
                             title=a["title"], owner=a["owner"], version=a["version"],
                             record_type=a.get("record_type") or "",
                             retrieval=Retrieval(a["retrieval"]) if a.get("retrieval") else None)
                for a in out.get("artifacts") or []]

    def pin(self, artifact_ids: Sequence[str] = ()) -> Pin:
        taken = self._call(ReferenceTools.pin, {"artifact_ids": list(artifact_ids)})
        return self.pin_by_id(taken["pin_id"])          # the versions, whole, from the server

    def pin_by_id(self, pin_id: str) -> Pin:
        info = self._call(ReferenceTools.pin_info, {"pin_id": pin_id})
        return Pin(pin_id=info["pin_id"], ring=int(info["ring"]), pinned_at=str(info["pinned_at"]),
                   expires_at=str(info["expires_at"]),
                   versions=tuple(ArtifactVersion(
                       artifact_id=v["artifact_id"], version=v["version"],
                       kind=ArtifactKind(v["kind"]), title=v.get("title", ""),
                       master_ref=v.get("master_ref", ""), master_sha256=v.get("master_sha256", ""),
                       agent_sha256=v.get("agent_sha256", ""), derived_from=v.get("derived_from", ""),
                       signature_id=v.get("signature_id", ""), signed_at=str(v.get("signed_at", "")),
                       ring=int(v.get("ring", info["ring"])),
                       published_at=str(v.get("published_at", "")),
                       retrieval=Retrieval(v["retrieval"]) if v.get("retrieval") else None)
                       for v in info.get("versions") or []))

    # ---------------------------------------------------------------- the reads

    def _citation(self, pin: Pin, c: Mapping[str, Any]) -> Citation:
        return Citation(artifact_id=c["artifact_id"], title=c.get("title", ""),
                        version=c["version"], signature_id=c.get("signature_id", ""),
                        locator=c.get("locator", ""), master_ref=c.get("master_ref", ""),
                        anchor=c.get("anchor", ""))

    def lookup(self, pin: Pin, *, record_type: str, key: Mapping[str, Any], run: RunRef,
               limit: int = 20, artifact_id: str = "") -> RecordResult:
        out = self._call(ReferenceTools.lookup, {
            "pin_id": pin.pin_id, "record_type": record_type, "key": dict(key), "limit": limit,
            "artifact_id": artifact_id, "run_id": run.run_id, "process": run.process,
            "field": run.field})
        citations = [self._citation(pin, c) for c in out.get("citations") or []]
        by_locator = {c.locator: c for c in citations}
        records = tuple(Record(
            record_id=r["record_id"], record_type=record_type, key=dict(r.get("key") or {}),
            body=dict(r.get("body") or {}),
            citation=by_locator.get(r["record_id"]) or Citation(
                artifact_id=r["artifact_id"], title="", version=r["version"], signature_id="",
                locator=r["record_id"], master_ref=""))
            for r in out.get("records") or [])
        return RecordResult(records=records, citations=tuple(citations),
                            near=tuple(dict(n) for n in out.get("near") or []))

    def search(self, pin: Pin, *, question: str, run: RunRef,
               artifact_ids: Sequence[str] = (), k: int = 5) -> PassageResult:
        out = self._call(ReferenceTools.search, {
            "pin_id": pin.pin_id, "question": question, "artifact_ids": list(artifact_ids),
            "k": k, "run_id": run.run_id, "process": run.process, "field": run.field})
        citations = [self._citation(pin, c) for c in out.get("citations") or []]
        by_locator = {c.locator: c for c in citations}
        passages = tuple(Passage(
            passage_id=p["passage_id"], text=p["text"], score=float(p["score"]),
            heading_path=tuple(p.get("heading_path") or ()),
            citation=by_locator.get(p["passage_id"]) or Citation(
                artifact_id=p["artifact_id"], title="", version=p["version"], signature_id="",
                locator=p["passage_id"], master_ref=""),
            record_id=p.get("record_id", ""), key=dict(p.get("key") or {}))
            for p in out.get("passages") or [])
        return PassageResult(passages=passages, citations=tuple(citations))

    def record(self, pin: Pin, *, artifact_id: str, record_id: str, run: RunRef) -> Record:
        out = self._call(ReferenceTools.record, {
            "pin_id": pin.pin_id, "artifact_id": artifact_id, "record_id": record_id,
            "run_id": run.run_id, "process": run.process, "field": run.field})
        found, citation = out["record"], out["citation"]
        return Record(record_id=found["record_id"], record_type=pin.version_of(artifact_id).kind
                      and "", key=dict(found.get("key") or {}), body=dict(found.get("body") or {}),
                      citation=self._citation(pin, citation))

    def consumers(self, *, artifact_id: str, version: str) -> list[Consumption]:
        out = self._call(ReferenceTools.consumers, {"artifact_id": artifact_id, "version": version})
        return [Consumption(run_id=c["run_id"], process=c["process"], field=c["field"],
                            artifact_id=artifact_id, version=version, mode=c["mode"],
                            consulted_at=str(c.get("consulted_at", "")),
                            locator=c.get("locator", ""), hit=bool(c.get("hit", True)))
                for c in out.get("consumers") or []]


def build(**overrides: Any) -> McpReferenceLibrary:
    """The container's factory. `embedder` is accepted and ignored: the server that answers a
    search embeds the query, not this reader."""
    overrides.pop("embedder", None)
    options: dict[str, Any] = {"url": config.REFERENCE_MCP_URL, "secret": config.MCP_SHARED_SECRET,
                               "ring": config.REFERENCE_RING}
    options.update(overrides)
    return McpReferenceLibrary(**options)
