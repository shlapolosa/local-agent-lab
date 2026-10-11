"""The projector: a DONE publish run becomes one Markdown page in the wiki folder — metadata only, tagged as
fabric-written (the loop guard), remembered so a redelivery never writes twice, and left unacked when the
write fails so it is retried."""
import asyncio

from fixtures.fakes import FakeRedis
from lab.core.semantic.fabric.ontology import SUBJECT
from lab.core.semantic.fabric.rungs import IMPACT_READS, SUGGESTED
from lab.platform import fabric_events, workflows
from lab.platform.contracts import ARTIFACT_PUBLISH, CollabTools, SemanticTools, WorkflowStatus
from lab.substrate import fabric_projector as P

IRI = "urn:fabric:artifact:01J9X5K7QZ3M8N2P4R6T8V0W1Y"
REFERENCED = "urn:fabric:artifact:01J9X5M2ABCDEFGHJKMNPQRSTV"
CONCEPT = "urn:lab:semantic:ref:syn#c1"
ROW = {"iri": IRI, "title": "ADR-14 Event bus", "document_type": "urn:fabric:scheme:doc-types#decision-record",
       "state": "published", "baseline_version": "3", "owner": "urn:fabric:person:oid-1", "sensitivity_label": "Confidential",
       "pointer": {"source": "collab", "handle": "collab://item/drive-1/doc7"},
       "links": [{"predicate": "deliveredUnder", "rung": "H", "object": "urn:fabric:context:usecase:UC-42"},
                 # a concept link carries the LABEL the fabric resolved — `catalog_get` adds it whenever the
                 # concept has a prefLabel, which is every seeded concept, so a fixture without one was not
                 # a real row (and it is what the page's link text must read)
                 {"predicate": "subject", "rung": "X", "object": "urn:lab:semantic:ref:syn#c1",
                  "label": "Care Delivery"},
                 {"predicate": "references", "rung": "X", "object": REFERENCED}]}
WIKI = "collab://item/drive-1/wiki"


def test_the_page_is_metadata_and_links_never_content():
    md = P.page(ROW)
    assert md.startswith("---\n") and 'fabric_iri: "urn:fabric:artifact:01J9X5K7QZ3M8N2P4R6T8V0W1Y"' in md
    assert 'document_type: "decision-record"' in md and 'fabric_tag: "projection"' in md
    assert "- usecase:UC-42" in md and "- Care Delivery" in md and "# ADR-14 Event bus" in md
    assert 'subjects: ["Care Delivery"]' in md          # the label, not the hashed concept id a reader cannot read
    assert "`collab:collab://item/drive-1/doc7`" in md and "baseline 3" in md
    assert P.slug("ADR-14 Event bus!!") == "adr-14-event-bus" and P.slug("") == "record"


#: what `semantic_trace` answers for the concept: the catalogue rows about it, this record among them.
ABOUT = [{"iri": IRI, "distance": 1, "rung": "X", "title": "ADR-14 Event bus",
          "document_type": "urn:fabric:scheme:doc-types#decision-record", "state": "published", "owner": ""},
         {"iri": "urn:fabric:artifact:01J9OLDERRECORD00000000000", "distance": 1, "rung": "H",
          "title": "Triage BRS", "document_type": "", "state": "pending", "owner": ""}]
#: ...and the row the reference names, which has a page of its own
REFERENCED_ROW = {"iri": REFERENCED, "title": "Minutes 3 Oct", "state": "published",
                  "projection_url": "https://t/minutes", "pointer": {"source": "collab", "handle": "collab://d/i9"},
                  "links": []}


class Gateway:
    def __init__(self, row=ROW, put_error=None, topology_error=None, suffix=".html", assert_error=None,
                 corpus_error=None, about=None, trace_error=None, referenced=REFERENCED_ROW):
        self.row, self.put_error, self.calls = row, put_error, []
        self.topology_error, self.suffix, self.assert_error = topology_error, suffix, assert_error
        self.corpus_error, self.referenced = corpus_error, referenced
        self.about = ABOUT if about is None else about
        self.trace_error = trace_error

    async def __call__(self, calls):
        out = []
        for suffix, args in calls:
            self.calls.append((suffix, args))
            if suffix == SemanticTools.catalog_get:
                out.append(self.referenced if args.get("iri") == REFERENCED else self.row)
            elif suffix == SemanticTools.trace:
                if self.trace_error:
                    raise self.trace_error
                out.append(self.about)
            elif suffix == SemanticTools.store_spec:
                out.append({"spec_ref": f"art://store/{args['name']}"})
            elif suffix == SemanticTools.store_page:
                out.append({"ref": f"art://store/{args['name']}", "name": args["name"]})
            elif suffix == SemanticTools.topology:
                if self.topology_error:
                    raise self.topology_error
                out.append({"ref": f"art://store/adr-14-event-bus.topology{self.suffix}", "suffix": self.suffix,
                            "media_type": "text/html", "nodes": 3, "edges": 2, "title": "ADR-14 Event bus",
                            "concepts": ["Care Delivery", "Triage"], "statuses": ["focus", "X", "vocabulary"]})
            elif suffix == SemanticTools.view_corpus:
                if self.corpus_error:
                    raise self.corpus_error
                out.append({"ref": f"art://store/documentation-fabric-corpus{self.suffix}", "suffix": self.suffix,
                            "media_type": "text/html", "nodes": 105, "edges": 157, "records": 61,
                            "title": "The documentation fabric's corpus", "subtitle": "61 records · 44 concepts",
                            "concepts": [f"c{i}" for i in range(44)], "statuses": ["published", "vocabulary"]})
            elif suffix == SemanticTools.catalog_assert:
                if self.assert_error:
                    raise self.assert_error
                out.append({"assertion": "urn:fabric:assertion:1", "rung": args["rung"], "unchanged": False})
            elif suffix == CollabTools.put:
                if self.put_error:
                    raise self.put_error
                out.append({"handle": "collab://item/drive-1/page1", "name": args["name"], "url": "https://t/p",
                            "modified": "2026-09-11T12:00:00Z"})
        return out


