"""The reconciler: the allow-listed drives are listed to a bounded depth, each file is asked of the catalog,
and only what is new or changed becomes an event — on the same stream, in the same shape, as a notification."""
import asyncio

from fixtures.fakes import FakeRedis
from lab.platform import fabric_events
from lab.platform.contracts import CollabTools, SemanticTools
from lab.substrate import fabric_reconciler as R

H1, H2, H3 = "collab://item/drive-1/f1", "collab://item/drive-1/f2", "collab://item/drive-1/f3"
LISTING = {
    ("drive-1", ""): {"items": [{"name": "a.docx", "folder": False, "handle": H1, "modified": "2026-09-10T00:00:00Z"},
                                {"name": "sub", "folder": True, "handle": None},
                                {"name": "b.docx", "folder": False, "handle": H2, "modified": "2026-09-11T00:00:00Z"}]},
    ("drive-1", "sub"): {"items": [{"name": "c.docx", "folder": False, "handle": H3, "modified": "2026-09-09T00:00:00Z"},
                                   {"name": "deeper", "folder": True, "handle": None}]},
    ("drive-1", "sub/deeper"): {"items": [{"name": "d.docx", "folder": False, "handle": "collab://item/drive-1/f4",
                                           "modified": "2026-09-01T00:00:00Z"}]},
}
KNOWN = {H2: {"iri": "urn:fabric:artifact:x", "pointer": {"source": "collab", "handle": H2, "version": "2026-09-11T00:00:00Z"}},
         H3: {"iri": "urn:fabric:artifact:y", "pointer": {"source": "collab", "handle": H3, "version": "2026-09-01T00:00:00Z"}}}


class Gateway:
    def __init__(self):
        self.calls = []

    async def __call__(self, calls):
        self.batches = getattr(self, "batches", []) + [len(calls)]
        out = []
        for suffix, args in calls:
            self.calls.append((suffix, args))
            if suffix == CollabTools.list:
                out.append(LISTING.get((args["drive_id"], args["path"]), {"items": []}))
            elif suffix == SemanticTools.catalog_get:
                out.append(KNOWN.get(args["pointer"]["handle"]))
        return out


def test_only_drive_entries_of_the_allowlist_are_swept_from_their_folder():
    assert R.drives(("collab:drive-1", "collab:*", "work:proj", "lab:*", "collab:drive-2/Architectures")) == \
        [("drive-1", ""), ("drive-2", "Architectures")]


def test_decide_is_new_changed_or_nothing():
    item = {"name": "a.docx", "folder": False, "handle": H1, "modified": "2026-09-10T00:00:00Z"}
    new = R.decide(item, None)
    assert new.change == "created" and new.pointer == {"source": "collab", "handle": H1, "version": "2026-09-10T00:00:00Z"}
    changed = R.decide(item, {"pointer": {"source": "collab", "handle": H1, "version": "2026-09-01T00:00:00Z"}})
    assert changed.change == "updated" and changed.occurred_at == "2026-09-10T00:00:00Z"
    assert R.decide(item, {"pointer": {"source": "collab", "handle": H1, "version": "2026-09-10T00:00:00Z"}}) is None
    assert R.decide({"folder": True, "handle": None}, None) is None
    assert R.decide({"name": "a.docx", "folder": False, "handle": "https://not-a-handle"}, None) is None


def test_a_sweep_publishes_what_changed_recurses_to_depth_and_never_writes_the_catalog():
    r, gw = FakeRedis(), Gateway()
    events = asyncio.run(R.sweep(call=gw, allowlist=("collab:drive-1", "collab:*"), depth=1, limit=100, client=r))
    # a.docx unseen -> created; b.docx seen at this version -> nothing; c.docx seen at an older version -> updated;
    # d.docx is two levels down and depth is 1 -> never listed
    assert [(e.pointer["handle"], e.change) for e in events] == [(H1, "created"), (H3, "updated")]
    assert len(r.x[fabric_events.STREAM]) == 2
    listed = [a["path"] for s, a in gw.calls if s == CollabTools.list]
    assert listed == ["", "sub"]
    assert all(s in (CollabTools.list, SemanticTools.catalog_get) for s, _ in gw.calls)
    # ONE session per page: the root page's two files were asked of the catalog in one batch
    assert gw.batches == [1, 2, 1, 1]


