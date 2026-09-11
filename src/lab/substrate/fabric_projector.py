"""The projector: a PUBLISHED record becomes a page people can read where they already look.

The fabric holds metadata; a wiki page is a PROJECTION of it — regenerated from the record, never edited
in place, and tagged as fabric-written so the ingress drops the change event the write itself causes
(the loop guard, note 003). Consumes `workflow:finished` for DONE `artifact_publish` runs; reads the record
through the gateway with the fabric's substrate identity (`FABRIC_CURATOR_KEY`); writes ONE small Markdown
file into `FABRIC_WIKI_FOLDER` by `collab_put`. Unset folder = it logs the page it would write.

Deliberately bounded, like the notifiers: only DONE publish runs; only the record's metadata and links (a
page names where the artifact is and what it is about, never what it says); a failed write is left unacked
and reclaimed; a landed write is remembered so at-least-once never becomes twice.

Run: .venv/bin/python -m lab.substrate.fabric_projector
"""
from __future__ import annotations

import asyncio
import json
import re

from lab.core.semantic.fabric.catalog import pointer_key
from lab.core.semantic.fabric.ontology import CONTEXT_IRI, DELIVERED_UNDER, REFERENCES, SUBJECT, short
from lab.platform import config, fabric_events, streams, workflows
from lab.platform.contracts import ARTIFACT_PUBLISH, CollabTools, SemanticTools, WorkflowStatus
from lab.substrate import fabric_gateway

GROUP = "fabric-projector"
CONSUMER = "1"
PROJECTED_TTL_S = 86400
TAG_KIND = "projection"


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return s[:80] or "record"


def page(row: dict) -> str:
    """The Markdown projection of one record. Pure: frontmatter = the row's facets, body = its links.
    Metadata only — the artifact's own content lives in its system of record, linked, never copied."""
    links = row.get("links") or []
    ctx = [l["object"] for l in links if l.get("predicate") == short(DELIVERED_UNDER)]
    subjects = [l["object"] for l in links if l.get("predicate") == short(SUBJECT)]
    refs = [l for l in links if l.get("predicate") == short(REFERENCES)]
    pointer = row.get("pointer") or {}
    custody = pointer.get("handle") or pointer.get("ref") or pointer.get("itemId") or pointer.get("workItem") or ""
    front = {
        "fabric_iri": row["iri"], "title": row.get("title") or "", "document_type": _short(row.get("document_type")),
        "state": row.get("state") or "", "baseline_version": row.get("baseline_version") or "",
        "delivery_context": [c.replace(CONTEXT_IRI, "") for c in ctx],
        "owner": row.get("owner") or "", "sensitivity_label": row.get("sensitivity_label") or "",
        "subjects": [_short(s) for s in subjects], "source": f"{pointer.get('source', '')}:{custody}",
        "generated_by": "documentation-fabric", "fabric_tag": TAG_KIND,
    }
    lines = ["---"]
    for k, v in front.items():
        lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    lines += ["---", "", f"# {front['title'] or _short(row['iri'])}", "",
              f"*{front['document_type'] or 'artifact'} · {front['state']}"
              + (f" · baseline {front['baseline_version']}" if front["baseline_version"] else "") + "*", ""]
    if ctx:
        lines += ["## Delivered under", ""] + [f"- {c}" for c in front["delivery_context"]] + [""]
    if subjects:
        lines += ["## About", ""] + [f"- {s}" for s in front["subjects"]] + [""]
    if refs:
        lines += ["## References", ""] + [f"- {r['object']} ({r.get('rung', '?')})" for r in refs] + [""]
    lines += ["## Source", "", f"`{front['source']}` — open it in its system of record; this page is a projection "
              "of the fabric's record and is regenerated on every publish.", ""]
    return "\n".join(lines)


def _short(iri) -> str:
    s = str(iri or "")
    return short(s) if "#" in s or "/" in s[8:] else s.rsplit(":", 1)[-1] if s.startswith("urn:") else s


