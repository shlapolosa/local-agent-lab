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
from lab.core.semantic.fabric.rungs import CONSTRUCTED, IMPACT_READS
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
#: A CONCEPT's page: `concept-<scheme>-<label>.md`, in the same folder as the records, so a subject link is a
#: plain relative Markdown link both Obsidian and SharePoint follow.
CONCEPT_PREFIX = "concept-"
#: record IRI -> the file its page was written as. The projector's own memory of what it WROTE, which is a
#: different question from the reader-facing `projection_url` ON the record: a concept page lists every record
#: about that concept (39 of 93 for one measured 7 Oct 2026) and asking the catalogue per record costs one
#: gateway call each — a round trip per record trips the fabric's own rate limit at about sixty (measured
#: 10 Oct 2026, `corpus_view`). No TTL: a page does not expire, and the hash is the size of the catalogue,
#: one short field per record.
PAGES_KEY = "fabric:pages"


def page(row: dict, topology: dict | None = None, targets: dict | None = None) -> str:
    """The Markdown projection of one record. Pure: frontmatter = the row's facets, body = its links.
    Metadata only — the artifact's own content lives in its system of record, linked, never copied.
    `topology` is the drawn view beside it ({url, nodes, concepts}) when one was written — a link, never a
    picture, because the page is text and the view is regenerated on every publish.

    `targets` is iri -> {label, page}: what this record's subjects and references are CALLED and which file in
    the same folder is about them, resolved by `project` through `resolve` — this function stays pure, which
    is why it is the thing the tests assert on. A target with no page is NAMED and not linked: a dead link is
    worse than plain text, because it looks like a promise."""
    links = row.get("links") or []
    ctx = [l["object"] for l in links if l.get("predicate") == short(DELIVERED_UNDER)]
    # The LABEL the fabric already resolved, not the IRI's tail. They differ exactly where it matters:
    # `doc-types#unknown` is the answer "I looked and none of these fits", and its label says so — while
    # the tail renders as `*unknown · published*`, which reads as a missing value rather than a decision
    # somebody made. `catalog_get` resolves it, so the page must not re-derive it worse.
    typed = next((l for l in links if l.get("predicate") == short(DOCUMENT_TYPE)), {})
    # ONE bullet per object: `catalog_get` reports a record's links across every rung graph, so a subject
    # promoted from X to H arrives twice and would be listed twice, reading as two subjects
    subjects = _one_per_object(l for l in links if l.get("predicate") == short(SUBJECT))
    refs = _one_per_object(l for l in links if l.get("predicate") == short(REFERENCES))
    targets = targets or {}
    pointer = row.get("pointer") or {}
    custody = pointer.get("handle") or pointer.get("ref") or pointer.get("itemId") or pointer.get("workItem") or ""
    front = {
        "fabric_iri": row["iri"], "title": row.get("title") or "", "document_type": _label(typed) or _short(row.get("document_type")),
        "state": row.get("state") or "", "baseline_version": row.get("baseline_version") or "",
        "delivery_context": [c.replace(CONTEXT_IRI, "") for c in ctx],
        "owner": row.get("owner") or "", "sensitivity_label": row.get("sensitivity_label") or "",
        "subjects": [_label(s) for s in subjects], "source": f"{pointer.get('source', '')}:{custody}",
        "generated_by": "documentation-fabric", "fabric_tag": TAG_KIND,
    }
    lines = _front(front) + [f"# {front['title'] or _short(row['iri'])}", "",
              f"*{front['document_type'] or 'artifact'} · {front['state']}"
              + (f" · baseline {front['baseline_version']}" if front["baseline_version"] else "") + "*", ""]
    if ctx:
        lines += ["## Delivered under", ""] + [f"- {c}" for c in front["delivery_context"]] + [""]
    if subjects:
        lines += ["## About", ""] + [f"- {_bullet(s, targets)}" for s in subjects] + [""]
    if refs:
        lines += ["## References", ""] + [f"- {_bullet(r, targets)} ({r.get('rung', '?')})" for r in refs] + [""]
    if topology and topology.get("url"):
        lines += ["## Topology", "",
                  f"[What this is about, drawn]({topology['url']}) — {len(topology.get('concepts') or [])} concepts, "
                  f"{topology.get('nodes', 0)} nodes. Redrawn from the graph on every publish; the colour of a box "
                  "says how the fabric knows it.", ""]
    lines += ["## Source", "", f"`{front['source']}` — open it in its system of record; this page is a projection "
              "of the fabric's record and is regenerated on every publish.", ""]
    return "\n".join(lines)


