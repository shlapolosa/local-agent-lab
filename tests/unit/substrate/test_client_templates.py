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
