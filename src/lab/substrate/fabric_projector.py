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

from lab.core.semantic.fabric.catalog import pointer_key
from lab.core.semantic.fabric.ontology import (CONTEXT_IRI, DELIVERED_UNDER, DOCUMENT_TYPE, REFERENCES,
                                               SUBJECT, short)
from lab.core.semantic.fabric.rungs import CONSTRUCTED
from lab.platform import config, fabric_events, streams, workflows
from lab.platform.filetypes import file_slug as slug
from lab.platform.contracts import ARTIFACT_PUBLISH, CollabTools, SemanticTools, WorkflowStatus
from lab.substrate import fabric_gateway

GROUP = "fabric-projector"
CONSUMER = "1"
PROJECTED_TTL_S = 86400
TAG_KIND = "projection"
# ONE page for the whole catalogue, at a FIXED name: `collab_put` replaces a file of the same name, so the
# URL a person bookmarks is always the current picture. A `corpus-<date>.html` per publish would be a folder
# of stale pages with nothing to say which one to open.
CORPUS_NAME = "documentation-fabric-corpus"
CORPUS_KEY = "fabric:corpus-drawn"
CORPUS_EVERY_S = 300


def page(row: dict, topology: dict | None = None) -> str:
    """The Markdown projection of one record. Pure: frontmatter = the row's facets, body = its links.
    Metadata only — the artifact's own content lives in its system of record, linked, never copied.
    `topology` is the drawn view beside it ({url, nodes, concepts}) when one was written — a link, never a
    picture, because the page is text and the view is regenerated on every publish."""
    links = row.get("links") or []
    ctx = [l["object"] for l in links if l.get("predicate") == short(DELIVERED_UNDER)]
    # The LABEL the fabric already resolved, not the IRI's tail. They differ exactly where it matters:
    # `doc-types#unknown` is the answer "I looked and none of these fits", and its label says so — while
    # the tail renders as `*unknown · published*`, which reads as a missing value rather than a decision
    # somebody made. `catalog_get` resolves it, so the page must not re-derive it worse.
    typed = next((l for l in links if l.get("predicate") == short(DOCUMENT_TYPE)), {})
    subjects = [l["object"] for l in links if l.get("predicate") == short(SUBJECT)]
    refs = [l for l in links if l.get("predicate") == short(REFERENCES)]
    pointer = row.get("pointer") or {}
    custody = pointer.get("handle") or pointer.get("ref") or pointer.get("itemId") or pointer.get("workItem") or ""
    front = {
        "fabric_iri": row["iri"], "title": row.get("title") or "", "document_type": str(typed.get("label") or "") or _short(row.get("document_type")),
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
    if topology and topology.get("url"):
        lines += ["## Topology", "",
                  f"[What this is about, drawn]({topology['url']}) — {len(topology.get('concepts') or [])} concepts, "
                  f"{topology.get('nodes', 0)} nodes. Redrawn from the graph on every publish; the colour of a box "
                  "says how the fabric knows it.", ""]
    lines += ["## Source", "", f"`{front['source']}` — open it in its system of record; this page is a projection "
              "of the fabric's record and is regenerated on every publish.", ""]
    return "\n".join(lines)


def _short(iri) -> str:
    s = str(iri or "")
    return short(s) if "#" in s or "/" in s[8:] else s.rsplit(":", 1)[-1] if s.startswith("urn:") else s


async def project(state: dict, *, folder: str, call=None, client=None) -> dict | None:
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
    stem = slug(row.get("title") or iri.rsplit(":", 1)[-1])
    run_id = str(state.get("request_id") or "")
    # The picture FIRST, because the page links to it — and a view that cannot be drawn must not cost the page:
    # a record with no drawing is a page missing one section, while a link to a page nobody wrote is a broken
    # promise a reader finds instead of the fabric.
    drawn = await draw(iri, stem, folder=folder, call=go, client=client, run_id=run_id)
    out = await write_page(f"{stem}.md", page(row, drawn), folder=folder, call=go, client=client, run_id=run_id)
    await _record_page(iri, out.get("url", ""), call=go)
    # LAST, and separate: the record's page, its drawing and its catalogue link have all landed by now, so a
    # corpus redraw can only add to a run that already succeeded — never undo it.
    corpus = await draw_corpus(folder=folder, call=go, client=client, run_id=run_id)
    return {**out, "topology": drawn.get("url", "") if drawn else "", "corpus": corpus}


async def _record_page(iri: str, url: str, *, call) -> None:
    """The page's URL ON THE RECORD, so `catalog_get` can hand a person the page. Measured 10 Oct 2026: asked
    for a record's entry "and the link to its projection page", the Teams bot answered that the entry carries
    none — correct, and the end of every answer that should have offered it. The URL was already on the RUN,
    which is not where a reader looks.

    Rung C: the fabric's own deterministic projector CONSTRUCTED this location (D is refused outright —
    "derived is computed, not asserted").

    BEST EFFORT, after the write and never before it, like `continuations.link_runs`: the page is already in
    the folder and tagged by the time this runs, so a catalogue that cannot be reached must leave the
    projection standing. Losing the page would be far worse than losing the link to it."""
    if not url:                                  # nothing was written (no folder), so there is no link to record
        return
    try:
        await call([(SemanticTools.catalog_assert, {"iri": iri, "field": "projection_url", "value": url,
                                                    "rung": CONSTRUCTED, "method": "fabric-projector"})])
    except Exception as e:                       # noqa: BLE001 — the page stands; the link to it is extra
        print(f"[projector] {iri}: page written but its link was not recorded "
              f"({type(e).__name__}: {e})", flush=True)


async def draw(iri: str, stem: str, *, folder: str, call, client=None, run_id: str = "") -> dict | None:
    """The record's topology view, drawn and written beside its page. Returns {url, nodes, concepts} or None.

    Built by the fabric from the CURRENT graph on every publish — there is no stored layout, so the picture a
    reader opens is never older than the knowledge it claims to show.

    Only the DRAWING is optional. Once the file is in the folder the write must complete, loop guard and all:
    a topology page left untagged is ingested by the fabric as a new document on the next sweep — the very loop
    the guard exists to stop — and it would be invisible, because the record's own page still published. So the
    guarded region ends where the write begins, and a half-finished write fails the run to be reclaimed."""
    try:
        view = (await call([(SemanticTools.topology, {"iri": iri})]))[0]
        view = json.loads(view) if isinstance(view, str) else view
    except Exception as e:                       # noqa: BLE001 — a drawing is extra; the record is the work
        print(f"[projector] {iri}: no topology drawn ({type(e).__name__}: {e})", flush=True)
        return None
    put = await write_ref(f"{stem}.topology{view.get('suffix') or '.html'}", view["ref"], folder=folder,
                          call=call, client=client, run_id=run_id)
    return {**view, "url": put.get("url", "")}


async def draw_corpus(*, folder: str, call, client=None, run_id: str = "") -> str:
    """The WHOLE catalogue drawn as one page in the same folder — every record that is about something, the
    concepts they share, the vocabulary's edges between those. Returns its URL, or "" when none was drawn.

    `semantic_view_corpus` does the drawing; the projector renders NOTHING itself, because which adapter draws
    a focusless view is configuration (`FABRIC_CORPUS_RENDERER`) and the tool already picks it — hence the
    suffix comes back from the tool too.

    BOUNDED, not per publish. A whole-catalogue redraw is O(the catalogue) — measured 4.9 s at 61 records,
    157 links — and it runs in the SAME single consumer as the per-record pages, so a sweep publishing N
    records would pay N redraws of which N-1 are superseded within seconds while the records behind them wait.
    The record's own page and catalogue entry are the authoritative, immediate writes; this is a browsing
    surface, so five minutes of staleness costs a reader nothing. The flip side, stated: the LAST publish of a
    quiet day may not reach the picture until the next one, which is the trade a debounce makes.

    The bound is claimed AFTER the write, not before: a put or a tag that fails leaves the run unacked to be
    reclaimed, and a claim already taken would skip the redraw on the retry — leaving a file in the folder that
    the loop guard never marked, the very loop it exists to stop. The cost of claiming late is that two
    consumers could both redraw once; there is only ever one (two consumers of a group sharing a name would
    share a pending list), and the second would overwrite an identical page."""
    if client is not None and client.get(CORPUS_KEY):
        return ""
    try:
        view = (await call([(SemanticTools.view_corpus, {})]))[0]
        view = json.loads(view) if isinstance(view, str) else view
    except Exception as e:                       # noqa: BLE001 — a picture of everything is extra; one record is the work
        print(f"[projector] no corpus drawn ({type(e).__name__}: {e})", flush=True)
        return ""
    # ...but once the file is in the folder the write must complete, loop guard and all — the same boundary as
    # `draw`: the guarded region ends where the write begins.
    put = await write_ref(f"{CORPUS_NAME}{view.get('suffix') or '.html'}", view["ref"], folder=folder,
                          call=call, client=client, run_id=run_id)
    if client is not None:
        client.set(CORPUS_KEY, "1", ex=CORPUS_EVERY_S)
    return put.get("url", "")


async def write_page(name: str, text: str, *, folder: str, call, client=None, run_id: str = "") -> dict:
    """ONE small Markdown page into the wiki folder, by reference: stored as a lab artifact, then `collab_put`
    (which replaces a file of the same name), then MARKED as fabric-written so the ingress drops the change
    event this write causes — the loop guard is part of the write, not something a caller remembers (a page
    written without it is ingested by the fabric on the next sweep, every time it is rewritten). Shared by the
    record projection and the measurements page."""
    stored = (await call([(SemanticTools.store_page, {"text": text, "name": name})]))[0]
    stored = json.loads(stored) if isinstance(stored, str) else stored
    if not folder:
        print(f"[projector] would write {name} ({len(text)} chars) — FABRIC_WIKI_FOLDER unset", flush=True)
        return {"ref": stored["ref"], "handle": "", "name": name}
    return await write_ref(name, stored["ref"], folder=folder, call=call, client=client, run_id=run_id)


async def write_ref(name: str, ref: str, *, folder: str, call, client=None, run_id: str = "") -> dict:
    """An already-stored artifact into the wiki folder, and the loop guard that must go with it. Separate from
    `write_page` because the topology view is rendered by the fabric and never passes through this process as
    text — but it is written, tagged and remembered in exactly the same way."""
    if not folder:
        print(f"[projector] would write {name} ({ref}) — FABRIC_WIKI_FOLDER unset", flush=True)
        return {"ref": ref, "handle": "", "name": name, "url": ""}
    put = (await call([(CollabTools.put, {"folder": folder, "ref": ref, "name": name})]))[0]
    put = json.loads(put) if isinstance(put, str) else put
    out = {"ref": ref, "handle": str(put.get("handle") or ""), "name": str(put.get("name") or name),
           "url": str(put.get("url") or ""),
           "version": str(put.get("modified") or put.get("version") or "")}
    if out["handle"]:
        # a fabric page is regenerated on every write, so tagging every version of it (an empty stamp is
        # accepted) is intended — a person's edit to a projection is not a change the fabric ingests
        fabric_events.mark_written(pointer_key({"source": "collab", "handle": out["handle"]}),
                                   out["version"], TAG_KIND, run_id, client=client)
    return out


def handle(entry_id: str, fields: dict, *, folder: str, client, call=None) -> dict | None:
    """One finished run. Acks when the work is done; a FAILED write stays unacked and is reclaimed."""
    rid = fields.get("request_id", "")
    try:
        if fields.get("process") != ARTIFACT_PUBLISH.name:
            return _done(entry_id, client)
        if _already(client, rid):
            return _done(entry_id, client)
        out = asyncio.run(project(workflows.status(rid, client=client), folder=folder, call=call, client=client))
        if out is None:
            return _done(entry_id, client)
        # the topology URL rides the run so whatever answers a person — the review app, the bot — can
        # offer the picture without drawing it again; "" when none was drawn, which reads as "no link"
        workflows.annotate(rid, client=client, projection_ref=out["ref"], projection_handle=out["handle"],
                           topology_url=out.get("topology", ""))
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