def concept_page(concept: dict) -> str:
    """ONE concept's page: what it is called, which vocabulary holds it, and the records about it — each a
    link where the fabric wrote one. This is what makes following a subject worth doing: a reader who leaves a
    document by its topic arrives somewhere that leads on, rather than at a word.

    What a concept page IS, deliberately: the fabric's INDEX of its own records — not a definition and not a
    hierarchy. The vocabulary's own meaning belongs to the steward and is already published as its master
    (`vocab_master`); paraphrasing it here would be a second home for the definition, drifting from the first
    the day one is edited. So this page says only what the fabric knows that the master cannot: which
    documents are about this, and where they are.

    Pure, like `page()` — `resolve` did the lookups — and nothing is rendered that the payload does not carry:
    a concept the fabric holds no records for says so rather than showing an empty heading.

    No document TYPE on the rows: `semantic_trace` joins the catalogue for the type's IRI and nothing resolves
    its label, and a type rendered from its tail reads `unknown` for the deliberate answer "no type fits" —
    the exact defect the record's own page was fixed for on 10 Oct 2026. The state is unambiguous without a
    lookup; the type is not."""
    records = concept.get("records") or []
    label, scheme = str(concept.get("label") or ""), str(concept.get("scheme") or "")
    front = {"fabric_iri": concept["iri"], "label": label, "scheme": scheme, "kind": "concept",
             "records": len(records), "generated_by": "documentation-fabric", "fabric_tag": TAG_KIND}
    lines = _front(front) + [f"# {label or _short(concept['iri'])}", "",
                             "*concept" + (f" · {scheme}" if scheme else "") + "*", ""]
    if records:
        lines += ["## Documents about this", ""] + [
            f"- {_link(str(r.get('title') or _short(r.get('iri'))), str(r.get('page') or ''))}"
            + (f" — {r['state']}" if r.get("state") else "") + (f" ({r['rung']})" if r.get("rung") else "")
            for r in records] + [""]
    lines += ["## About this page", "", "A projection of the fabric's own records, rewritten whenever a "
              "document about this concept publishes. The documents listed are the ones the fabric holds on "
              "its trusted rungs (C·X·H·D) — a suggested subject is a model's guess, so it is not here.", ""]
    return "\n".join(lines)


def concept_name(iri: str, label: str = "") -> str:
    """The file a concept's page is written as — SCHEME-qualified, because `vocab_conflicts` exists precisely
    because one word can mean two things in two vocabularies. Named by its label alone, one concept's page
    would silently overwrite the other's and every link into it would then be about the wrong thing, which
    reads as the fabric asserting a match it never made.

    The ID is the fallback, and the fallback is reached by a label that SLUGGED TO NOTHING, not only by one
    that is missing: `file_slug` folds to ASCII and drops the rest, so every Arabic label returns its default
    — `تقديم الرعاية` and `إدارة الدواء` would both be `concept-cafe-concept.md`. This lab's own corpus is
    bilingual (the whole speech bake-off exists because of it), so that is the expected case, not an exotic
    one, and it is the worst failure available here: the link resolves, to a page about something else."""
    return f"{CONCEPT_PREFIX}{slug(_scheme(iri), 'vocabulary')}-{slug(label, '') or slug(_short(iri), 'concept')}.md"


def record_name(row: dict) -> str:
    """The file a RECORD's page is written as. ONE home: the projector names its own output here, and a link
    to it from another page is the same string or it is broken."""
    return f"{page_stem(row)}.md"


def page_stem(row: dict) -> str:
    """The stem a record's page and the drawing beside it share — the IRI's tail (a ULID, unique by
    construction) whenever the title slugs to nothing, for the reason `concept_name` gives: a title in Arabic
    script leaves `file_slug` with no ASCII at all, and two such records would otherwise share one file while
    the page index pointed both IRIs at it."""
    return slug(row.get("title") or "", "") or slug(str(row.get("iri") or "").rsplit(":", 1)[-1])


def _front(front: dict) -> list[str]:
    """YAML frontmatter — the facets a reader filters and sorts on, in the one shape both pages use."""
    return ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in front.items()] + ["---", ""]


def _label(link: dict) -> str:
    """The LABEL the fabric already resolved for a link, falling back to the IRI's tail. `catalog_get` resolves
    a concept's prefLabel, so a page re-deriving it from the IRI reads `c1` where a person wrote `Care
    Delivery` — the same class of defect as rendering a document type from its tail."""
    return str(link.get("label") or "") or _short(link.get("object"))


def _bullet(link: dict, targets: dict) -> str:
    t = targets.get(str(link.get("object") or "")) or {}
    return _link(str(t.get("label") or "") or _label(link), str(t.get("page") or ""))


