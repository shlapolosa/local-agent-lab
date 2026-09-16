"""The committed client templates: valid where a client will validate them, and secret-free.

A connector file that fails its importer fails in the tenant, hours later, as somebody else's
problem. 15 Sep 2026: the Copilot Studio connector shipped with an empty `responses` object, which
Swagger 2.0 forbids, and pointed at a key the provisioner never minted.
"""
import glob
import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TEMPLATES = sorted(glob.glob(os.path.join(ROOT, "config", "clients", "*", "*.template.json")))


def test_there_are_templates_to_check():
    assert TEMPLATES


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: os.path.basename(os.path.dirname(p)))
def test_a_template_is_json_and_carries_no_secret(path):
    body = open(path).read()
    json.loads(body)                                   # placeholders are inside strings, so it parses
    for leak in ("sk-", "-----BEGIN", "password"):
        assert leak not in body, f"{leak} in {path}"


SWAGGERS = [p for p in TEMPLATES if json.load(open(p)).get("swagger")]


@pytest.mark.parametrize("path", SWAGGERS, ids=lambda p: os.path.basename(p))
def test_a_swagger_template_is_what_the_power_platform_importer_accepts(path):
    d = json.load(open(path))
    assert d["swagger"] == "2.0" and d["info"].get("title") and d["info"].get("version")
    assert d.get("host") and "://" not in d["host"], "a swagger host is a bare hostname"
    assert d.get("paths"), "a connector with no path imports as nothing"
    for route, methods in d["paths"].items():
        for verb, op in methods.items():
            assert op.get("operationId"), f"{route} {verb} has no operationId"
            # Swagger 2.0 REQUIRES a non-empty responses object; the importer refuses without it.
            assert op.get("responses"), f"{route} {verb} has no responses"
    for name, scheme in (d.get("securityDefinitions") or {}).items():
        assert scheme.get("type") in ("apiKey", "oauth2", "basic"), name


def test_the_copilot_connector_names_a_key_the_provisioner_actually_mints():
    """The connection is made with a virtual key; a README naming one nobody creates is a setup that
    cannot be followed."""
    connector = os.path.join(ROOT, "config", "clients", "copilot-studio")
    readme = open(os.path.join(connector, "README.md")).read()
    named = set(re.findall(r"\b(USECASE_[A-Z_]+_KEY)\b", readme))
    provisioner = open(os.path.join(ROOT, "scripts", "provision_usecase_agents.py")).read()
    assert named, "the README must say which key to connect with"
    for key in named:
        assert f'"{key}"' in provisioner, f"{key} is named to the user and minted by nobody"


def test_the_copilot_readme_promises_only_tools_the_key_is_granted():
    """A README's tool table is a promise made to whoever sets the agent up. 15 Sep 2026 it listed
    the design tools, the grant did not, and the connector came up with six tools and a table
    claiming ten."""
    import importlib.util
    import sys

    connector = os.path.join(ROOT, "config", "clients", "copilot-studio")
    readme = open(os.path.join(connector, "README.md")).read()
    spec = importlib.util.spec_from_file_location("_prov",
                                                  os.path.join(ROOT, "scripts", "provision_usecase_agents.py"))
    module = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, ["provision"]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.argv = argv
    granted = {t for tools in module.SUBMITTER_TOOLS.values() for t in tools}
    promised = set(re.findall(r"`(use_case_[a-z_]+|approvals_[a-z]+)`", readme))
    assert promised, "the README must say what the agent can do"
    missing = {p for p in promised if p not in granted and not p.endswith("_submit")}
    assert not missing, f"the README promises {sorted(missing)}, which the submitter key cannot call"


def test_a_client_readme_does_not_tell_a_reader_to_run_a_path_that_may_not_exist():
    """15 Sep 2026: the walkthrough said `.venv/bin/python`, which every git WORKTREE lacks — the
    venv lives in the canonical checkout. A setup step that fails on the machine it was written for
    is worse than no step."""
    for readme in glob.glob(os.path.join(ROOT, "config", "clients", "*", "README.md")):
        body = open(readme).read()
        if ".venv/bin/python" in body:
            assert "worktree" in body, f"{readme} runs the venv without saying where it is"


def test_an_mcp_connector_accepts_both_media_types_the_transport_requires():
    """Streamable HTTP refuses a client that accepts only JSON: the gateway answers 406 "must accept
    both application/json and text/event-stream" before any tool is reached (measured 15 Sep 2026 in
    the Power Platform test harness, which builds its Accept header from `produces`)."""
    for path in SWAGGERS:
        d = json.load(open(path))
        agentic = [op for methods in d["paths"].values() for op in methods.values()
                   if "mcp" in str(op.get("x-ms-agentic-protocol", ""))]
        if not agentic:
            continue
        produces = set(d.get("produces") or [])
        assert {"application/json", "text/event-stream"} <= produces, f"{path} produces {produces}"


def test_an_mcp_connector_declares_the_accept_header_rather_than_trusting_produces():
    """15 Sep 2026, measured in the portal: the Power Platform runtime sent `Accept:
    application/json` even with `text/event-stream` in `produces`, and the gateway refused it with
    406. The header is therefore a parameter with a default, which the runtime does send."""
    for path in SWAGGERS:
        d = json.load(open(path))
        for methods in d["paths"].values():
            for op in methods.values():
                if "mcp" not in str(op.get("x-ms-agentic-protocol", "")):
                    continue
                accept = [p for p in op.get("parameters") or []
                          if p.get("in") == "header" and p.get("name", "").lower() == "accept"]
                assert accept, f"{path} leaves Accept to produces"
                default = accept[0].get("default", "")
                assert "application/json" in default and "text/event-stream" in default, default


def test_an_operation_declares_at_most_one_body_parameter():
    """Swagger 2.0 allows one. The Power Platform portal adds its OWN body to an agentic operation
    (`queryRequest`), so a template that also declares one produced a deployed definition with two —
    read back from the tenant on 16 Sep 2026, on a connector Copilot Studio then could not connect
    to."""
    for path in TEMPLATES:
        d = json.load(open(path))
        for route, methods in (d.get("paths") or {}).items():
            for verb, op in methods.items():
                bodies = [p for p in op.get("parameters") or [] if p.get("in") == "body"]
                assert len(bodies) <= 1, f"{path} {verb} {route} declares {len(bodies)} body params"