def _finish(r, process=ARTIFACT_PUBLISH.name, **fields):
    workflows.ensure_finished_group(P.GROUP, r)
    inputs = {"artifact_iri": IRI, "approval_id": "apr-0123456789ab"} if process == ARTIFACT_PUBLISH.name else \
        {"transcript": "art://t/x.json", "speaker_map": {"S": {"tag": "x"}}}
    rid, _ = workflows.submit(process, inputs, "test", client=r)
    workflows.mark(rid, WorkflowStatus.DONE.value, client=r, **fields)
    return rid


def test_a_finished_publish_run_is_projected_tagged_and_acked():
    r, gw = FakeRedis(), Gateway()
    rid = _finish(r, artifact_iri=IRI)
    out = P.run_once(folder=WIKI, client=r, call=gw)
    assert len(out) == 1 and out[0].items() >= {"ref": "art://store/adr-14-event-bus.md", "name": "adr-14-event-bus.md",
                                                "handle": "collab://item/drive-1/page1",
                                                "version": "2026-09-11T12:00:00Z"}.items()
    put = next(a for s, a in gw.calls if s == CollabTools.put and a["name"] == "adr-14-event-bus.md")
    assert put == {"folder": WIKI, "ref": "art://store/adr-14-event-bus.md", "name": "adr-14-event-bus.md"}
    tag = fabric_events.written_by_fabric("collab:collab://item/drive-1/page1", "2026-09-11T12:00:00Z", client=r)
    assert tag["kind"] == "projection" and tag["version"] == "2026-09-11T12:00:00Z"
    # a LATER version of the page is a real change again — the guard is per version when the provider reports one
    assert fabric_events.written_by_fabric("collab:collab://item/drive-1/page1", "2026-09-12T00:00:00Z", client=r) is None
    st = workflows.status(rid, client=r)
    assert st["projection_ref"] == "art://store/adr-14-event-bus.md" and st["projection_handle"] == "collab://item/drive-1/page1"
    assert r.xpending(workflows.DONE, P.GROUP)["pending"] == 0
    # a redelivery writes nothing twice
    _finish(r, artifact_iri=IRI)
    # per RECORD: its page, the topology beside it, and one page per concept its subjects name
    assert P.run_once(folder=WIKI, client=r, call=gw)
    puts = [a["name"] for s, a in gw.calls if s == CollabTools.put]
    assert puts.count("adr-14-event-bus.md") == 2 and puts.count("adr-14-event-bus.topology.html") == 2
    assert puts.count("concept-syn-care-delivery.md") == 2
    assert r.get(P._key(rid)) == "1"


def test_without_a_wiki_folder_it_logs_and_writes_nothing(capsys):
    r, gw = FakeRedis(), Gateway()
    _finish(r, artifact_iri=IRI)
    out = P.run_once(folder="", client=r, call=gw)
    assert out[0]["handle"] == "" and "version" not in out[0] and CollabTools.put not in [s for s, _ in gw.calls]
    assert out[0]["topology"] == ""                       # nothing was written, so there is no link to offer
    printed = capsys.readouterr().out
    # both writes announce themselves: the page by its size, the drawing by the ref it would have written
    assert "would write adr-14-event-bus.md" in printed
    assert "would write adr-14-event-bus.topology.html" in printed
    assert "would write documentation-fabric-corpus.html" in printed


def test_a_failed_write_stays_unacked_and_is_noted_on_the_run():
    r, gw = FakeRedis(), Gateway(put_error=RuntimeError("tenant said no"))
    rid = _finish(r, artifact_iri=IRI)
    assert P.run_once(folder=WIKI, client=r, call=gw) == []
    assert r.xpending(workflows.DONE, P.GROUP)["pending"] == 1
    assert "tenant said no" in workflows.status(rid, client=r)["projection_error"]


def test_other_processes_and_unfinished_runs_are_acked_and_ignored():
    r, gw = FakeRedis(), Gateway()
    _finish(r, process="transcript_to_minutes")
    assert P.run_once(folder=WIKI, client=r, call=gw) == [] and gw.calls == []
    assert r.xpending(workflows.DONE, P.GROUP)["pending"] == 0
    assert asyncio.run(P.project({"status": "failed", "process": ARTIFACT_PUBLISH.name}, folder=WIKI, call=gw)) is None
    assert asyncio.run(P.project({"status": "done", "process": ARTIFACT_PUBLISH.name}, folder=WIKI, call=gw)) is None


