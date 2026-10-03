"""transcript_to_minutes — every lane scored against the tenant's own transcript, in ONE file.

The shape pinned: each lane, when it finishes, reads the sibling lanes' delivered transcripts beside
the same recording and rewrites `<recording>.comparison.txt` — so the last lane to finish leaves the
whole table, and no lane waits for another. Synthetic text throughout (this repository is public).
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/workloads/transcript_to_minutes/test_compare_with_reference.py"""
from lab.core.meetings import render
from lab.core.meetings.naming import Turn
from lab.workloads.transcript_to_minutes import workflow as W

from .test_workflow import _run, gw  # noqa: F401 - gw is a fixture

ITEM = {"id": "01FILE", "name": "weekly sync.mp4", "parent_handle": "collab://item/b!d/01FOLDER",
        "path": "Recordings", "created": "2026-09-29T07:20:44Z"}
VTT = """WEBVTT

00:00:03.000 --> 00:00:08.000
<v Maria Perez>Shall we start with the portal and then the budget</v>
"""
SIBLING = render.transcript([Turn("maria", 3.0, "Shall we start with the portal"),
                             Turn("Nabeel", 9.0, "الاتفاق إنه نبدأ")], title="weekly sync", lane="soniox")
LISTING = {"items": [
    {"name": "weekly sync.mp4", "handle": "collab://item/b!d/01FILE"},
    {"name": "weekly sync.soniox.transcript.txt", "handle": "collab://item/b!d/S1"},
    {"name": "weekly sync.soniox.minutes.txt", "handle": "collab://item/b!d/S2"},
    {"name": "weekly sync Copy.soniox.transcript.txt", "handle": "collab://item/b!d/C1"},   # another recording
    {"name": "weekly sync.comparison.txt", "handle": "collab://item/b!d/X"}]}


def wire(gw, monkeypatch, reference="art://v/teams.vtt"):  # noqa: F811
    stored, calls = {}, []

    async def fake(headers, mcp_url, batch):
        out = []
        for tool, args in batch:
            calls.append((tool, args))
            if tool == W.CollabTools.item:
                out.append(ITEM)
            elif tool == W.CollabTools.list:
                out.append(LISTING)
            elif tool == W.CollabTools.fetch:
                out.append({"ref": "art://f/" + args["handle"].rsplit("/", 1)[1]})
            elif tool == W.StorageTools.read_document:
                out.append(VTT if args["ref"] == reference else SIBLING)
            elif tool == W.SemanticTools.store_page:
                stored[args["name"]] = args["text"]
                out.append({"ref": f"art://s/{args['name']}"})
            elif tool == W.CollabTools.put:
                out.append({"name": args["name"], "handle": "h", "url": f"https://x/{args['name']}", "bytes": 1})
            else:
                out.append(gw.answers[tool])
        return out

    monkeypatch.setattr(W.gateway, "call_tools", fake)
    return stored, calls


def test_the_last_lane_to_finish_leaves_every_lane_scored_against_teams(gw, monkeypatch):  # noqa: F811
    stored, calls = wire(gw, monkeypatch)
    out = _run(provider="soniox-en", reference="art://v/teams.vtt", meeting={"id": "m", "recording": "collab://item/b!d/01FILE"})
    table = stored["weekly sync.comparison.txt"]
    rows = [l.split()[0] for l in table.splitlines() if l.startswith(("Microsoft", "soniox"))]
    assert rows == ["Microsoft", "soniox", "soniox-en"], "Teams first, then every lane, the copy excluded"
    assert out["comparison"] == "2 lane(s) compared: soniox, soniox-en"
    assert out["delivered"][-1]["name"] == "weekly sync.comparison.txt", "announced in the chat like the rest"
    fetched = [a["handle"] for t, a in calls if t == W.CollabTools.fetch]
    assert fetched == ["collab://item/b!d/S1"], "only a sibling LANE's transcript is read back — never a copy's"


def test_a_long_transcript_is_read_back_whole_not_at_a_model_s_cap(gw, monkeypatch):  # noqa: F811
    _, calls = wire(gw, monkeypatch)
    _run(provider="soniox-en", reference="art://v/teams.vtt", meeting={"id": "m", "recording": "collab://item/b!d/01FILE"})
    assert {a["max_chars"] for t, a in calls if t == W.StorageTools.read_document} == {W.READ_ALL}


def test_without_a_tenant_transcript_nothing_is_compared_and_it_says_so(gw, monkeypatch):  # noqa: F811
    stored, calls = wire(gw, monkeypatch)
    out = _run(provider="soniox-en", meeting={"id": "m", "recording": "collab://item/b!d/01FILE"})
    assert out["comparison"] == "no tenant transcript to compare with"
    assert "weekly sync.comparison.txt" not in stored and not any(t == W.CollabTools.list for t, _ in calls)


def test_a_comparison_that_fails_never_costs_the_minutes(gw, monkeypatch):  # noqa: F811
    wire(gw, monkeypatch)
    real = W.gateway.call_tools

    async def broken(headers, mcp_url, batch):
        if batch[0][0] == W.CollabTools.list:
            raise RuntimeError("the folder could not be listed")
        return await real(headers, mcp_url, batch)

    monkeypatch.setattr(W.gateway, "call_tools", broken)
    out = _run(provider="soniox-en", reference="art://v/teams.vtt", meeting={"id": "m", "recording": "collab://item/b!d/01FILE"})
    assert out["minutes_ref"] and "could not be listed" in out["comparison"]
