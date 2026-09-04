"""src/lab/substrate/mcp/workflow/server.py — the governed front door to every business process, through an
in-memory fastmcp Client and a FakeRedis, OFFLINE. Asserts the generated tool triple and its schemas,
submit's enqueue-and-acknowledge shape (non-blocking: no host runs, nothing waits), every input
validation failure, status/result across the whole lifecycle (incl. unknown and cross-process ids),
that the REGISTRY drives the tool list (a second, fake process yields its own three tools) and that
this role can reach no store credential.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/mcp/workflow/test_server.py"""
import ast
import asyncio
import os
import runpy

import pytest
from fastmcp import Client

from fixtures.fakes import FakeRedis
from lab.platform import config, workflows
from lab.platform.contracts import (PROCESSES, VISIO_TO_ARCHIMATE, ApprovalTools, InputField,
                                    InputKind, ProcessSpec, WorkflowStatus, WorkflowTools)
from lab.substrate.mcp.workflow import server as srv

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), *[".."] * 5))
SERVER_FILE = os.path.join(ROOT, "src", "lab", "substrate", "mcp", "workflow", "server.py")

FAKE = ProcessSpec(name="fake_process", group="wf-fake", title="Fake process",
                   description="Only tests register this.",
                   inputs=(InputField("primary", InputKind.REF, "the one ref"),
                           InputField("optional_one", InputKind.REF, "an optional single ref", required=False)),
                   outputs=("xml_ref",))


class Unreachable:
    """A store that fails on ANY use — proves the tools never touch an object store."""

    def __getattr__(self, name):
        if name.startswith("__"):                    # dependency_injector probes __IS_PROVIDER__ etc.
            raise AttributeError(name)
        raise AssertionError(f"workflow-mcp must hold no store: {name} was used")


@pytest.fixture
def redis():
    return FakeRedis()


@pytest.fixture
def server(redis):
    """The module-level server (built from the real PROCESSES) with Redis and both stores swapped."""
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


def submit(server, **args):
    return call(server, VISIO_TO_ARCHIMATE.tool("submit"), **args).data


# ---------------------------------------------------------------- the tool surface
def test_the_registry_drives_the_tool_list_and_the_contract_catalogue(server):
    by = tools(server)
    assert set(by) == WorkflowTools.names()
    # the process tools are exactly the registry's; the fixed approval gate rides on the same server
    assert set(by) - ApprovalTools.names() == {f"{p}_{v}" for p in PROCESSES
                                               for v in ("submit", "status", "result")}
    assert ApprovalTools.names() <= set(by)     # see tests/…/test_approval_tools.py for their behaviour
    assert all(by[n].description and len(by[n].description) > 80 for n in by), "an agent picks a tool by its description"


def test_adding_a_process_to_the_registry_adds_its_three_tools_and_nothing_else():
    built = srv.build({**PROCESSES, FAKE.name: FAKE})
    assert set(tools(built)) == WorkflowTools.names() | {"fake_process_submit", "fake_process_status",
                                                         "fake_process_result"}
    only = srv.build({FAKE.name: FAKE})                       # a registry of ONE process -> one triple
    assert set(tools(only)) - ApprovalTools.names() == {"fake_process_submit", "fake_process_status",
                                                        "fake_process_result"}
    schema = tools(only)["fake_process_submit"].inputSchema
    assert schema["required"] == ["primary"]
    assert set(schema["properties"]) == {"primary", "optional_one", "requester"}


def test_an_optional_single_reference_also_accepts_null(redis):
    """LLM clients fill every declared parameter — an optional ref must accept `null`, or pydantic
    rejects the call before InputField.coerce (which handles None) is ever reached."""
    built = srv.build({FAKE.name: FAKE})
    opt = tools(built)["fake_process_submit"].inputSchema["properties"]["optional_one"]
    assert {"type": "string"} in opt["anyOf"] and {"type": "null"} in opt["anyOf"]
    assert srv.annotation_of(FAKE.field("optional_one")) == (str | None)
    assert srv.annotation_of(FAKE.field("primary")) is str
    assert srv.annotation_of(VISIO_TO_ARCHIMATE.field("requirements")) == list[str]
    with built.container.redis.override(redis):
        out = call(built, "fake_process_submit", primary="art://a/b.png", optional_one=None).data
        assert workflows.status(out["request_id"], client=redis)["inputs"] == {"primary": "art://a/b.png"}


def test_submit_schema_is_self_describing(server):
    s = tools(server)[VISIO_TO_ARCHIMATE.tool("submit")].inputSchema
    assert s["required"] == ["diagram"] and set(s["properties"]) == {"diagram", "requirements", "requester"}
    assert s["properties"]["diagram"]["type"] == "string"
    assert "art://" in s["properties"]["diagram"]["description"]
    assert s["properties"]["requirements"] == {"default": [], "items": {"type": "string"}, "type": "array",
                                               "description": VISIO_TO_ARCHIMATE.field("requirements").description}
    assert s["properties"]["requester"]["default"] == "mcp"
    assert s["additionalProperties"] is False                  # a typo'd argument is refused, not dropped
    for verb in ("status", "result"):
        rs = tools(server)[VISIO_TO_ARCHIMATE.tool(verb)].inputSchema
        assert rs["required"] == ["request_id"] and set(rs["properties"]) == {"request_id"}


