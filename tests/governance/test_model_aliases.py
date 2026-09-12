"""The prefixed model aliases, and the two ways they can be silently wrong.

WHY THEY EXIST. Claude Code's gateway model discovery keeps a model only when its id contains
"claude" or "anthropic" (its gateway compatibility guide, "Model discovery"). Measured 8 Sep 2026 on
a throwaway gateway: with 12 models served, it cached exactly the 7 whose ids matched and dropped
`kimi-k3`, `glm-flash`, `gpt-oss-120b`, `kimi-k2.7-code` and `auto`. Those models were always
callable BY NAME; they were simply invisible in `/model`, which is how a developer chooses one.

WHY AN ALIAS AND NOT A RENAME. `kimi-k3` is named in workload code, in every agent key's `models`
list and in the developer allowlist. A rename breaks all of them. `model_group_alias` resolves to
the SAME model group, so there is one deployment, one spend identity, and `kimi-k3` keeps working
untouched — verified live on both API surfaces, Anthropic `/v1/messages` and OpenAI
`/v1/chat/completions`, for the alias and the original.

The two failures this pins are both silent:
  * an alias pointing at a model that does not exist — it LISTS, and every call fails;
  * an alias missing from the developer allowlist — a developer sees nothing, which looks exactly
    like the bug the aliases were added to fix. That allowlist is what limited an Entra identity to
    7 models while the master key saw 12, and it took an experiment to find.
"""
from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parents[2] / "config" / "litellm-config.yaml"


def _config() -> dict:
    return yaml.safe_load(CONFIG.read_text())


def test_every_alias_points_at_a_model_that_actually_exists():
    cfg = _config()
    served = {m["model_name"] for m in cfg["model_list"]}
    aliases = cfg.get("router_settings", {}).get("model_group_alias", {}) or {}
    for alias, target in aliases.items():
        name = target["model"] if isinstance(target, dict) else target
        assert name in served, f"alias {alias!r} -> {name!r}, which no model_list entry serves"


def test_every_alias_is_visible_to_claude_code_discovery():
    """An alias whose id lacks 'claude'/'anthropic' is dropped by discovery — so it would be a
    rename with none of the benefit, and nobody would notice until they looked in /model."""
    aliases = _config().get("router_settings", {}).get("model_group_alias", {}) or {}
    assert aliases, "the aliases exist to make non-Claude models discoverable; none are declared"
    for alias in aliases:
        low = alias.lower()
        assert "claude" in low or "anthropic" in low, \
            f"{alias!r} would be filtered out by Claude Code's discovery, so it buys nothing"


def test_the_developer_allowlist_names_every_alias():
    """`default_internal_user_params.models` is a per-user restriction, and a model absent from it
    is invisible to a developer identity however the catalogue is configured."""
    cfg = _config()
    aliases = set(cfg.get("router_settings", {}).get("model_group_alias", {}) or {})
    allowed = set(cfg["litellm_settings"]["default_internal_user_params"]["models"])
    assert aliases <= allowed, f"aliases a developer cannot see: {sorted(aliases - allowed)}"


def test_an_alias_never_replaces_the_name_a_workload_calls():
    """The whole point of aliasing rather than renaming: the original names must survive, because
    workload code and agent key `models` lists name them."""
    cfg = _config()
    served = {m["model_name"] for m in cfg["model_list"]}
    aliases = cfg.get("router_settings", {}).get("model_group_alias", {}) or {}
    for target in aliases.values():
        name = target["model"] if isinstance(target, dict) else target
        assert name in served, f"{name!r} was renamed away; workloads calling it would break"
    assert {"kimi-k3", "glm-flash", "auto"} <= served, "a model a workload names has gone missing"


def test_an_alias_is_not_hidden_from_the_model_list():
    """`hidden: true` keeps an alias out of /v1/models, which is exactly where discovery reads."""
    aliases = _config().get("router_settings", {}).get("model_group_alias", {}) or {}
    for alias, target in aliases.items():
        if isinstance(target, dict):
            assert target.get("hidden") is not True, f"{alias!r} is hidden from /v1/models"


def test_the_use_case_agents_model_is_served_and_the_cards_and_provisioning_follow_it():
    """One declaration (`config.USECASE_AGENT_MODEL`): the gateway serves it, every use-case agent
    card names it, and the provisioning script mints and reconciles keys to it — so the 12 Sep 2026
    move off a capped upstream was one value, and the next one will be too."""
    import importlib.util, sys
    from pathlib import Path
    from lab.platform import config
    ROOT = Path(__file__).resolve().parents[2]
    from lab.platform.contracts import AGENTS
    served = {m["model_name"] for m in _config()["model_list"]}
    assert config.USECASE_AGENT_MODEL in served
    usecase = [a for a in AGENTS if any(p.startswith("use_case_") for p in a.processes)]
    assert len(usecase) >= 12 and all(a.model == config.USECASE_AGENT_MODEL for a in usecase)
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("provision_usecase_agents", ROOT / "scripts" / "provision_usecase_agents.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    assert mod.AGENT_MODEL == config.USECASE_AGENT_MODEL and mod.EVALS_MODELS[0] == config.USECASE_AGENT_MODEL