def test_the_page_arrives_as_itself_not_wrapped_in_the_json_a_spec_would_need():
    r, gw = FakeRedis(), Gateway()
    _finish(r, artifact_iri=IRI)
    P.run_once(folder=WIKI, client=r, call=gw)
    stored = next(a for s, a in gw.calls if s == SemanticTools.store_page and a["name"].endswith("event-bus.md"))
    assert stored["name"] == "adr-14-event-bus.md" and stored["text"].startswith("---\n")
    assert not any(s == SemanticTools.store_spec for s, _ in gw.calls)      # a page is not a spec


def test_the_topology_is_drawn_beside_the_page_and_the_page_links_to_it():
    r, gw = FakeRedis(), Gateway()
    rid = _finish(r, artifact_iri=IRI)
    out = P.run_once(folder=WIKI, client=r, call=gw)
    drawn = next(a for s, a in gw.calls if s == SemanticTools.topology)
    assert drawn == {"iri": IRI}                       # drawn from the graph as it stands, not from the page
    puts = [a["name"] for s, a in gw.calls if s == CollabTools.put]
    # everything the record's page LINKS to is written before it — the drawing and the concept pages alike,
    # so the page never promises a file the folder does not yet hold
    assert puts == ["adr-14-event-bus.topology.html", "concept-syn-care-delivery.md", "adr-14-event-bus.md",
                    "documentation-fabric-corpus.html"]
    md = next(a["text"] for s, a in gw.calls if s == SemanticTools.store_page and a["name"].endswith("event-bus.md"))
    assert "https://t/p" in md and "2 concepts" in md   # the link a person opens, and what it holds
    assert out[0]["topology"] == "https://t/p"
    # on the run too, so whatever answers a person can offer the picture without drawing it again
    assert workflows.status(rid, client=r)["topology_url"] == "https://t/p"


def test_a_view_that_cannot_be_drawn_never_costs_the_page():
    r, gw = FakeRedis(), Gateway(topology_error=RuntimeError("renderer down"))
    _finish(r, artifact_iri=IRI)
    out = P.run_once(folder=WIKI, client=r, call=gw)
    assert out[0]["handle"] == "collab://item/drive-1/page1" and out[0]["topology"] == ""
    md = next(a["text"] for s, a in gw.calls if s == SemanticTools.store_page)
    assert "Topology" not in md                        # a link to a page that was never written is worse than none


def test_the_drawing_is_named_by_the_renderer_never_by_the_projector():
    """Which adapter draws is configuration. A projector that assumed HTML would break the day a raster or an
    interactive renderer is configured — the one change the renderer registry exists to make free."""
    r, gw = FakeRedis(), Gateway(suffix=".svg")
    _finish(r, artifact_iri=IRI)
    P.run_once(folder=WIKI, client=r, call=gw)
    assert [a["name"] for s, a in gw.calls if s == CollabTools.put][0] == "adr-14-event-bus.topology.svg"


def test_a_topology_written_but_not_tagged_fails_the_run_rather_than_feeding_the_fabric_its_own_drawing(monkeypatch):
    """The one failure the blanket guard must not swallow: the file is already in the folder, so leaving it
    untagged means the next sweep ingests the fabric's own picture as somebody's document."""
    r, gw = FakeRedis(), Gateway()
    rid = _finish(r, artifact_iri=IRI)
    real, seen = fabric_events.mark_written, []
    def boom(*a, **kw):                                   # ONLY the drawing's guard, after its put landed
        seen.append(1)
        if len(seen) == 1:
            raise ConnectionError("redis blip")
        return real(*a, **kw)
    monkeypatch.setattr(fabric_events, "mark_written", boom)
    assert P.run_once(folder=WIKI, client=r, call=gw) == []
    assert "projection_error" in workflows.status(rid, client=r)
    assert r.xpending(workflows.DONE, P.GROUP)["pending"] == 1      # unacked, so it is reclaimed and retried


def test_the_page_says_what_the_type_MEANS_not_the_iris_tail():
    """`doc-types#unknown` is the answer "I looked and none of these fits" — a decision somebody made.
    Rendered from the IRI's tail it reads `*unknown · published*`, which looks like a missing value, and
    that is how the first real record's page described a reviewer's deliberate answer (10 Oct 2026).
    `catalog_get` has already resolved the label; the page must not re-derive it worse."""
    row = {"iri": "urn:fabric:artifact:1", "title": "BRS.md", "state": "published",
           "document_type": "urn:fabric:scheme:doc-types#unknown",
           "pointer": {"source": "collab", "handle": "collab://d/i1"},
           "links": [{"predicate": "documentType", "object": "urn:fabric:scheme:doc-types#unknown",
                      "rung": "H", "label": "No type fits"}]}
    text = P.page(row)
    assert 'document_type: "No type fits"' in text and "*No type fits · published" in text
    assert "unknown" not in text

    # ...and with no label resolved it still degrades to the tail rather than to nothing
    bare = {**row, "links": [{"predicate": "documentType", "object": row["document_type"], "rung": "H"}]}
    assert 'document_type: "unknown"' in P.page(bare)


