"""The deploy scripts put deploy/ on sys.path so they can import their siblings. A sibling named after
an installed package then SHADOWS it for the whole process: `deploy/azure.py` made `import azure.core`
fail (`'azure' is not a package`) for every test that ran after one had loaded it — litellm's azure
route and agent_framework's azure packages among them. Load every deploy script the way the tests and
scripts do, then import the packages a sibling could shadow."""
import importlib
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEPLOY = os.path.join(ROOT, "deploy")


def test_no_deploy_script_or_directory_is_named_after_an_installed_top_level_package():
    names = {os.path.splitext(n)[0] for n in os.listdir(DEPLOY) if n.endswith(".py") or
             os.path.isdir(os.path.join(DEPLOY, n))}
    clashes = sorted(n for n in names - {"__pycache__"}
                     if importlib.util.find_spec(n) is not None
                     and not (importlib.util.find_spec(n).origin or "").startswith(DEPLOY)
                     and not any(p.startswith(DEPLOY) for p in (importlib.util.find_spec(n).submodule_search_locations or [])))
    assert clashes == [], f"deploy/ entries named after installed packages: {clashes}"


def test_the_azure_sdk_still_imports_after_every_deploy_script_is_loaded():
    for n in sorted(os.listdir(DEPLOY)):
        if n.endswith(".py"):
            spec = importlib.util.spec_from_file_location(f"lab_shadow_{n[:-3]}", os.path.join(DEPLOY, n))
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
    sys.modules.pop("azure", None)
    importlib.import_module("azure.core")