def _link(label: str, page_file: str) -> str:
    """Standard Markdown, NEVER a `[[wikilink]]`. Obsidian — the instrument for "does anybody actually wander
    this" — renders both; SharePoint, Copilot and every later renderer understand only the first, so the test
    tool must not dictate a non-portable syntax."""
    return f"[{label}]({page_file})" if page_file else label


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
    stem, name = page_stem(row), record_name(row)
    run_id = str(state.get("request_id") or "")
    targets, concepts = await resolve(row, call=go, client=client)
    # The picture FIRST, because the page links to it — and a view that cannot be drawn must not cost the page:
    # a record with no drawing is a page missing one section, while a link to a page nobody wrote is a broken
    # promise a reader finds instead of the fabric.
    drawn = await draw(iri, stem, folder=folder, call=go, client=client, run_id=run_id)
    # ...and the concept pages BEFORE it too, for exactly the same reason: the record's page links to them, so
    # writing it first would leave a promise in the folder until the reclaim. Unguarded, so a concept page
    # that cannot be written fails the run — which is why nothing has to be pruned from `targets`: by the time
    # the record's page is written, every page it points at is either in the folder or the run has raised.
    #
    # NOT debounced, unlike the corpus, and the frequency question is a real one: the hottest measured concept
    # carries 39 of 93 records (7 Oct 2026), so a full sweep rewrites that ONE file 39 times, 38 of them
    # superseded within seconds. The corpus's bound does not transfer, because the two pages are refreshed by
    # different events: the corpus is redrawn by the next publish of ANYTHING, so a debounce costs it minutes
    # of staleness; a concept page is rewritten only by a publish about THAT concept, so a skipped write can
    # leave a record missing from it indefinitely — and the list of records IS the page's entire content, so a
    # reader would be told "2 documents" where there are three with nothing to say otherwise. A redundant
    # write of a page that is correct beats a cheap page that is quietly wrong.
    written = {}
    for c in concepts:
        put = await write_page(c["name"], concept_page(c), folder=folder, call=go,
                               client=client, run_id=run_id)
        # the name the PROVIDER answered with, which is what `write_ref` already honours: the link must point
        # at the file that is there, not at the one the projector asked for
        written[c["iri"]] = targets[c["iri"]]["page"] = str(put.get("name") or c["name"])
        _remember_page(c["iri"], written[c["iri"]] if put.get("handle") else "", client=client)
    out = await write_page(name, page(row, drawn, targets), folder=folder, call=go, client=client,
                           run_id=run_id)
    _remember_page(iri, str(out.get("name") or "") if out.get("handle") else "", client=client)
    await _record_page(iri, out.get("url", ""), call=go)
    # LAST, and separate: the record's page, its drawing and its catalogue link have all landed by now, so a
    # corpus redraw can only add to a run that already succeeded — never undo it.
    corpus = await draw_corpus(folder=folder, call=go, client=client, run_id=run_id)
    return {**out, "topology": drawn.get("url", "") if drawn else "", "corpus": corpus,
            "concepts": sorted(written.values())}