def test_the_page_url_is_recorded_ON_THE_RECORD_so_an_answer_can_hand_it_over():
    """Measured 10 Oct 2026: asked for a record's entry "and the link to its projection page", the Teams bot
    answered that the entry carries no such URL — right, and useless. The projector already knew it and put it
    on the RUN, which is not where a reader looks. Rung C, not D: the fabric's own deterministic projector
    CONSTRUCTED the location, and `graph_assert` refuses D outright ("derived is computed, not asserted")."""
    r, gw = FakeRedis(), Gateway()
    _finish(r, artifact_iri=IRI)
    P.run_once(folder=WIKI, client=r, call=gw)
    assert [a for s, a in gw.calls if s == SemanticTools.catalog_assert] == [
        {"iri": IRI, "field": "projection_url", "value": "https://t/p", "rung": "C", "method": "fabric-projector"}]
    # after the write, never before it: a URL recorded for a page that failed to land is a broken promise
    # (ORDER against the page's own put, not "the last call" — the corpus redraw now runs after both)
    names = [s for s, _ in gw.calls]
    assert names.index(SemanticTools.catalog_assert) > max(
        i for i, (s, a) in enumerate(gw.calls) if s == CollabTools.put and a["name"] == "adr-14-event-bus.md")


def test_a_link_that_cannot_be_recorded_never_undoes_the_page_that_was_written(capsys):
    """Best effort, like `link_runs`: the page is in the folder and tagged by the time this runs, so a
    catalogue that cannot be reached must leave the projection standing — losing the page would be far worse
    than losing the link to it."""
    r, gw = FakeRedis(), Gateway(assert_error=RuntimeError("semantic-mcp down"))
    rid = _finish(r, artifact_iri=IRI)
    out = P.run_once(folder=WIKI, client=r, call=gw)
    assert out and out[0]["handle"] == "collab://item/drive-1/page1"
    assert "semantic-mcp down" in capsys.readouterr().out
    st = workflows.status(rid, client=r)
    assert st["projection_ref"] == "art://store/adr-14-event-bus.md" and "projection_error" not in st
    assert r.xpending(workflows.DONE, P.GROUP)["pending"] == 0      # the work is done; the link is extra


def test_with_no_folder_there_is_no_url_to_record():
    r, gw = FakeRedis(), Gateway()
    _finish(r, artifact_iri=IRI)
    P.run_once(folder="", client=r, call=gw)
    assert not [a for s, a in gw.calls if s == SemanticTools.catalog_assert]


def test_the_whole_corpus_is_drawn_beside_the_record_under_ONE_fixed_name():
    """The catalogue page is a URL that should always be current, so it is overwritten rather than dated:
    `collab_put` replaces a file of the same name, and a `corpus-<date>.html` per publish would be a folder
    of stale pages with no way to tell which one a reader should open."""
    r, gw = FakeRedis(), Gateway()
    out = (_finish(r, artifact_iri=IRI), P.run_once(folder=WIKI, client=r, call=gw))[1]
    assert [a for s, a in gw.calls if s == SemanticTools.view_corpus] == [{}]   # the whole catalogue, unnarrowed
    corpus = next(a for s, a in gw.calls if s == CollabTools.put and a["name"].startswith("documentation-fabric-corpus"))
    assert corpus == {"folder": WIKI, "ref": "art://store/documentation-fabric-corpus.html",
                      "name": "documentation-fabric-corpus.html"}
    assert out[0]["corpus"] == "https://t/p"
    # ...and the drawing is tagged as fabric-written like every other fabric write, or the next sweep
    # ingests the fabric's own picture of itself as somebody's document
    assert fabric_events.written_by_fabric("collab:collab://item/drive-1/page1", "2026-09-11T12:00:00Z",
                                           client=r)["kind"] == "projection"


def test_the_corpus_page_is_named_by_the_renderer_never_by_the_projector():
    """Same reason as the record's topology: which adapter draws is configuration (`FABRIC_CORPUS_RENDERER`),
    and the focusless view has its own."""
    r, gw = FakeRedis(), Gateway(suffix=".svg")
    _finish(r, artifact_iri=IRI)
    P.run_once(folder=WIKI, client=r, call=gw)
    assert "documentation-fabric-corpus.svg" in [a["name"] for s, a in gw.calls if s == CollabTools.put]


def test_a_burst_of_publishes_redraws_the_whole_corpus_at_most_once_per_bound():
    """A whole-catalogue redraw is O(the catalogue) — measured 4.9 s at 61 records — and it runs in the same
    single consumer as the per-record pages, so N publishes in a sweep would pay N redraws of which N-1 are
    superseded within seconds while the records behind them wait. The RECORD's own page and catalogue entry
    are the authoritative, immediate writes; the corpus picture is a browsing surface, so it is bounded."""
    r, gw = FakeRedis(), Gateway()
    for _ in range(3):
        _finish(r, artifact_iri=IRI)
        P.run_once(folder=WIKI, client=r, call=gw)
    assert len([1 for s, _ in gw.calls if s == SemanticTools.view_corpus]) == 1
    assert len([1 for s, a in gw.calls if s == CollabTools.put and a["name"] == "adr-14-event-bus.md"]) == 3
    assert r.ttl.get(P.CORPUS_KEY) == P.CORPUS_EVERY_S     # it expires, so the page never stops being current
    r.kv.pop(P.CORPUS_KEY)                                 # the bound elapses
    _finish(r, artifact_iri=IRI)
    P.run_once(folder=WIKI, client=r, call=gw)
    assert len([1 for s, _ in gw.calls if s == SemanticTools.view_corpus]) == 2