def test_descriptions_tell_an_agent_the_async_contract(server):
    by = tools(server)
    sub = by[VISIO_TO_ARCHIMATE.tool("submit")].description
    assert "IMMEDIATELY" in sub and VISIO_TO_ARCHIMATE.tool("status") in sub and "does NOT wait" in sub
    assert VISIO_TO_ARCHIMATE.tool("result") in by[VISIO_TO_ARCHIMATE.tool("status")].description
    assert "art://" in by[VISIO_TO_ARCHIMATE.tool("result")].description


# ---------------------------------------------------------------- submit
def test_submit_enqueues_one_request_and_returns_immediately(server, redis):
    out = submit(server, diagram="art://a/b.vsdx", requirements=["art://c/d.docx"], requester="copilot")
    rid = out["request_id"]
    assert rid.startswith("wfr-") and out["status"] == WorkflowStatus.PENDING.value and out["accepted"] is True
    assert out["process"] == "visio_to_archimate"
    assert out["poll_with"] == VISIO_TO_ARCHIMATE.tool("status") and out["result_with"] == VISIO_TO_ARCHIMATE.tool("result")
    assert redis.xlen(workflows.REQ) == 1                       # exactly ONE event published
    st = workflows.status(rid, client=redis)
    assert st["process"] == "visio_to_archimate" and st["requester"] == "copilot"
    assert st["inputs"] == {"diagram": "art://a/b.vsdx", "requirements": ["art://c/d.docx"]}
    assert rid in redis.smembers("workflow:pending")
    # non-blocking: the tool only WRITES the request — it never reads the stream or waits on a run
    assert not {"xreadgroup", "xack", "blpop", "brpop"} & set(redis.calls)


def test_submit_defaults_and_repeated_calls_are_distinct_runs(server, redis):
    a = submit(server, diagram="art://a/b.vsdx")
    assert workflows.status(a["request_id"], client=redis)["requester"] == "mcp"
    assert workflows.status(a["request_id"], client=redis)["inputs"]["requirements"] == []
    b = submit(server, diagram="art://a/b.vsdx")
    assert b["request_id"] != a["request_id"] and redis.xlen(workflows.REQ) == 2
    assert "do not re-submit" in b["note"]                      # the tool tells an agent not to retry-loop
    blank = submit(server, diagram="art://a/b.vsdx", requester="   ")
    assert workflows.status(blank["request_id"], client=redis)["requester"] == "mcp"


@pytest.mark.parametrize("args, message", [
    ({"diagram": "   "}, "diagram must be a non-empty reference"),
    ({"diagram": "art://onlyid"}, "malformed artifact ref"),
    ({"diagram": "https://example.com/x.vsdx"}, "is not an art:// reference"),
    ({"diagram": "art://a/b.vsdx", "requirements": ["art://bad"]}, "malformed artifact ref"),
    ({"diagram": "art://a/b.vsdx", "requirements": [""]}, "requirements must be a non-empty reference"),
])
def test_submit_rejects_bad_input_without_enqueueing(server, redis, args, message):
    assert message in call_error(server, VISIO_TO_ARCHIMATE.tool("submit"), **args)
    assert redis.xlen(workflows.REQ) == 0 and not redis.smembers("workflow:pending")


def test_submit_schema_rejects_the_wrong_shape_before_the_tool_runs(server, redis):
    assert call_error(server, VISIO_TO_ARCHIMATE.tool("submit"))                        # diagram missing
    assert call_error(server, VISIO_TO_ARCHIMATE.tool("submit"), diagram="art://a/b.vsdx",
                      requirements="art://c/d.docx")                                     # a string, not a list
    assert call_error(server, VISIO_TO_ARCHIMATE.tool("submit"), diagram="art://a/b.vsdx", page="P1")
    assert redis.xlen(workflows.REQ) == 0


# ---------------------------------------------------------------- status / result across the lifecycle
def test_status_follows_the_run(server, redis):
    rid = submit(server, diagram="art://a/b.vsdx", requester="ana")["request_id"]
    st = call(server, VISIO_TO_ARCHIMATE.tool("status"), request_id=rid).data
    assert st["status"] == "pending" and st["finished"] is False and st["requester"] == "ana"
    assert st["request_id"] == rid and st["created_at"] and st["inputs"]["diagram"] == "art://a/b.vsdx"

    workflows.mark(rid, WorkflowStatus.RUNNING, consumer="1", trace_id="t" * 32, client=redis)
    st = call(server, VISIO_TO_ARCHIMATE.tool("status"), request_id=rid).data
    assert st["status"] == "running" and st["finished"] is False
    assert st["trace_id"] == "t" * 32 and st["consumer"] == "1" and st["started_at"]

    workflows.mark(rid, WorkflowStatus.DONE, approval_id="apr-1", xml_ref="art://x/m.xml",
                   summary={"elements": 12}, client=redis)
    st = call(server, VISIO_TO_ARCHIMATE.tool("status"), request_id=rid).data
    assert st["status"] == "done" and st["finished"] is True and st["finished_at"]


