"""reference-mcp — the governed corpus, exposed as tools.

Read-only by construction, at three levels that each hold on their own: the catalogue declares no
write tool, the adapter implements none, and the database refuses writes from the role this service
runs as (DR-03). Publication is an operator CLI holding the signing key and the publisher DSN.

Every tool takes `run_id`, `process` and `field` — the DERIVED FIELD, not just the run. FR-44 needs
every derived field to record the versions it consulted, and making the attribution an ARGUMENT is
what removes the "report your sources afterwards" step a run could forget: the consumption row is
written inside the call or the call did not happen.

Span attributes are counts and ids only. A span reaches a collector this lab does not authenticate,
so an artifact's TEXT never goes on one — the same rule the speech and collab servers keep.
"""
from __future__ import annotations

from typing import Any

from fastmcp.exceptions import ToolError

from lab.core.reference.errors import ReferenceError
from lab.core.reference.model import Pin, RunRef
from lab.platform import config
from lab.substrate.mcpserver import LabServer, span

SERVICE = "reference-mcp"
server = LabServer(SERVICE, config.REFERENCE_MCP_PORT)

#: The most passages ONE relevance query returns, on both transports (the tool and the
#: OpenAI-shaped façade in `vectorstore`). A cap rather than a caller's number so nobody can page
#: the corpus out through a search; a matcher that needs more asks more questions.
MAX_HITS = 20


def _run(run_id: str, process: str, field: str) -> RunRef:
    try:
        return RunRef(run_id=run_id, process=process, field=field)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def _pin(pin_id: str) -> Pin:
    """A pin the caller already took. Only its id crosses the wire — the versions are the server's
    record, so a caller cannot claim a pin it was not given."""
    if not str(pin_id or "").strip():
        raise ToolError("every read is made under a pin; call reference_pin first and pass its "
                        "pin_id — an unpinned read would let two reads in one run straddle a "
                        "release")
    return server.reference().pin_by_id(pin_id)          # type: ignore[attr-defined]


def _guard(fn, *args, **kwargs):
    """Turn a typed refusal into the sentence a caller can act on, and let nothing else through."""
    try:
        return fn(*args, **kwargs)
    except ReferenceError as exc:
        raise ToolError(exc.sentence) from exc


@server.tool()
def reference_catalogue() -> dict:
    """Every governed artifact this instance may consult, at the version its release ring resolves
    to. Use it to discover artifact ids and record types before pinning."""
    heads = _guard(server.reference().catalogue)
    span().set_attribute("reference.artifacts", len(heads))
    return {"ring": config.REFERENCE_RING,
            "artifacts": [{"artifact_id": h.artifact_id, "kind": str(h.kind),
                           "record_type": h.record_type, "title": h.title, "owner": h.owner,
                           "version": h.version, "retrieval": str(h.retrieval)}
                          for h in heads]}


@server.tool()
def reference_pin(artifact_ids: list[str] | None = None) -> dict:
    """Freeze the artifact versions this run will consult; omit `artifact_ids` for the whole
    corpus. Every signature is verified here, and any failure fails the whole pin. Pass the
    returned `pin_id` to every subsequent read.

    Each version says how it is READ — `retrieval` is `whole` (read every record:
    `reference_lookup(record_type, key={}, artifact_id=<id>)` returns them all, unlimited), `key`
    (exact reads by natural key) or `vector` (also searchable with `reference_search`). Read it the
    way it says; never infer the mode from size."""
    pin = _guard(server.reference().pin, artifact_ids or [])
    span().set_attribute("reference.pinned", len(pin.versions))
    return {"pin_id": pin.pin_id, "ring": pin.ring, "pinned_at": pin.pinned_at,
            "expires_at": pin.expires_at,
            "versions": [{"artifact_id": v.artifact_id, "version": v.version,
                          "signature_id": v.signature_id, "retrieval": str(v.retrieval)}
                         for v in pin.versions]}