def test_the_bound_is_claimed_after_the_write_so_a_failed_redraw_is_retried_not_suppressed():
    """The claim cannot come first: a put or a tag that fails leaves the run unacked to be reclaimed, and a
    bound already taken would skip the redraw on the retry — leaving a file in the folder that the loop guard
    never marked, which is exactly what it exists to stop."""
    r, gw = FakeRedis(), Gateway(put_error=RuntimeError("tenant said no"))
    _finish(r, artifact_iri=IRI)
    assert P.run_once(folder=WIKI, client=r, call=gw) == []
    assert r.get(P.CORPUS_KEY) is None


def test_a_corpus_that_cannot_be_drawn_never_undoes_the_record_that_just_published(capsys):
    """Best effort and SEPARATE from the record: the page, its topology and its catalogue link have all
    landed by the time this runs. A picture of the whole corpus is extra; the record is the work."""
    r, gw = FakeRedis(), Gateway(corpus_error=RuntimeError("renderer down"))
    rid = _finish(r, artifact_iri=IRI)
    out = P.run_once(folder=WIKI, client=r, call=gw)
    assert out and out[0]["handle"] == "collab://item/drive-1/page1" and out[0]["corpus"] == ""
    assert "renderer down" in capsys.readouterr().out
    st = workflows.status(rid, client=r)
    assert st["projection_ref"] == "art://store/adr-14-event-bus.md" and "projection_error" not in st
    assert r.xpending(workflows.DONE, P.GROUP)["pending"] == 0      # the record published; the corpus is extra


# --------------------------------------------------------------- T3.5: the pages are a graph a person can walk

def _bullets(md):
    """Every bullet the page renders — the only place a subject or a reference appears, so a topology link
    (which is a Markdown link and always has been) cannot be mistaken for one."""
    return [l for l in md.splitlines() if l.startswith("- ")]


def test_a_subject_and_a_reference_are_markdown_links_never_wikilinks():
    """The instrument for "does anybody actually wander this" is Obsidian, which renders both — but SharePoint,
    Copilot and every later renderer understand only standard Markdown, so the test tool must not dictate the
    syntax. The link text is the LABEL the fabric resolved, which is what a reader recognises."""
    md = P.page(ROW, targets={CONCEPT: {"label": "Care Delivery", "page": "concept-syn-care-delivery.md"},
                              REFERENCED: {"label": "Minutes 3 Oct", "page": "minutes-3-oct.md"}})
    assert "- [Care Delivery](concept-syn-care-delivery.md)" in md
    assert "- [Minutes 3 Oct](minutes-3-oct.md) (X)" in md
    assert "[[" not in md


def test_a_link_is_written_only_where_a_page_is():
    """A dead link is worse than plain text, because it looks like a promise. With nothing resolved the page
    reads exactly as it did before — and a target the caller resolved a LABEL but no page for is named, not
    linked: knowing what a reference IS called is worth having without pretending it leads somewhere."""
    assert not [b for b in _bullets(P.page(ROW)) if "](" in b]
    named = P.page(ROW, targets={REFERENCED: {"label": "Minutes 3 Oct", "page": ""}})
    assert "- Minutes 3 Oct (X)" in named and not [b for b in _bullets(named) if "](" in b]


def test_a_concept_page_is_the_records_about_it_and_links_the_ones_that_have_pages():
    md = P.concept_page({"iri": CONCEPT, "label": "Care Delivery", "scheme": "syn", "records": [
        {"iri": IRI, "title": "ADR-14 Event bus", "state": "published", "rung": "X", "page": "adr-14-event-bus.md"},
        {"iri": "urn:fabric:artifact:1", "title": "Triage BRS", "state": "pending", "rung": "H", "page": ""}]})
    assert md.startswith("---\n") and f'fabric_iri: "{CONCEPT}"' in md and 'fabric_tag: "projection"' in md
    assert 'kind: "concept"' in md and 'records: 2' in md and "# Care Delivery" in md
    assert "- [ADR-14 Event bus](adr-14-event-bus.md) — published (X)" in md
    assert "- Triage BRS — pending (H)" in md          # no page yet, so it is named rather than promised


def test_a_concept_page_says_nothing_it_was_not_given():
    """A card rendering a fixed shape with blanks was a real defect (`Elements ?` on a vocabulary card):
    absence stays absent, so a concept the fabric holds no records for has no heading for them."""
    md = P.concept_page({"iri": CONCEPT, "label": "", "scheme": "", "records": []})
    assert "Documents about this" not in md and "# c1" in md and 'records: 0' in md
    assert "*concept*" in md                       # and no dangling separator where the scheme would be