def test_result_only_answers_when_the_run_finished(server, redis):
    rid = submit(server, diagram="art://a/b.vsdx")["request_id"]
    pending = call(server, VISIO_TO_ARCHIMATE.tool("result"), request_id=rid).data
    assert pending["finished"] is False and pending["status"] == "pending"
    assert VISIO_TO_ARCHIMATE.tool("status") in pending["message"] and "not finished yet" in pending["message"]

    workflows.mark(rid, WorkflowStatus.RUNNING, client=redis)
    assert call(server, VISIO_TO_ARCHIMATE.tool("result"), request_id=rid).data["finished"] is False

    workflows.mark(rid, WorkflowStatus.DONE, approval_id="apr-7", xml_ref="art://x/m.archimate.xml",
                   xlsx_ref="art://x/objects.xlsx", review_app="http://review", trace_id="a" * 32,
                   summary={"elements": 12, "relations": 9}, client=redis)
    out = call(server, VISIO_TO_ARCHIMATE.tool("result"), request_id=rid).data
    assert out["finished"] is True and out["status"] == "done" and out["request_id"] == rid
    assert out["approval_id"] == "apr-7" and out["xml_ref"] == "art://x/m.archimate.xml"
    assert out["xlsx_ref"] == "art://x/objects.xlsx" and out["review_app"] == "http://review"
    assert out["summary"] == {"elements": 12, "relations": 9} and out["trace_id"] == "a" * 32
    assert set(out) - {"request_id", "process", "status", "finished"} <= set(VISIO_TO_ARCHIMATE.outputs)


def test_result_of_a_failed_run_reports_the_error(server, redis):
    rid = submit(server, diagram="art://a/b.vsdx")["request_id"]
    workflows.mark(rid, WorkflowStatus.FAILED, error="ValueError: no shapes", client=redis)
    out = call(server, VISIO_TO_ARCHIMATE.tool("result"), request_id=rid).data
    assert out["status"] == "failed" and out["finished"] is True and out["error"] == "ValueError: no shapes"
    assert call(server, VISIO_TO_ARCHIMATE.tool("status"), request_id=rid).data["finished"] is True
    workflows.mark(rid, WorkflowStatus.FAILED, client=redis)                   # a failure with no message
    redis.h[f"workflow:req:{rid}"].pop("error")
    assert call(server, VISIO_TO_ARCHIMATE.tool("result"), request_id=rid).data["error"] == "the run failed"


def test_unknown_and_cross_process_ids_are_refused(server, redis):
    for verb in ("status", "result"):
        assert "unknown request" in call_error(server, VISIO_TO_ARCHIMATE.tool(verb), request_id="wfr-nope")
    # seed a SECOND process's request: `spec=` is how a caller with its own registry validates
    # (workflows.request refuses an unregistered process otherwise)
    other = workflows.request(FAKE.name, {"primary": "art://a/b.png"}, "tester", spec=FAKE, client=redis)
    for verb in ("status", "result"):
        msg = call_error(server, VISIO_TO_ARCHIMATE.tool(verb), request_id=other)
        assert "is a 'fake_process' run" in msg and "not 'visio_to_archimate'" in msg


# ---------------------------------------------------------------- least privilege + entry point
def test_this_role_reaches_no_store(server, redis):
    """Every tool runs green while both stores raise on any use — the server holds Redis only."""
    rid = submit(server, diagram="art://a/b.vsdx")["request_id"]
    workflows.mark(rid, WorkflowStatus.DONE, xml_ref="art://x/m.xml", client=redis)
    call(server, VISIO_TO_ARCHIMATE.tool("status"), request_id=rid)
    call(server, VISIO_TO_ARCHIMATE.tool("result"), request_id=rid)
    # and the CODE says so too: strip every docstring (prose may mention a store), scan what is left
    tree = ast.parse(open(SERVER_FILE, encoding="utf-8").read())
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0].value, "value", None), str)}
    code = "\n".join(ast.unparse(n) for n in ast.walk(tree)
                     if isinstance(n, (ast.Attribute, ast.Name, ast.Constant)) and id(n) not in docs)
    assert "workflows.request" in code and "container.redis" in code   # the scan really sees the bodies
    assert "artifacts" not in code and "uploads" not in code
    for forbidden in ("ARTIFACTS_URL", "UPLOADS_URL", "S3_", "DATABASE_URL", "GATEWAY_URL"):
        assert forbidden not in code, forbidden


def test_server_identity_and_main(server):
    assert srv.SERVICE == "workflow-mcp" and srv.server.service == "workflow-mcp"
    assert srv.server.port == config.WORKFLOW_MCP_PORT == 9400
    assert srv.server.mcp.name == "workflow-mcp"
    import lab.substrate.mcpserver as ms
    served, real = [], ms.serve
    ms.serve = lambda mcp, service, port, **kw: served.append((service, port))
    try:
        runpy.run_path(SERVER_FILE, run_name="__main__")
        assert served == [("workflow-mcp", config.WORKFLOW_MCP_PORT)]
    finally:
        ms.serve = real


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