@server.tool()
def reference_lookup(pin_id: str, record_type: str, key: dict, run_id: str, process: str,
                     field: str, limit: int = 20, artifact_id: str = "") -> dict:
    """EXACT retrieval over governed records, by the artifact's published natural key.

    A miss is a legitimate answer and returns no records — it does not mean the corpus is empty.
    Anything that merely resembles the key is reported under `near`, which is NOT an answer: a
    nearly-right predicate or price line is worse than a failed lookup.

    `artifact_id` narrows to ONE artifact, and a caller that knows which it wants should pass it:
    a record type is a classification two artifacts may share. For an artifact whose `retrieval`
    is `whole`, naming it with an empty `key` returns EVERY record regardless of `limit`."""
    out = _guard(server.reference().lookup, _pin(pin_id), record_type=record_type, key=key,
                 run=_run(run_id, process, field), limit=limit, artifact_id=artifact_id)
    span().set_attribute("reference.matched", out.matched)
    return {"records": [{"record_id": r.record_id, "key": dict(r.key), "body": dict(r.body),
                         "artifact_id": r.citation.artifact_id, "version": r.citation.version}
                        for r in out.records],
            "citations": [_citation(c) for c in out.citations],
            "matched": out.matched,
            "near": [dict(n) for n in out.near]}


@server.tool()
def reference_search(pin_id: str, question: str, run_id: str, process: str, field: str,
                     artifact_ids: list[str] | None = None, k: int = 5) -> dict:
    """SEMANTIC retrieval over the artifacts declared `vector` — prose, AND record artifacts that
    also index (the capability map). A hit over a record artifact names its `record_id`, so follow
    it with `reference_record` for the exact row. Naming an exact (`key`/`whole`) artifact refuses:
    read those with `reference_lookup`.

    Refuses when the pinned version's index is absent, incomplete or embedded with a different
    model — a degraded answer here would read as "the corpus has nothing on this", which is an
    all-clear nobody is entitled to infer."""
    out = _guard(server.reference().search, _pin(pin_id), question=question,
                 run=_run(run_id, process, field), artifact_ids=artifact_ids or [],
                 k=min(int(k), MAX_HITS))
    span().set_attribute("reference.passages", len(out.passages))
    return {"passages": [_passage(p) for p in out.passages],
            "citations": [_citation(c) for c in out.citations]}


@server.tool()
def reference_record(pin_id: str, artifact_id: str, record_id: str, run_id: str, process: str,
                     field: str) -> dict:
    """One record by the id a citation carries — how a cited answer is reopened at review."""
    try:
        found = _guard(server.reference().record, _pin(pin_id), artifact_id=artifact_id,
                       record_id=record_id, run=_run(run_id, process, field))
    except KeyError as exc:
        raise ToolError(str(exc)) from exc
    return {"record": {"record_id": found.record_id, "key": dict(found.key),
                       "body": dict(found.body)},
            "citation": _citation(found.citation)}


@server.tool()
def reference_consumers(artifact_id: str, version: str, limit: int = 100) -> dict:
    """Which runs, and which derived fields, consulted this artifact version (FR-45).

    The blast radius of a bad release, in one call. Granted separately from the read tools: it
    spans runs, so it answers an audit question rather than a derivation one."""
    rows = _guard(server.reference().consumers, artifact_id=artifact_id, version=version)[:limit]
    span().set_attribute("reference.consumers", len(rows))
    return {"consumers": [{"run_id": c.run_id, "process": c.process, "field": c.field,
                           "mode": c.mode, "locator": c.locator, "hit": c.hit,
                           "consulted_at": c.consulted_at} for c in rows],
            "runs": len({c.run_id for c in rows})}


def _passage(p: Any) -> dict:
    """`record_id`/`key` are set when the passage was derived from a RECORD: a relevance hit over
    the capability map names the exact row, so a caller follows it with `reference_record`."""
    return {"passage_id": p.passage_id, "text": p.text, "score": p.score,
            "heading_path": list(p.heading_path), "artifact_id": p.citation.artifact_id,
            "version": p.citation.version, "record_id": p.record_id, "key": dict(p.key)}


def _citation(citation: Any) -> dict:
    """`master_ref` is the HUMAN-readable signed master, so what an agent cites is what a person
    opens — DR-02 made visible at the point of use."""
    return {"artifact_id": citation.artifact_id, "title": citation.title,
            "version": citation.version, "signature_id": citation.signature_id,
            "locator": citation.locator, "anchor": citation.anchor,
            "master_ref": citation.master_ref}


if __name__ == "__main__":
    from lab.substrate.mcp.reference import vectorstore     # the OpenAI-shaped façade beside /mcp
    server.serve(routes=vectorstore.routes(server, max_hits=MAX_HITS))
