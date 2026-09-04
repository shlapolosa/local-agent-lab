"""src/lab/substrate/mcp/workflow/approval_tools.py — the human-in-the-loop GOVERNANCE surface on
workflow-mcp (list / read / decide an approval), through an in-memory fastmcp Client and a FakeRedis,
OFFLINE. Asserts the tool surface and its schemas, that the two read tools are read-only in fact (not
just by hint), that `approvals_decide` carries a real human and refuses a blank actor / an unknown id /
a request already decided, that a read-only grant cannot reach it, that the Teams channel and the tool
record IDENTICAL audit entries (one implementation), and that this role reaches no store.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/workflow/test_approval_tools.py"""
import ast
import asyncio
import os

import pytest
from fastmcp import Client

from fixtures.fakes import FakeRedis, patched_client
from lab.platform import config
from lab.platform.contracts import ApprovalKind, ApprovalTools, Decision, WorkflowTools
from lab.substrate import approvals
from lab.substrate.channels.teams import TeamsChannel
from lab.substrate.mcp.workflow import approval_tools as at
from lab.substrate.mcp.workflow import server as srv

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), *[".."] * 5))
TOOLS_FILE = os.path.join(ROOT, "src", "lab", "substrate", "mcp", "workflow", "approval_tools.py")

PAYLOAD = {"xml_ref": "art://x/claims.archimate.xml", "xlsx_ref": "art://x/claims.xlsx",
           "svg_refs": {"Overview": "art://x/overview.svg"},
           "summary": {"elements": 12, "relations": 9, "views": 2, "violations": 0, "warnings": 1,
                       "domain": "Claims", "decision": "UPDATE"}}