async def resolve(row: dict, *, call, client=None) -> tuple[dict, list[dict]]:
    """What this record's page needs in order to LINK, and the concept pages that make those links real.

    `page()` is pure, so every lookup lives here. A subject is resolved to the records that SHARE the concept
    (`semantic_trace`, inbound over dct:subject, on the trusted rungs only — a suggested subject is a model's
    guess, the same rule as `topology`'s relatedTo and NFR-7's impact); a reference is resolved to the title
    and page of the record it names (`catalog_get`), because an artifact IRI has no prefLabel and a bullet
    reading `01J9X5M2ABC…` is a worse answer than none.

    ONE gateway session for all of it: a round trip per record trips the fabric's own rate limit at about
    sixty (measured 10 Oct 2026, `corpus_view`), and a record about three concepts would otherwise pay four.

    Returns (targets, concepts). Best effort as a WHOLE: a lookup that fails leaves the page plain rather than
    broken — the one outcome worse than plain text is a link to a page nobody wrote — and never costs the
    record its page. All-or-nothing because the failure a batch can have is its transport or its grant, which
    would have refused each call on its own just the same."""
    links = row.get("links") or []
    subjects = _one_per_object(l for l in links if l.get("predicate") == short(SUBJECT))
    refs = _one_per_object(l for l in links if l.get("predicate") == short(REFERENCES))
    if not subjects and not refs:
        return {}, []                            # the common case for a freshly swept document: ask nothing
    try:
        answers = await call(
            [(SemanticTools.trace, {"start": str(l.get("object") or ""), "predicates": [SUBJECT],
                                    "rungs": list(IMPACT_READS), "depth": 1, "inbound": True}) for l in subjects]
            + [(SemanticTools.catalog_get, {"iri": str(l.get("object") or "")}) for l in refs])
    except Exception as e:                       # noqa: BLE001 — the links are extra; the record is the work
        print(f"[projector] {row.get('iri')}: subjects and references left unlinked "
              f"({type(e).__name__}: {e})", flush=True)
        return {}, []
    about = [_coerce(a) or [] for a in answers[:len(subjects)]]
    named = [_coerce(a) or {} for a in answers[len(subjects):]]
    pages = _page_names({str(h.get("iri") or "") for hits in about for h in hits}
                        | {str(l.get("object") or "") for l in refs}, client=client)
    pages[str(row.get("iri") or "")] = record_name(row)   # ...its own page, written later in this same run
    targets, concepts = {}, []
    for link, hits in zip(subjects, about):
        iri, label = str(link.get("object") or ""), _label(link)
        concepts.append({"iri": iri, "label": label, "scheme": _scheme(iri), "name": concept_name(iri, label),
                         "records": [{"iri": str(h.get("iri") or ""), "title": str(h.get("title") or ""),
                                      "state": str(h.get("state") or ""), "rung": str(h.get("rung") or ""),
                                      "page": pages.get(str(h.get("iri") or ""), "")}
                                     # belt and braces over `G.traverse`, which already skips its start node
                                     for h in hits if str(h.get("iri") or "") != iri]})
        targets[iri] = {"label": label, "page": concepts[-1]["name"]}
    for link, ref_row in zip(refs, named):
        iri = str(link.get("object") or "")
        # The index first; failing that the record's OWN `projection_url`, which this projector wrote — and
        # that URL, not a file name derived from the row. `page_stem` is a function of the TITLE, so a record
        # renamed since it published has its page at the old slug and a derived name would point at a file
        # nobody ever wrote. The index starts empty, so on the first sweep over an existing catalogue this is
        # every reference; an absolute link is followed by Obsidian and SharePoint alike.
        file = pages.get(iri) or str(ref_row.get("projection_url") or "")
        targets[iri] = {"label": str(ref_row.get("title") or "") or _label(link), "page": file}
    return targets, concepts


def _one_per_object(links) -> list[dict]:
    """The first link per object IRI, in the order the record reports them. ONE home, used by the renderer and
    by the resolver: `catalog_get` enumerates a record's links across every rung graph, so the same subject
    asserted at two rungs arrives twice — two trace calls, two writes of one file, and the concept named twice
    on the page as though it were two."""
    out: dict[str, dict] = {}
    for l in links:
        out.setdefault(str(l.get("object") or ""), l)
    return list(out.values())


def _coerce(answer):
    """An MCP result arrives as JSON text or as the object (AF #3313 — and the fakes send the object)."""
    return json.loads(answer) if isinstance(answer, str) else answer


def _scheme(iri: str) -> str:
    """The vocabulary an IRI belongs to: `urn:lab:semantic:ref:syn#c1` -> `syn`. What a reader needs to tell
    two concepts spelled the same apart, and all the IRI carries."""
    return str(iri).split("#", 1)[0].rsplit(":", 1)[-1]


def _page_names(iris, *, client=None) -> dict[str, str]:
    """The file each record's page was written as, from the projector's own index."""
    want = sorted(i for i in iris if i)
    if not want or client is None:
        return {}
    try:
        got = client.hmget(PAGES_KEY, want)
    except Exception as e:                       # noqa: BLE001 — without the index a page is plain, not broken
        print(f"[projector] page index unreadable, links left plain ({type(e).__name__}: {e})", flush=True)
        return {}
    return {i: str(v) for i, v in zip(want, got or []) if v}


def _remember_page(iri: str, name: str, *, client=None) -> None:
    """Remember what this record's page is called, so another record's page can link to it. Nothing written
    means nothing to remember (no folder, or a write that failed). Best effort, like `_record_page`: losing an
    index entry costs a link until that record publishes again, and raising here would cost the page."""
    if client is None or not iri or not name:
        return
    try:
        client.hset(PAGES_KEY, iri, name)
    except Exception as e:                       # noqa: BLE001
        print(f"[projector] {iri}: page written but not indexed ({type(e).__name__}: {e})", flush=True)


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
        view = _coerce((await call([(SemanticTools.topology, {"iri": iri})]))[0])
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
        view = _coerce((await call([(SemanticTools.view_corpus, {})]))[0])
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
    stored = _coerce((await call([(SemanticTools.store_page, {"text": text, "name": name})]))[0])
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
    put = _coerce((await call([(CollabTools.put, {"folder": folder, "ref": ref, "name": name})]))[0])
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
