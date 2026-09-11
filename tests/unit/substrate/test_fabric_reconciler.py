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


def test_only_drive_entries_of_the_allowlist_are_swept():
    assert R.drives(("collab:drive-1", "collab:*", "work:proj", "lab:*", "collab:drive-2")) == ["drive-1", "drive-2"]


def test_decide_is_new_changed_or_nothing():
    item = {"folder": False, "handle": H1, "modified": "2026-09-10T00:00:00Z"}
    new = R.decide(item, None)
    assert new.change == "created" and new.pointer == {"source": "collab", "handle": H1, "version": "2026-09-10T00:00:00Z"}
    changed = R.decide(item, {"pointer": {"source": "collab", "handle": H1, "version": "2026-09-01T00:00:00Z"}})
    assert changed.change == "updated" and changed.occurred_at == "2026-09-10T00:00:00Z"
    assert R.decide(item, {"pointer": {"source": "collab", "handle": H1, "version": "2026-09-10T00:00:00Z"}}) is None
    assert R.decide({"folder": True, "handle": None}, None) is None
    assert R.decide({"folder": False, "handle": "https://not-a-handle"}, None) is None


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
