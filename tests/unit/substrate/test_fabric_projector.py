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
    def __init__(self, row=ROW, put_error=None):
        self.row, self.put_error, self.calls = row, put_error, []

    async def __call__(self, calls):
        out = []
        for suffix, args in calls:
            self.calls.append((suffix, args))
            if suffix == SemanticTools.catalog_get:
                out.append(self.row)
            elif suffix == SemanticTools.store_spec:
                out.append({"spec_ref": f"art://store/{args['name']}"})
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
    assert out == [{"ref": "art://store/adr-14-event-bus.md", "handle": "collab://item/drive-1/page1", "name": "adr-14-event-bus.md",
                    "version": "2026-09-11T12:00:00Z"}]
    put = next(a for s, a in gw.calls if s == CollabTools.put)
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
    assert P.run_once(folder=WIKI, client=r, call=gw) and len([s for s, _ in gw.calls if s == CollabTools.put]) == 2
    assert r.get(P._key(rid)) == "1"


def test_without_a_wiki_folder_it_logs_and_writes_nothing(capsys):
    r, gw = FakeRedis(), Gateway()
    _finish(r, artifact_iri=IRI)
    out = P.run_once(folder="", client=r, call=gw)
    assert out[0]["handle"] == "" and "version" not in out[0] and CollabTools.put not in [s for s, _ in gw.calls]
    assert "would write adr-14-event-bus.md" in capsys.readouterr().out


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