class Unreachable:
    """A store that fails on ANY use — proves the approval tools never touch an object store."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise AssertionError(f"workflow-mcp must hold no store: {name} was used")


@pytest.fixture
def redis():
    return FakeRedis()


@pytest.fixture
def server(redis):
    with srv.server.container.redis.override(redis), \
         srv.server.container.artifacts.override(Unreachable()), \
         srv.server.container.uploads.override(Unreachable()):
        yield srv.server


def call(server, _tool, **args):
    async def go():
        async with Client(server.mcp) as c:
            return await c.call_tool(_tool, args)
    return asyncio.run(go())


def call_error(server, _tool, **args) -> str:
    async def go():
        async with Client(server.mcp) as c:
            r = await c.call_tool(_tool, args, raise_on_error=False)
            assert r.is_error, f"{_tool} should have failed"
            return r.content[0].text
    return asyncio.run(go())


def tools(server):
    async def go():
        async with Client(server.mcp) as c:
            return {t.name: t for t in await c.list_tools()}
    return asyncio.run(go())


def seed(redis, subject="claims", kind=ApprovalKind.ADOIT_IMPORT.value, payload=None, trace="t" * 32):
    return approvals.request(kind, subject, PAYLOAD if payload is None else payload, "architect",
                             trace_id=trace, client=redis)


# ---------------------------------------------------------------- the tool surface
def test_the_three_approval_tools_join_the_process_tools_on_one_server(server):
    by = tools(server)
    assert ApprovalTools.names() == {"approvals_list", "approvals_get", "approvals_decide"} <= set(by)
    assert ApprovalTools.names() < WorkflowTools.names()          # one alias, one grant surface
    assert all(len(by[n].description or "") > 80 for n in ApprovalTools.names())


def test_the_read_tools_are_hinted_read_only_and_decide_is_hinted_a_write(server):
    by = tools(server)
    for name in ApprovalTools.READ:
        assert by[name].annotations.readOnlyHint is True, name
    d = by[ApprovalTools.decide].annotations
    # destructiveHint: approving RELEASES a repository write — a client that confirms before
    # destructive calls (Copilot Studio does) must confirm before this one.
    assert d.readOnlyHint is False and d.destructiveHint is True and d.idempotentHint is False


def test_decide_tells_the_caller_it_records_a_HUMAN_decision(server):
    doc = tools(server)[ApprovalTools.decide].description
    assert "HUMAN" in doc and "never" in doc.lower() and "actor" in doc
    assert "own initiative" in doc                                # an agent must not decide for itself


def test_schemas_are_self_describing(server):
    by = tools(server)
    ls = by[ApprovalTools.list].inputSchema
    assert ls.get("required", []) == [] and set(ls["properties"]) == {"kind", "limit"}
    assert ls["additionalProperties"] is False
    g = by[ApprovalTools.get].inputSchema
    assert g["required"] == ["request_id"] and set(g["properties"]) == {"request_id"}
    d = by[ApprovalTools.decide].inputSchema
    assert sorted(d["required"]) == ["actor", "decision", "request_id"]
    assert set(d["properties"]) == {"request_id", "decision", "actor", "comment", "channel"}
    assert d["properties"]["decision"]["enum"] == [x.value for x in Decision]
    assert "SIGNED-IN HUMAN" in d["properties"]["actor"]["description"]


# ---------------------------------------------------------------- list
def test_list_answers_what_a_reviewer_needs_to_triage(server, redis):
    rid = seed(redis)
    out = call(server, ApprovalTools.list).data
    assert out["count"] == 1 and out["review_app"] == config.REVIEW_APP_URL
    item, = out["approvals"]
    assert item["request_id"] == rid and item["kind"] == "adoit-import" and item["subject"] == "claims"
    assert item["requester"] == "architect" and item["status"] == "pending" and item["created_at"]
    assert item["summary"] == PAYLOAD["summary"]                       # the counts, verbatim
    assert "review_app" not in item                                    # once, on the envelope
    assert item["trace_url"].endswith("/trace/" + "t" * 32)
    assert item["decide_with"] == ApprovalTools.decide
    assert "xml_ref" not in item                                       # refs are the detail tool's job


def test_list_is_ordered_filtered_and_capped(server, redis):
    first, second = seed(redis, "alpha"), seed(redis, "beta", kind="other-kind")
    ids = [i["request_id"] for i in call(server, ApprovalTools.list).data["approvals"]]
    assert ids == [first, second]                                      # oldest first (insertion order)
    only = call(server, ApprovalTools.list, kind="other-kind").data
    assert [i["request_id"] for i in only["approvals"]] == [second] and only["count"] == 1
    capped = call(server, ApprovalTools.list, limit=1).data
    assert [i["request_id"] for i in capped["approvals"]] == [first]
    assert capped["count"] == 1 and capped["open_total"] == 2          # capped, but says how many exist


def test_list_of_nothing_says_so(server):
    out = call(server, ApprovalTools.list).data
    assert out["count"] == 0 and out["approvals"] == [] and out["open_total"] == 0


def test_a_request_awaiting_changes_stays_open_and_keeps_its_comment(server, redis):
    rid = seed(redis)
    call(server, ApprovalTools.decide, request_id=rid, decision="update", actor="maria",
         comment="rename the claims component")
    item, = call(server, ApprovalTools.list).data["approvals"]
    assert item["status"] == "update" and item["comment"] == "rename the claims component"
    assert item["decided_by"] == "maria"


# ---------------------------------------------------------------- get
def test_a_second_decider_loses_the_race_and_records_nothing(server, redis):
    """The finality guard is a CLAIM on approvals:pending, not a check-then-act — two channels
    deciding at once cannot both append a final answer."""
    rid = seed(redis)
    redis.s["approvals:pending"].discard(rid)          # the other decider claimed it a moment ago
    msg = call_error(server, ApprovalTools.decide, request_id=rid, decision="approve", actor="omar")
    assert "already" in msg and approvals.DEC not in redis.x


def test_get_returns_the_artifacts_a_human_judges_it_on(server, redis):
    rid = seed(redis)
    out = call(server, ApprovalTools.get, request_id=rid).data
    assert out["request_id"] == rid and out["open"] is True and out["status"] == "pending"
    assert out["summary"] == PAYLOAD["summary"]
    assert out["artifacts"] == {"xml_ref": PAYLOAD["xml_ref"], "xlsx_ref": PAYLOAD["xlsx_ref"],
                                "svg_refs": PAYLOAD["svg_refs"]}       # everything but the summary
    assert out["trace_id"] == "t" * 32 and out["trace_url"].endswith("t" * 32)
    assert out["review_app"] == config.REVIEW_APP_URL and out["decide_with"] == ApprovalTools.decide


def test_get_degrades_on_a_request_with_no_payload_or_trace(server, redis):
    rid = seed(redis, payload={}, trace=None)
    out = call(server, ApprovalTools.get, request_id=rid).data
    assert out["artifacts"] == {} and out["summary"] == {} and out["trace_url"] is None


def test_get_of_an_unknown_request_is_refused(server):
    assert "unknown request" in call_error(server, ApprovalTools.get, request_id="apr-nope")


def test_the_read_tools_never_mutate(server, redis):
    rid = seed(redis)
    before = ({k: dict(v) for k, v in redis.h.items()}, {k: set(v) for k, v in redis.s.items()},
              {k: list(v) for k, v in redis.x.items()})
    redis.calls.clear()
    call(server, ApprovalTools.list)
    call(server, ApprovalTools.get, request_id=rid)
    assert not {"xadd", "hset", "sadd", "srem", "delete", "set", "expire"} & set(redis.calls)
    assert ({k: dict(v) for k, v in redis.h.items()}, {k: set(v) for k, v in redis.s.items()},
            {k: list(v) for k, v in redis.x.items()}) == before


# ---------------------------------------------------------------- decide
@pytest.mark.parametrize("decision", [d.value for d in Decision])
def test_decide_records_every_decision_value_with_the_deciding_human(server, redis, decision):
    rid = seed(redis)
    out = call(server, ApprovalTools.decide, request_id=rid, decision=decision,
               actor="maria@contoso.com", comment=" looks right ", channel="teams").data
    assert out["request_id"] == rid and out["decision"] == decision and out["recorded"] is True
    assert out["actor"] == "maria@contoso.com" and out["channel"] == "mcp:teams"
    assert out["comment"] == "looks right" and out["decided_at"]
    assert out["status"] == decision and out["open"] is (decision == Decision.UPDATE.value)
    # the audit log (approvals:decisions) and the request hash both carry the human
    (_, entry), = redis.x[approvals.DEC]
    assert entry["actor"] == "maria@contoso.com" and entry["channel"] == "mcp:teams"
    st = approvals.status(rid, client=redis)
    assert st["decided_by"] == "maria@contoso.com" and st["decided_via"] == "mcp:teams"
    assert (rid in redis.smembers("approvals:pending")) is (decision == Decision.UPDATE.value)


def test_the_server_stamps_provenance_on_the_channel_the_caller_claims(server, redis):
    """A caller may say WHERE the human decided, but not that it happened anywhere but through this
    tool — so a connector cannot log a decision as one taken at the review app itself."""
    a, b, c = seed(redis, "a"), seed(redis, "b"), seed(redis, "c")
    out = call(server, ApprovalTools.decide, request_id=a, decision="approve", actor="maria").data
    assert out["channel"] == at.SOURCE == "mcp" and out["comment"] == ""      # nothing claimed
    assert call(server, ApprovalTools.decide, request_id=b, decision="approve", actor="maria",
                channel="teams").data["channel"] == "mcp:teams"
    spoof = call(server, ApprovalTools.decide, request_id=c, decision="approve", actor="maria",
                 channel="review-app").data
    assert spoof["channel"] == "mcp:review-app" and spoof["channel"] not in approvals.CHANNELS


@pytest.mark.parametrize("actor", ["", "   "])
def test_decide_refuses_a_blank_actor_and_records_nothing(server, redis, actor):
    rid = seed(redis)
    msg = call_error(server, ApprovalTools.decide, request_id=rid, decision="approve", actor=actor)
    assert "actor is required" in msg
    assert approvals.DEC not in redis.x and approvals.status(rid, client=redis)["status"] == "pending"


def test_decide_without_an_actor_argument_is_refused_by_the_schema(server, redis):
    seed(redis)
    assert call_error(server, ApprovalTools.decide, request_id="apr-1", decision="approve")
    assert approvals.DEC not in redis.x


def test_decide_refuses_an_unknown_request(server, redis):
    assert "unknown request" in call_error(server, ApprovalTools.decide, request_id="apr-nope",
                                           decision="approve", actor="maria")
    assert approvals.DEC not in redis.x


def test_decide_refuses_an_unknown_decision_value(server, redis):
    rid = seed(redis)
    assert call_error(server, ApprovalTools.decide, request_id=rid, decision="frobnicate", actor="maria")
    assert approvals.DEC not in redis.x


def test_a_final_decision_is_not_re_decided(server, redis):
    rid = seed(redis)
    call(server, ApprovalTools.decide, request_id=rid, decision="approve", actor="maria")
    msg = call_error(server, ApprovalTools.decide, request_id=rid, decision="decline", actor="omar")
    assert "already approve" in msg and "maria" in msg
    assert len(redis.x[approvals.DEC]) == 1                       # the second attempt recorded nothing
    assert approvals.status(rid, client=redis)["decided_by"] == "maria"


def test_changes_requested_can_still_be_decided_later(server, redis):
    rid = seed(redis)
    call(server, ApprovalTools.decide, request_id=rid, decision="update", actor="maria", comment="rename")
    out = call(server, ApprovalTools.decide, request_id=rid, decision="approve", actor="maria").data
    assert out["status"] == "approve" and out["open"] is False


# ---------------------------------------------------------------- governance
def test_a_read_only_grant_cannot_decide(server):
    """The gateway grants tools per team (`mcp_tool_permissions`); ApprovalTools.READ IS that
    read-only grant, so a team holding it sees no tool that can write a decision."""
    assert ApprovalTools.decide not in ApprovalTools.READ
    assert set(ApprovalTools.READ) | set(ApprovalTools.WRITE) == ApprovalTools.names()
    granted = {n: t for n, t in tools(server).items() if n in ApprovalTools.READ}
    assert set(granted) == set(ApprovalTools.READ)
    assert all(t.annotations.readOnlyHint for t in granted.values())


def test_the_teams_channel_and_the_tool_record_identical_decisions(server, redis):
    """DRY: the Teams inbound path and the MCP tool are two CLIENTS of one implementation
    (approvals.human_decision) — same validation, same audit entry."""
    a, b = seed(redis, "one"), seed(redis, "two")
    via_tool = call(server, ApprovalTools.decide, request_id=a, decision="approve",
                    actor="maria@contoso.com", channel="teams").data
    with patched_client(redis):
        via_teams = TeamsChannel("").decide(b, "approve", " maria@contoso.com ")
        for bad in ("", "   "):                       # the SAME refusal, not a second implementation
            with pytest.raises(ValueError, match="actor is required"):
                TeamsChannel("").decide(b, "approve", bad)
    assert via_teams == {"request_id": b, "decision": "approve", "actor": "maria@contoso.com",
                         "channel": "teams", "comment": "", "decided_at": via_teams["decided_at"]}
    # identical in every respect EXCEPT the provenance the server stamps on a relayed decision
    skip = {"request_id", "decided_at", "channel"}
    assert {k: via_tool[k] for k in via_teams if k not in skip} == \
           {k: v for k, v in via_teams.items() if k not in skip}
    assert via_tool["channel"] == "mcp:teams" and via_teams["channel"] == "teams"
    src = open(os.path.join(ROOT, "src", "lab", "substrate", "channels", "teams.py"), encoding="utf-8").read()
    assert "human_decision" in src and "actor is required" not in src   # no second validator


# ---------------------------------------------------------------- least privilege
def test_this_role_reaches_no_store(server, redis):
    rid = seed(redis)
    call(server, ApprovalTools.list)
    call(server, ApprovalTools.get, request_id=rid)
    call(server, ApprovalTools.decide, request_id=rid, decision="approve", actor="maria")
    tree = ast.parse(open(TOOLS_FILE, encoding="utf-8").read())
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0].value, "value", None), str)}
    code = "\n".join(ast.unparse(n) for n in ast.walk(tree)
                     if isinstance(n, (ast.Attribute, ast.Name, ast.Constant)) and id(n) not in docs)
    assert "approvals.human_decision" in code and "container.redis" in code
    # no store is ever REACHED: "artifacts" appears only as a result key naming the art:// refs
    attrs = "\n".join(ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Attribute))
    assert "artifacts" not in attrs and "uploads" not in attrs
    for forbidden in ("ARTIFACTS_URL", "UPLOADS_URL", "S3_", "DATABASE_URL", "GATEWAY_URL"):
        assert forbidden not in code, forbidden


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q", "-p", "no:warnings"]))