def test_two_vocabularies_may_hold_the_same_word_so_a_concept_page_is_scheme_qualified():
    """`vocab_conflicts` exists because a word can mean two things in two schemes. Naming the page by the
    label alone would silently overwrite one concept's page with the other's, and every link into it would
    then be about the wrong thing — which reads as the fabric asserting a match it never made."""
    assert P.concept_name(CONCEPT, "Care Delivery") == "concept-syn-care-delivery.md"
    assert P.concept_name("urn:lab:semantic:ref:cafe#x9", "Care Delivery") == "concept-cafe-care-delivery.md"
    assert P.concept_name(CONCEPT, "") == "concept-syn-c1.md"       # no label resolved: the id, never nothing


def test_the_concept_page_is_written_beside_the_record_and_tagged_like_every_fabric_write():
    r, gw = FakeRedis(), Gateway()
    out = (_finish(r, artifact_iri=IRI), P.run_once(folder=WIKI, client=r, call=gw))[1]
    put = next(a for s, a in gw.calls if s == CollabTools.put and a["name"].startswith("concept-"))
    assert put == {"folder": WIKI, "ref": "art://store/concept-syn-care-delivery.md",
                   "name": "concept-syn-care-delivery.md"}
    assert out[0]["concepts"] == ["concept-syn-care-delivery.md"]
    text = next(a["text"] for s, a in gw.calls if s == SemanticTools.store_page and a["name"].startswith("concept-"))
    # the record that just published is ON its concept's page, linked to the page written in the same run
    assert "- [ADR-14 Event bus](adr-14-event-bus.md) — published (X)" in text
    assert "- Triage BRS — pending (H)" in text
    # ...and the record's own page links out to it, so the walk goes both ways
    md = next(a["text"] for s, a in gw.calls if s == SemanticTools.store_page and a["name"].endswith("event-bus.md"))
    assert "[Care Delivery](concept-syn-care-delivery.md)" in md
    assert fabric_events.written_by_fabric("collab:collab://item/drive-1/page1", "2026-09-11T12:00:00Z",
                                           client=r)["kind"] == "projection"


def test_the_records_on_a_concept_page_come_from_the_trusted_rungs_only():
    """The same rule as `topology`'s relatedTo and as impact (NFR-7): a SUGGESTED subject is a model's guess,
    and listing it beside a confirmed one is how a page stops being evidence."""
    r, gw = FakeRedis(), Gateway()
    _finish(r, artifact_iri=IRI)
    P.run_once(folder=WIKI, client=r, call=gw)
    traces = [a for s, a in gw.calls if s == SemanticTools.trace]
    assert len(traces) == 1 and traces[0]["start"] == CONCEPT and traces[0]["predicates"] == [SUBJECT]
    assert traces[0]["inbound"] and traces[0]["depth"] == 1
    assert set(traces[0]["rungs"]) == set(IMPACT_READS) and SUGGESTED not in traces[0]["rungs"]


def test_a_reference_is_linked_only_when_the_record_it_names_has_a_page():
    r, gw = FakeRedis(), Gateway()
    _finish(r, artifact_iri=IRI)
    P.run_once(folder=WIKI, client=r, call=gw)
    md = next(a["text"] for s, a in gw.calls if s == SemanticTools.store_page and a["name"].endswith("event-bus.md"))
    # the record's OWN `projection_url`, not a file name derived from its title: `page_stem` is a function of
    # the title, so a record renamed since it published has its page at the old slug and a derived name would
    # point at a file nobody ever wrote
    assert "- [Minutes 3 Oct](https://t/minutes) (X)" in md
    # ...and a referenced record the projector has never written a page for is NAMED, never linked
    r2, gw2 = FakeRedis(), Gateway(referenced={"iri": REFERENCED, "title": "Minutes 3 Oct", "state": "pending",
                                               "pointer": {"source": "collab", "handle": "collab://d/i9"}})
    _finish(r2, artifact_iri=IRI)
    P.run_once(folder=WIKI, client=r2, call=gw2)
    md2 = next(a["text"] for s, a in gw2.calls if s == SemanticTools.store_page and a["name"].endswith("event-bus.md"))
    assert "- Minutes 3 Oct (X)" in md2 and "](" not in md2.split("## References", 1)[1].split("##", 1)[0]


def test_the_page_a_record_was_written_as_is_REMEMBERED_so_other_pages_can_link_to_it():
    """The projector's own memory of what it WROTE. The reader-facing fact stays `projection_url` on the
    record; this index exists because asking the catalogue per record costs one gateway call each, and a hot
    concept carries 39 of 93 records (measured 7 Oct 2026) while a round trip per record trips the fabric's
    own rate limit at about sixty (measured 10 Oct 2026)."""
    r, gw = FakeRedis(), Gateway()
    _finish(r, artifact_iri=IRI)
    P.run_once(folder=WIKI, client=r, call=gw)
    assert r.hget(P.PAGES_KEY, IRI) == "adr-14-event-bus.md"
    # it is used, not re-derived: a second record's reference to this one resolves from the index alone,
    # with no `projection_url` on the row it reads
    assert P._page_names({IRI, "urn:fabric:artifact:nope"}, client=r) == {IRI: "adr-14-event-bus.md"}
    assert P._page_names({IRI}, client=None) == {}
    # ...and with nothing written there is nothing to remember
    r2 = FakeRedis()
    _finish(r2, artifact_iri=IRI)
    P.run_once(folder="", client=r2, call=Gateway())
    assert r2.hget(P.PAGES_KEY, IRI) is None