def test_the_sweep_is_bounded_by_the_item_limit():
    r, gw = FakeRedis(), Gateway()
    events = asyncio.run(R.sweep(call=gw, allowlist=("collab:drive-1",), depth=3, limit=1, client=r))
    assert [e.pointer["handle"] for e in events] == [H1]


def test_run_once_never_raises(monkeypatch, capsys):
    from lab.platform import config
    monkeypatch.setattr(config, "FABRIC_ALLOWLIST", ("collab:drive-1",))

    async def boom(calls):
        raise RuntimeError("gateway down")
    assert R.run_once(call=boom, client=FakeRedis()) == []
    assert "sweep failed" in capsys.readouterr().out



def test_renewal_touches_only_the_labs_expiring_subscriptions():
    from datetime import datetime, timezone
    now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    calls = []

    async def gw(cs):
        out = []
        for s, a in cs:
            calls.append((s, a))
            if s == CollabTools.watches:
                out.append({"items": [
                    {"id": "ours-soon", "resource": "drives/d/root", "notification_url": "https://recv/notifications", "expires": "2026-09-14T00:00:00Z"},
                    {"id": "ours-fresh", "resource": "drives/d/root", "notification_url": "https://recv/notifications", "expires": "2026-09-30T00:00:00Z"},
                    {"id": "theirs", "resource": "drives/x/root", "notification_url": "https://flow.example/hook", "expires": "2026-09-12T13:00:00Z"},
                    {"id": "odd", "resource": "drives/d/root", "notification_url": "https://recv/notifications", "expires": "not-a-date"}]})
            else:
                out.append({"id": a["watch_id"], "expires": "2026-09-15T11:00:00Z"})
        return out
    renewed = asyncio.run(R.renew_watches(call=gw, receivers=("https://recv/notifications",), within_s=2 * 86400, now=now))
    assert [r["id"] for r in renewed] == ["ours-soon"] and renewed[0]["expires"] == "2026-09-15T11:00:00Z"
    assert [a for s, a in calls if s == CollabTools.watch_renew] == [{"watch_id": "ours-soon"}]


def test_the_first_sweep_waits_out_the_deploy_window(monkeypatch):
    """A sweep at boot queued runs that died at preflight while the gateway was still restarting."""
    import inspect
    src = inspect.getsource(R.main)
    assert "FABRIC_SWEEP_FIRST_S" in src and "on_start" not in src


def test_a_swept_item_carries_its_folder_path_on_the_pointer():
    ev = R.decide({"name": "a.docx", "folder": False, "handle": H1, "modified": "2026-09-10T00:00:00Z",
                   "path": "Architectures/2026"}, None)
    assert ev.pointer["path"] == "Architectures/2026"
    assert "path" not in R.decide({"name": "a.docx", "folder": False, "handle": H1,
                                   "modified": "2026-09-10T00:00:00Z"}, None).pointer


def test_run_once_sweeps_first_then_measures_and_remembers_the_numbers(monkeypatch):
    from lab.platform import config, fabric_events
    from lab.substrate import fabric_metrics
    monkeypatch.setattr(config, "FABRIC_ALLOWLIST", ("collab:drive-1",))
    monkeypatch.setattr(config, "FABRIC_WIKI_FOLDER", "collab://item/drive-1/root")
    order = []

    async def call(calls):
        out = []
        for suffix, args in calls:
            if suffix == "collab_list":
                order.append("sweep"); out.append({"items": []})
            elif suffix == "semantic_query":
                order.append("measure")
                name = next(k for k, q in fabric_metrics.QUERIES.items() if q == args["sparql"])
                out.append({"columns": ["state", "n"], "rows": []} if name == "states"
                           else {"columns": ["rung", "n"], "rows": []} if name == "delivery"
                           else {"columns": ["n"], "rows": [["0"]]})
            elif suffix == "semantic_store_page":
                out.append({"ref": "art://m/fabric-metrics.md", "name": args["name"]})
            elif suffix == "collab_put":
                out.append({"handle": "collab://item/drive-1/page", "name": args["name"]})
            else:
                out.append(None)
        return out
    r = FakeRedis()
    R.run_once(call=call, client=r)
    assert order and order[0] == "sweep" and "measure" in order
    assert r.get(fabric_events.METRICS_KEY) and r.get("fabric:written:collab:collab://item/drive-1/page")   # loop-guarded