async def project(state: dict, *, folder: str, call=None) -> dict | None:
    """Write the page for one finished publish run. Returns {ref, handle, name} or None when there is
    nothing to write. `call(calls)` is the gateway transport (injected by a test)."""
    if state.get("status") != WorkflowStatus.DONE.value or state.get("process") != ARTIFACT_PUBLISH.name:
        return None
    iri = str(state.get("artifact_iri") or (state.get("inputs") or {}).get("artifact_iri") or "")
    if not iri:
        return None
    go = call or fabric_gateway.call
    row = (await go([(SemanticTools.catalog_get, {"iri": iri})]))[0]
    if not row:
        raise LookupError(f"no catalog record {iri}")
    name = f"{slug(row.get('title') or iri.rsplit(':', 1)[-1])}.md"
    text = page(row)
    stored = (await go([(SemanticTools.store_spec, {"spec": {"text": text}, "name": name})]))[0]
    ref = stored["spec_ref"] if isinstance(stored, dict) else json.loads(stored)["spec_ref"]
    if not folder:
        print(f"[projector] would write {name} ({len(text)} chars) — FABRIC_WIKI_FOLDER unset", flush=True)
        return {"ref": ref, "handle": "", "name": name}
    put = (await go([(CollabTools.put, {"folder": folder, "ref": ref, "name": name})]))[0]
    return {"ref": ref, "handle": str(put.get("handle") or ""), "name": str(put.get("name") or name),
            "version": str(put.get("modified") or put.get("version") or "")}


def handle(entry_id: str, fields: dict, *, folder: str, client, call=None) -> dict | None:
    """One finished run. Acks when the work is done; a FAILED write stays unacked and is reclaimed."""
    rid = fields.get("request_id", "")
    try:
        if fields.get("process") != ARTIFACT_PUBLISH.name:
            return _done(entry_id, client)
        if _already(client, rid):
            return _done(entry_id, client)
        out = asyncio.run(project(workflows.status(rid, client=client), folder=folder, call=call))
        if out is None:
            return _done(entry_id, client)
        if out["handle"]:
            # The loop guard: the ingress drops the change event THIS write causes. The version is the
            # provider's stamp when it reports one; a projection page is fabric-owned and regenerated on
            # every publish, so tagging every version of it (an empty stamp) is the intended behaviour —
            # a person's edit to a projection is not a change the fabric ingests.
            fabric_events.mark_written(pointer_key({"source": "collab", "handle": out["handle"]}),
                                       out.get("version", ""), TAG_KIND, rid, client=client)
        workflows.annotate(rid, client=client, projection_ref=out["ref"], projection_handle=out["handle"])
        client.set(_key(rid), "1", ex=PROJECTED_TTL_S)
        _done(entry_id, client)
        return out
    except Exception as e:                          # noqa: BLE001 — one record must not stop the rest
        print(f"[projector] {rid}: {type(e).__name__}: {e}", flush=True)
        try:
            workflows.annotate(rid, client=client, projection_error=f"{type(e).__name__}: {e}"[:300])
        except Exception:                           # noqa: BLE001
            pass
        return None


def _key(rid: str) -> str:
    return f"fabric:projected:{rid}"


def _already(client, rid: str) -> bool:
    return bool(rid) and bool(client.get(_key(rid)))


def _done(entry_id: str, client) -> None:
    workflows.ack_finished(GROUP, entry_id, client=client)
    return None


def run_once(*, folder: str | None = None, client=None, block_ms: int = 0, call=None) -> list[dict]:
    r = client or _client()
    folder = config.FABRIC_WIKI_FOLDER if folder is None else folder
    events = workflows.finished_events(GROUP, CONSUMER, block_ms=block_ms, count=20, client=r)
    return [o for o in (handle(eid, f, folder=folder, client=r, call=call) for eid, f in events) if o]


def _client():
    from lab.platform import redis_client
    return redis_client.client()


def main() -> None:
    r = _client()
    workflows.ensure_finished_group(GROUP, r)
    streams.serve(name="fabric projector",
                  ready=f"fabric projector ready  group={GROUP} folder={'set' if config.FABRIC_WIKI_FOLDER else 'UNSET (log only)'}",
                  read=lambda: workflows.finished_events(GROUP, CONSUMER, block_ms=streams.BLOCK_MS, count=20, client=r),
                  handle=lambda eid, f: handle(eid, f, folder=config.FABRIC_WIKI_FOLDER, client=r))


if __name__ == "__main__":
    main()