def test_resolution_that_fails_leaves_the_page_PLAIN_rather_than_broken(capsys):
    """The one outcome worse than plain text is a link to a page nobody wrote. A lookup that cannot be made
    is therefore all-or-nothing for the links, and never costs the record its page."""
    r, gw = FakeRedis(), Gateway(trace_error=RuntimeError("semantic-mcp down"))
    out = (_finish(r, artifact_iri=IRI), P.run_once(folder=WIKI, client=r, call=gw))[1]
    assert out[0]["handle"] == "collab://item/drive-1/page1" and out[0]["concepts"] == []
    md = next(a["text"] for s, a in gw.calls if s == SemanticTools.store_page)
    # the LABEL the row already carried is still read (it needs no lookup); a reference, which has none,
    # falls back to the IRI's tail exactly as every other unresolved link on these pages does
    assert _bullets(md) == ["- usecase:UC-42", "- Care Delivery", "- 01J9X5M2ABCDEFGHJKMNPQRSTV (X)"]
    assert "semantic-mcp down" in capsys.readouterr().out
    assert r.xpending(workflows.DONE, P.GROUP)["pending"] == 0      # the record published; its links are extra


def test_a_record_about_nothing_and_referencing_nothing_asks_the_fabric_nothing():
    """No subjects and no references is the common case for a freshly swept document: it must not pay a
    gateway session to be told so."""
    bare = {"iri": IRI, "title": "ADR-14 Event bus", "state": "published",
            "pointer": {"source": "collab", "handle": "collab://d/i1"}, "links": []}
    r, gw = FakeRedis(), Gateway(row=bare)
    _finish(r, artifact_iri=IRI)
    P.run_once(folder=WIKI, client=r, call=gw)
    assert not [1 for s, _ in gw.calls if s == SemanticTools.trace]
    assert [a["name"] for s, a in gw.calls if s == CollabTools.put and a["name"].startswith("concept-")] == []


def test_a_concept_page_written_but_not_tagged_fails_the_run_like_any_other_fabric_write(monkeypatch):
    """Same boundary as the drawing: once the file is in the folder the write must complete, loop guard and
    all, or the next sweep ingests the fabric's own index page as somebody's document."""
    r, gw = FakeRedis(), Gateway()
    rid = _finish(r, artifact_iri=IRI)
    real, seen = fabric_events.mark_written, []
    def boom(*a, **kw):                                   # the SECOND write is the concept page
        seen.append(1)
        if len(seen) == 2:
            raise ConnectionError("redis blip")
        return real(*a, **kw)
    monkeypatch.setattr(fabric_events, "mark_written", boom)
    assert P.run_once(folder=WIKI, client=r, call=gw) == []
    assert "projection_error" in workflows.status(rid, client=r)
    assert r.xpending(workflows.DONE, P.GROUP)["pending"] == 1


def test_a_redis_blip_on_the_page_index_costs_a_link_never_a_page(capsys):
    """The index is the projector's memory, not its work: unreadable, the links it would have resolved are
    left plain; unwritable, this record's page is simply not linkable from elsewhere until it publishes again.
    Either way the page itself lands and the run is acked."""
    r, gw = FakeRedis(), Gateway()
    _finish(r, artifact_iri=IRI)
    r.fail("hmget")                                  # ...after the submit, which keeps its own hash
    out = P.run_once(folder=WIKI, client=r, call=gw)
    assert out[0]["handle"] == "collab://item/drive-1/page1"
    text = next(a["text"] for s, a in gw.calls if s == SemanticTools.store_page and a["name"].startswith("concept-"))
    # the record publishing THIS run is still linked — its page is written in this run, so the index is not
    # what tells the projector it exists; every other record is named rather than promised
    assert "- [ADR-14 Event bus](adr-14-event-bus.md) — published (X)" in text
    assert "- Triage BRS — pending (H)" in text
    assert "page index unreadable" in capsys.readouterr().out
    assert r.xpending(workflows.DONE, P.GROUP)["pending"] == 0
    # the WRITE side is best effort for the same reason — raising here would cost a page already in the folder
    r2 = FakeRedis()
    r2.fail("hset")
    P._remember_page(IRI, "adr-14-event-bus.md", client=r2)
    assert "page written but not indexed" in capsys.readouterr().out


def test_a_title_that_SLUGS_TO_NOTHING_still_names_its_own_file():
    """`file_slug` folds to ASCII and drops the rest, so every Arabic title returns its default — two records
    would share `record.md` while the page index pointed both IRIs at it, and a link would then resolve to a
    page about a different document. This lab's own corpus is bilingual (the speech bake-off exists because
    of it), so this is the expected case, not an exotic one."""
    a = {"iri": "urn:fabric:artifact:01J9AAA", "title": "محضر الاجتماع"}
    b = {"iri": "urn:fabric:artifact:01J9BBB", "title": "تقرير التصميم"}
    assert P.record_name(a) != P.record_name(b) and P.record_name(a).endswith(".md")
    # ...and the same within ONE scheme, where the scheme qualifier cannot help
    assert P.concept_name("urn:lab:semantic:ref:cafe#c1", "تقديم الرعاية") != \
           P.concept_name("urn:lab:semantic:ref:cafe#c2", "إدارة الدواء")


