"""lab.substrate.gateway.models_overlay — one gateway config, a per-target MODEL overlay.

The gateway's model NAMES are its contract (workload code, agent keys' `models` lists and the
developer allowlist all name them), so production keeps every name and swaps only what serves it.
The overlay must say, for EVERY base name, either what serves it or that it is dropped: a name left
alone would silently route to a provider this target holds no key for, and fail only at request time.
"""
import pytest
import yaml

from lab.substrate.gateway import models_overlay as mo

BASE = {
    "model_list": [
        {"model_name": "kimi-k3", "litellm_params": {"model": "openai/kimi-k3", "api_base": "https://ollama.com/v1"},
         "model_info": {"supports_vision": True}},
        {"model_name": "nomic-embed-text", "litellm_params": {"model": "ollama/nomic-embed-text"},
         "model_info": {"mode": "embedding"}},
    ],
    "router_settings": {"model_group_alias": {"claude/kimi-k3": {"model": "kimi-k3", "hidden": False}}},
    "general_settings": {"custom_auth": "lab.substrate.gateway.custom_auth.user_api_key_auth"},
}
AZURE = {"kimi-k3": {"model": "azure/gpt-5-mini", "api_base": "os.environ/AZURE_FOUNDRY_API_BASE"},
         "nomic-embed-text": None}


def test_a_name_keeps_its_info_and_gets_the_overlay_params():
    out = mo.apply(BASE, AZURE)
    [kimi] = [m for m in out["model_list"] if m["model_name"] == "kimi-k3"]
    assert kimi["litellm_params"] == AZURE["kimi-k3"]
    assert kimi["model_info"] == {"supports_vision": True}


def test_null_drops_a_name_this_target_does_not_serve():
    names = [m["model_name"] for m in mo.apply(BASE, AZURE)["model_list"]]
    assert names == ["kimi-k3"]


def test_everything_but_the_model_list_is_untouched_and_the_base_is_not_mutated():
    before = yaml.safe_dump(BASE)
    out = mo.apply(BASE, AZURE)
    assert out["general_settings"] == BASE["general_settings"]
    assert out["router_settings"] == BASE["router_settings"]
    assert yaml.safe_dump(BASE) == before


def test_a_base_name_the_overlay_does_not_mention_is_refused_by_name():
    with pytest.raises(ValueError, match="nomic-embed-text"):
        mo.apply(BASE, {"kimi-k3": AZURE["kimi-k3"]})


def test_an_overlay_name_the_base_does_not_serve_is_refused_by_name():
    with pytest.raises(ValueError, match="gpt-9"):
        mo.apply(BASE, {**AZURE, "gpt-9": {"model": "azure/x"}})


def test_an_alias_to_a_dropped_name_is_refused():
    with pytest.raises(ValueError, match="claude/kimi-k3"):
        mo.apply(BASE, {"kimi-k3": None, "nomic-embed-text": None})


def test_resolve_writes_the_merged_config_and_returns_its_path(tmp_path):
    base, overlay = tmp_path / "base.yaml", tmp_path / "azure.yaml"
    base.write_text(yaml.safe_dump(BASE))
    overlay.write_text(yaml.safe_dump(AZURE))
    out = mo.resolve(str(base), str(overlay), str(tmp_path / "out"))
    assert yaml.safe_load(open(out))["model_list"][0]["litellm_params"]["model"] == "azure/gpt-5-mini"


def test_the_committed_azure_overlay_covers_every_name_the_committed_config_serves():
    """The real pair, not a fixture: a model added to config/litellm-config.yaml without a production
    answer fails HERE, not on the first production request for it."""
    base = yaml.safe_load(open(mo.ROOT / "config" / "litellm-config.yaml"))
    overlay = yaml.safe_load(open(mo.ROOT / "config" / "litellm-models.azure.yaml"))
    out = mo.apply(base, overlay)
    assert out["model_list"], "production serves no model at all"
    for m in out["model_list"]:
        assert not m["litellm_params"]["model"].startswith(("ollama/", "anthropic/")), m["model_name"]
