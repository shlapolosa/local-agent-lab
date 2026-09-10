"""The relevance stores: the gateway's registry, the contract, and what makes a store governed.

Three things can drift silently. A store in the contract the gateway does not register passes
preflight and fails the run; a store registered with a credential in the yaml would send that
credential LITERALLY (LiteLLM resolves no `os.environ/` on its vector-store path — verified in
1.98); and an embedding width that differs from the served model's compares a query with an index
it cannot be compared with. Each is pinned here, offline, from the files themselves.
"""
import importlib.util
import os
from pathlib import Path

import pytest
import yaml

from lab.platform import config
from lab.platform.contracts import VectorStores

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "litellm-config.yaml"


def _config() -> dict:
    return yaml.safe_load(CONFIG.read_text())


@pytest.fixture(scope="module")
def railway():
    """deploy/railway.py without Railway credentials — the deploy tests' own pattern."""
    mp = pytest.MonkeyPatch()
    for k in ("RAILWAY_TOKEN", "RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID"):
        mp.delenv(k, raising=False)
    spec = importlib.util.spec_from_file_location("lab_railway_vs", ROOT / "deploy" / "railway.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    mp.undo()


def _allowed(patterns, name) -> bool:
    return any(name == p or (p.endswith("*") and name.startswith(p[:-1])) for p in patterns)


# ---------------------------------------------------------------- one declaration

def test_the_yaml_declares_no_stores_because_a_database_deletes_them():
    """`vector_store_registry` loads into memory and the list endpoint removes any store the
    database does not hold (verified live). A block here would be a decoy that passes review and
    disappears at the first `GET /vector_store/list`."""
    assert "vector_store_registry" not in _config()
    assert VectorStores.names(), "the contract is the declaration, and it is non-empty"


def test_the_registration_script_reconciles_exactly_the_contract():
    """What CD writes into the gateway is derived from `VectorStores` at run time — nothing to
    drift from — and carries neither a credential nor an api_base."""
    spec = importlib.util.spec_from_file_location(
        "register_vector_stores", ROOT / "scripts" / "register_vector_stores.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import io
    import contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert module.main(["--dry-run"]) == 0
    declared = {e["vector_store_id"]: e for e in __import__("json").loads(out.getvalue())}
    assert set(declared) == VectorStores.names()
    for entry in declared.values():
        assert entry["custom_llm_provider"] == VectorStores.PROVIDER
        assert entry["litellm_params"] == {}, "no credential, no api_base — the env carries them"
        assert entry["vector_store_description"]


def test_the_gateway_role_is_handed_what_the_stores_read_from_its_environment(railway):
    allowed = railway.ROLE_ENV["gateway"]
    for name in ("PG_VECTOR_API_BASE", "PG_VECTOR_API_KEY"):
        assert _allowed(allowed, name), f"{name} never reaches the cloud gateway"
    # ... and every workload role is NOT: a store is reached through the gateway, never directly
    for role, patterns in railway.ROLE_ENV.items():
        if role != "gateway":
            assert not _allowed(patterns, "PG_VECTOR_API_KEY"), role


def test_file_search_injection_stays_off():
    """`vector_store_pre_call_hook` injects context from the LAST user message with NO pin — a read
    the corpus cannot attribute. Refused by design until a pin can travel with it."""
    callbacks = _config()["litellm_settings"].get("callbacks") or []
    assert "vector_store_pre_call_hook" not in callbacks


# ---------------------------------------------------------------- the embedding model

def _embedding_models() -> list[dict]:
    return [m for m in _config()["model_list"]
            if (m.get("model_info") or {}).get("mode") == "embedding"]


def test_every_model_credential_is_an_environment_reference_the_gateway_role_receives(railway):
    """A credential typed into the yaml would be committed to a PUBLIC repo; one referenced from an
    env name the cloud gateway is never handed resolves to nothing and every call fails."""
    allowed = railway.ROLE_ENV["gateway"]
    for model in _config()["model_list"]:
        params = model["litellm_params"]
        key, base = params.get("api_key", ""), params.get("api_base", "")
        if not key:
            # A model on the PRIVATE network (the substrate's own embedder) authenticates like
            # Redis does — not at all — but its address must still be an env reference the
            # gateway receives, or it resolves to nothing and every call fails.
            assert base.startswith("os.environ/"), f"{model['model_name']} has no key and no env address"
            assert _allowed(allowed, base.removeprefix("os.environ/")), \
                f"{model['model_name']}: {base} never reaches the cloud gateway"
            continue
        assert key.startswith("os.environ/"), f"{model['model_name']} carries a literal credential"
        assert _allowed(allowed, key.removeprefix("os.environ/")), \
            f"{model['model_name']}: {key} never reaches the cloud gateway"


def test_the_corpus_embeds_with_the_one_served_embedding_model_at_its_native_width():
    """REFERENCE_EMBED_DIM's default is the served model's `output_vector_size`. A query embedded
    at another width cannot be compared with the index, and `pg_library.search` refuses the
    mismatch — this catches it before a corpus is published at the wrong width."""
    models = _embedding_models()
    assert len(models) == 1, "one embedding model is served; a second needs REFERENCE_EMBED_MODEL"
    assert models[0]["model_info"]["output_vector_size"] == config.REFERENCE_EMBED_DIM
    assert models[0]["litellm_params"]["model"].startswith("ollama/"), \
        "the corpus embeds with the substrate's own model — no vendor serves one this lab can use"


# ---------------------------------------------------------------- compose is not a third answer

def _compose() -> dict:
    return yaml.safe_load((ROOT / "deploy" / "substrate" / "compose.yml").read_text())


def test_compose_lets_config_own_the_embedding_width():
    """A literal default in compose was 1024 while config said 3072: a compose deployment would
    have indexed at a width the cloud corpus does not share. One home — `config.py`."""
    env = _compose()["services"]["reference-mcp"]["environment"]
    assert "REFERENCE_EMBED_DIM" not in env


def test_compose_points_the_gateway_at_the_facade_with_the_shared_secret():
    env = _compose()["services"]["gateway"]["environment"]
    assert env["PG_VECTOR_API_BASE"] == "http://reference-mcp:9700"
    assert "MCP_SHARED_SECRET" in str(env["PG_VECTOR_API_KEY"])


# ---------------------------------------------------------------- the workbooks

def test_the_corpus_publishes_exactly_the_stores_the_gateway_registers():
    """Three declarations collapse to one: the publish script's WORKBOOKS is keyed by the store
    catalogue and asserts it at import, so a store with no artifact — or the reverse — cannot load."""
    spec = importlib.util.spec_from_file_location(
        "publish_usecase_corpus", ROOT / "scripts" / "publish_usecase_corpus.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert set(module.WORKBOOKS) == VectorStores.names()


def test_no_licensed_workbook_is_tracked_by_git():
    """The repository is public and the BA Guild models are licensed: a workbook travels by
    `art://` ref through the private store and is never a file here. (The ADOIT object-import
    template is a bundled tenant file, not a licensed model, and stays.)"""
    import subprocess
    from lab.core.semantic.reference.baguild import KNOWN
    tracked = subprocess.run(["git", "ls-files", "*.xlsx", "**/*.xlsx"], cwd=ROOT,
                             capture_output=True, text=True).stdout.split()
    licensed = [f for f in tracked if Path(f).stem in KNOWN or "reference-sources" in f]
    assert licensed == [], licensed
