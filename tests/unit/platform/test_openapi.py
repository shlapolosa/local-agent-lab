"""The generated OpenAPI (Swagger 2.0) document — what a low-code client imports as a custom connector.

Power Platform imports Swagger 2.0 only, wants a unique `operationId` and a `summary` per operation,
declared path parameters, and a document under 1 MB. These tests hold the document to that, using
`lab.substrate.apipolicy.OPERATIONS` as the operation table — the same table the gateway enforces.
"""
import json
import re

import pytest

from lab.platform.contracts import PROCESSES, WorkflowTools
from lab.platform.openapi import openapi, path_template
from lab.substrate import apipolicy

BASE = "https://gateway.example.test"


@pytest.fixture(scope="module")
def doc():
    return openapi(BASE, apipolicy.OPERATIONS)


def _ops(doc):
    for path, item in doc["paths"].items():
        for method, op in item.items():
            yield path, method, op


def test_it_is_swagger_two_pointing_at_the_front_door(doc):
    assert doc["swagger"] == "2.0"
    assert doc["host"] == "gateway.example.test" and doc["schemes"] == ["https"]
    assert doc["basePath"] == apipolicy.API_PREFIX


def test_every_operation_has_a_unique_id_a_summary_and_a_response(doc):
    ids = [op["operationId"] for _, _, op in _ops(doc)]
    assert len(ids) == len(set(ids))
    for _, _, op in _ops(doc):
        assert op["summary"] and len(op["summary"]) <= 80 and not op["summary"].endswith(".")
        assert op["responses"]
        assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", op["operationId"]), op["operationId"]


def test_every_path_parameter_is_declared(doc):
    for path, _, op in _ops(doc):
        declared = {p["name"] for p in op.get("parameters", []) if p["in"] == "path"}
        assert declared == set(re.findall(r"{(\w+)}", path)), path


def test_process_operations_are_named_after_their_mcp_tools(doc):
    ids = {op["operationId"] for _, _, op in _ops(doc)}
    for spec in PROCESSES.values():
        assert spec.tool("status") in ids and spec.tool("runs") in ids
        assert (spec.tool("submit") in ids) is spec.external, spec.name


def test_a_continuation_only_process_has_no_submit_path(doc):
    for spec in PROCESSES.values():
        post = doc["paths"].get(f"/processes/{spec.name}/runs", {}).get("post")
        assert (post is not None) is ("submit" in WorkflowTools.verbs_for(spec))


def test_the_submit_body_is_the_platform_schema(doc):
    from lab.platform.submit_schema import input_schema
    for spec in (s for s in PROCESSES.values() if s.external):
        body = next(p for p in doc["paths"][f"/processes/{spec.name}/runs"]["post"]["parameters"]
                    if p["in"] == "body")
        assert body["schema"] == input_schema(spec)


def test_it_is_self_contained_and_small_enough_to_import(doc):
    text = json.dumps(doc)
    assert "$ref" not in text and len(text.encode()) < 1_000_000


def test_it_declares_entra_sign_in(doc):
    (scheme,) = doc["securityDefinitions"].values()
    assert scheme["type"] == "oauth2" and "login.microsoftonline.com" in scheme["authorizationUrl"]
    assert doc["security"]


def test_path_template_names_a_segment_after_its_collection():
    pattern = re.escape("/api") + r"/processes/[^/]+/runs/[^/]+/events"
    assert path_template(pattern, "/api") == "/processes/{process}/runs/{run}/events"
    assert path_template(re.escape("/api") + r"/approvals/[^/]+", "/api") == "/approvals/{approval}"


def test_an_upload_takes_files_and_an_artifact_answers_bytes(doc):
    if "/uploads" in doc["paths"]:
        up = doc["paths"]["/uploads"]["post"]
        assert up["consumes"] == ["multipart/form-data"]
        assert any(p["in"] == "formData" and p["type"] == "file" for p in up["parameters"])
    if "/artifacts" in doc["paths"]:
        assert doc["paths"]["/artifacts"]["get"]["responses"]["200"]["schema"] == {"type": "file"}


def test_a_literal_the_pattern_escaped_is_a_plain_character_in_the_template():
    from lab.platform.openapi import path_template
    assert path_template(r"/api/openapi\.json", "/api") == "/openapi.json"
