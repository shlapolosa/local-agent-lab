"""The projector: a DONE publish run becomes one Markdown page in the wiki folder — metadata only, tagged as
fabric-written (the loop guard), remembered so a redelivery never writes twice, and left unacked when the
write fails so it is retried."""
import asyncio

from fixtures.fakes import FakeRedis
from lab.platform import fabric_events, workflows
from lab.platform.contracts import ARTIFACT_PUBLISH, CollabTools, SemanticTools, WorkflowStatus
from lab.substrate import fabric_projector as P

IRI = "urn:fabric:artifact:01J9X5K7QZ3M8N2P4R6T8V0W1Y"
ROW = {"iri": IRI, "title": "ADR-14 Event bus", "document_type": "urn:fabric:scheme:doc-types#decision-record",
       "state": "published", "baseline_version": "3", "owner": "urn:fabric:person:oid-1", "sensitivity_label": "Confidential",
       "pointer": {"source": "collab", "handle": "collab://item/drive-1/doc7"},
       "links": [{"predicate": "deliveredUnder", "rung": "H", "object": "urn:fabric:context:usecase:UC-42"},
                 {"predicate": "subject", "rung": "X", "object": "urn:lab:semantic:ref:syn#c1"},
                 {"predicate": "references", "rung": "X", "object": "urn:fabric:artifact:01J9X5M2ABCDEFGHJKMNPQRSTV"}]}
WIKI = "collab://item/drive-1/wiki"


def test_the_page_is_metadata_and_links_never_content():
    md = P.page(ROW)
    assert md.startswith("---\n") and 'fabric_iri: "urn:fabric:artifact:01J9X5K7QZ3M8N2P4R6T8V0W1Y"' in md
    assert 'document_type: "decision-record"' in md and 'fabric_tag: "projection"' in md
    assert "- usecase:UC-42" in md and "- c1" in md and "# ADR-14 Event bus" in md
    assert "`collab:collab://item/drive-1/doc7`" in md and "baseline 3" in md
    assert P.slug("ADR-14 Event bus!!") == "adr-14-event-bus" and P.slug("") == "record"


class Gateway:
    def __init__(self, row=ROW, put_error=None, topology_error=None, suffix=".html", assert_error=None):
        self.row, self.put_error, self.calls = row, put_error, []
        self.topology_error, self.suffix, self.assert_error = topology_error, suffix, assert_error

    async def __call__(self, calls):
        out = []
        for suffix, args in calls:
            self.calls.append((suffix, args))
            if suffix == SemanticTools.catalog_get:
                out.append(self.row)
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
    put = next(a for s, a in gw.calls if s == CollabTools.put and a["name"].endswith(".md"))
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
    # two files per projected record now — the page and the topology beside it — and no more
    assert P.run_once(folder=WIKI, client=r, call=gw) and len([s for s, _ in gw.calls if s == CollabTools.put]) == 4
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
    stored = next(a for s, a in gw.calls if s == SemanticTools.store_page)
    assert stored["name"] == "adr-14-event-bus.md" and stored["text"].startswith("---\n")
    assert not any(s == SemanticTools.store_spec for s, _ in gw.calls)      # a page is not a spec


def test_the_topology_is_drawn_beside_the_page_and_the_page_links_to_it():
    r, gw = FakeRedis(), Gateway()
    rid = _finish(r, artifact_iri=IRI)
    out = P.run_once(folder=WIKI, client=r, call=gw)
    drawn = next(a for s, a in gw.calls if s == SemanticTools.topology)
    assert drawn == {"iri": IRI}                       # drawn from the graph as it stands, not from the page
    puts = [a["name"] for s, a in gw.calls if s == CollabTools.put]
    assert puts == ["adr-14-event-bus.topology.html", "adr-14-event-bus.md"]
    md = next(a["text"] for s, a in gw.calls if s == SemanticTools.store_page)
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
    assert [s for s, _ in gw.calls][-1] == SemanticTools.catalog_assert


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