def test_the_sweep_also_asks_the_steward_and_survives_a_question_that_fails(capsys, monkeypatch):
    """The questions ride the sweep's cadence, and like the measurements beside them they must not be able to
    stop it: a vocabulary the fabric cannot ask about is still a fabric that must keep ingesting."""
    from lab.substrate import fabric_reconciler as R, fabric_vocabulary as V

    async def boom(**kw):
        raise ConnectionError("gateway down")
    monkeypatch.setattr(V, "ask_open", boom)
    monkeypatch.setattr(R, "_ASKED", set())
    R.run_once(call=Gateway(), client=FakeRedis())
    assert "vocabulary questions failed" in capsys.readouterr().out


def test_the_sweep_says_what_it_saw_and_what_it_published_per_folder(capsys):
    """The instrument this needed. Measured 4 Oct 2026: four consecutive live ticks reported
    `swept: 1 change(s) published` while `decide()`, run by hand against the same catalogue, said ~69 of the
    listed files should have produced one — and there was no way to tell from outside which step lost them.
    A total is not an instrument: it cannot distinguish "listed nothing", "every file already known",
    "handles rejected" and "truncated at a page boundary", and those have different fixes."""
    gw, r = Gateway(), FakeRedis()
    asyncio.run(R.sweep(call=gw, allowlist=("collab:drive-1",), depth=2, limit=50, client=r))
    out = capsys.readouterr().out
    assert "drive-1" in out and "(root)" in out and "sub/deeper" in out   # names each folder reported on
    for word in ("listed", "files", "new"):
        assert word in out, f"the per-folder line must report {word}: {out!r}"
    # the root: 3 items listed, 2 of them files, 1 new (b.docx is known at the same version)
    assert "listed 3" in out and "files 2" in out and "new 1" in out


def test_a_truncated_listing_is_reported_rather_than_silently_short(capsys):
    """`collab_list` pages, and the sweep asks ONCE per folder and ignores `more`. A folder with more items
    than one page is then swept in part, for ever, with nothing saying so — which is indistinguishable from
    a folder that really holds that many."""
    class Paged(Gateway):
        async def __call__(self, calls):
            out = await Gateway.__call__(self, calls)
            return [{**o, "more": True, "cursor": "next"} if isinstance(o, dict) and "items" in o else o
                    for o in out]
    asyncio.run(R.sweep(call=Paged(), allowlist=("collab:drive-1",), depth=1, limit=50, client=FakeRedis()))
    printed = capsys.readouterr().out
    assert "TRUNCATED" in printed or "more" in printed, \
        f"an ignored `more` must be reported: {printed!r}"


def test_a_file_the_fabric_cannot_read_is_not_swept_into_the_catalogue():
    """An allow-listed folder is a FOLDER, not a promise about what people put in it. The organiser's
    Recordings folder holds 28 `.mp4` recordings and 42 per-lane `.json` dumps beside the transcripts the
    allow-list was added for, and nothing downstream filters by extension: the classifier reads a file's
    NAME and path, never its bytes, so a raw recording would be catalogued as a document with a plausible
    type and a draft-review approval — noise a steward cannot tell from a real document. Measured 6 Oct 2026;
    only `FABRIC_SWEEP_LIMIT` had kept the sweep from reaching them.

    The rule is what the fabric can READ (`filetypes.kind_for`), not a deny-list of what it has met: a
    deny-list is wrong about every format nobody has thought of yet, which is the direction surprises come
    from. A lab-produced artifact reaches the catalogue through the always-admitted `lab` door instead, so
    excluding `artifact` here loses nothing.
    """
    stamp = "2026-10-06T00:00:00Z"
    for name in ("Meeting Recording.mp4", "lane.segments.json", "book.xlsx", "notes"):
        item = {"name": name, "folder": False, "handle": H1, "modified": stamp}
        assert R.decide(item, None) is None, name
    for name in ("a.docx", "b.txt", "c.csv", "d.vtt", "e.vsdx", "f.png"):
        item = {"name": name, "folder": False, "handle": H1, "modified": stamp}
        assert R.decide(item, None) is not None, name


def test_an_unreadable_file_already_in_the_catalogue_still_reports_a_change():
    """The filter decides what the fabric TAKES IN, not what it maintains. A record that exists — swept in
    before this rule, or catalogued through the lab door — must still be told when its bytes change, or the
    catalogue would quietly state a version that is no longer true."""
    known = {"pointer": {"source": "collab", "handle": H1, "version": "2026-01-01T00:00:00Z"}}
    item = {"name": "Meeting Recording.mp4", "folder": False, "handle": H1, "modified": "2026-10-06T00:00:00Z"}
    assert R.decide(item, known).change == "updated"