def test_a_record_about_SEVERAL_concepts_pairs_every_answer_with_the_link_it_belongs_to():
    """One batch carries the subject traces and the reference rows in one list, so the slice that splits them
    is only exercised by a row with more than one subject — and a mis-paired answer would put one concept's
    records on another concept's page, which reads as the fabric asserting a match it never made."""
    second = "urn:lab:semantic:ref:syn#c2"
    row = {**ROW, "links": ROW["links"] + [{"predicate": "subject", "rung": "H", "object": second,
                                            "label": "Triage"}]}
    about = {CONCEPT: [ABOUT[0]], second: [ABOUT[1]]}

    class Split(Gateway):
        async def __call__(self, calls):
            out = await super().__call__(calls)
            for i, (suffix, args) in enumerate(calls):
                if suffix == SemanticTools.trace:
                    out[i] = about[args["start"]]
            return out

    r, gw = FakeRedis(), Split(row=row)
    _finish(r, artifact_iri=IRI)
    P.run_once(folder=WIKI, client=r, call=gw)
    pages = {a["name"]: a["text"] for s, a in gw.calls if s == SemanticTools.store_page}
    assert "ADR-14 Event bus" in pages["concept-syn-care-delivery.md"]
    assert "Triage BRS" in pages["concept-syn-triage.md"]
    assert "Triage BRS" not in pages["concept-syn-care-delivery.md"]      # no answer on the wrong page
    # ...and the reference row still belongs to the reference, not to a trace
    assert "- [Minutes 3 Oct](https://t/minutes) (X)" in pages["adr-14-event-bus.md"]
    assert "[Triage](concept-syn-triage.md)" in pages["adr-14-event-bus.md"]


def test_the_name_the_PROVIDER_answered_with_is_what_other_pages_link_to():
    """`write_ref` already honours `put.name` over the name it asked for, because a provider may answer with a
    different one. Indexing the requested name would point the next record's link at a file that is not
    there."""
    class Renames(Gateway):
        async def __call__(self, calls):
            out = await super().__call__(calls)
            for i, (suffix, args) in enumerate(calls):
                if suffix == CollabTools.put:
                    out[i] = {**out[i], "name": f"copy-of-{args['name']}"}
            return out

    r, gw = FakeRedis(), Renames()
    out = (_finish(r, artifact_iri=IRI), P.run_once(folder=WIKI, client=r, call=gw))[1]
    assert r.hget(P.PAGES_KEY, IRI) == "copy-of-adr-14-event-bus.md"
    assert r.hget(P.PAGES_KEY, CONCEPT) == "copy-of-concept-syn-care-delivery.md"
    # the record's page points at the concept page that is THERE, which is known because it was written first
    md = next(a["text"] for s, a in gw.calls if s == SemanticTools.store_page and a["name"].endswith("event-bus.md"))
    assert "[Care Delivery](copy-of-concept-syn-care-delivery.md)" in md
    assert out[0]["concepts"] == ["copy-of-concept-syn-care-delivery.md"]


def test_one_subject_asserted_at_two_rungs_is_one_concept_page_not_two():
    """`catalog_get` reports a record's links across every rung graph, so the same subject promoted from X to H
    could arrive twice — two trace calls, two writes of one file, and the concept listed twice on the page."""
    row = {**ROW, "links": ROW["links"] + [{"predicate": "subject", "rung": "H", "object": CONCEPT,
                                            "label": "Care Delivery"}]}
    r, gw = FakeRedis(), Gateway(row=row)
    _finish(r, artifact_iri=IRI)
    P.run_once(folder=WIKI, client=r, call=gw)
    assert len([1 for s, _ in gw.calls if s == SemanticTools.trace]) == 1
    assert len([1 for s, a in gw.calls if s == CollabTools.put and a["name"].startswith("concept-")]) == 1
    md = next(a["text"] for s, a in gw.calls if s == SemanticTools.store_page and a["name"].endswith("event-bus.md"))
    assert md.count("[Care Delivery](concept-syn-care-delivery.md)") == 1


def test_a_concept_page_that_cannot_be_written_leaves_no_promise_in_the_record(capsys):
    """The rule `draw` states for the drawing, applied to the pages the record links to: the write that
    cannot complete happens BEFORE the page that would point at it, so the folder never holds a record page
    promising a file that is not there."""
    class NoConcepts(Gateway):
        async def __call__(self, calls):
            if any(s == CollabTools.put and a["name"].startswith("concept-") for s, a in calls):
                raise RuntimeError("tenant said no")
            return await super().__call__(calls)

    r, gw = FakeRedis(), NoConcepts()
    rid = _finish(r, artifact_iri=IRI)
    assert P.run_once(folder=WIKI, client=r, call=gw) == []
    assert not [1 for s, a in gw.calls if s == CollabTools.put and a["name"].endswith("event-bus.md")]
    assert "tenant said no" in workflows.status(rid, client=r)["projection_error"]
    assert r.xpending(workflows.DONE, P.GROUP)["pending"] == 1      # unacked, so the whole set is retried
