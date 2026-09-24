"""One gateway config, a per-target MODEL overlay (production: config/litellm-models.azure.yaml).

The gateway's model NAMES are a contract — workload code, every agent key's `models` list and the
developer allowlist name them — so a deploy target keeps the names and swaps only what SERVES each one.
An overlay maps every base name to replacement `litellm_params`, or to null to drop it. It must mention
every name: one left alone would route to a provider this target holds no key for and fail only when
somebody asks for it. `model_info`, routing, guardrails, MCP servers and auth are the base config's.

    python -m lab.substrate.gateway.models_overlay --config config/litellm-config.yaml \\
        --overlay config/litellm-models.azure.yaml -- litellm --host 0.0.0.0 --port 4000
resolves the pair into a temporary config and execs the gateway on it.
"""
import argparse
import copy
import os
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]


def apply(config: dict, overlay: dict) -> dict:
    """`config` with each model's `litellm_params` replaced by the overlay's (null = dropped). Pure."""
    served = [m["model_name"] for m in config.get("model_list", [])]
    missing = sorted(set(served) - set(overlay))
    if missing:
        raise ValueError(f"the overlay does not say what serves: {', '.join(missing)}")
    unknown = sorted(set(overlay) - set(served))
    if unknown:
        raise ValueError(f"the overlay names models the config does not serve: {', '.join(unknown)}")
    out = copy.deepcopy(config)
    out["model_list"] = [{**m, "litellm_params": copy.deepcopy(overlay[m["model_name"]])}
                         for m in out.get("model_list", []) if overlay[m["model_name"]] is not None]
    kept = {m["model_name"] for m in out["model_list"]}
    aliases = (out.get("router_settings") or {}).get("model_group_alias") or {}
    dangling = sorted(a for a, t in aliases.items() if (t["model"] if isinstance(t, dict) else t) not in kept)
    if dangling:
        raise ValueError(f"aliases point at dropped models: {', '.join(dangling)}")
    return out


def resolve(config_path: str, overlay_path: str, out_dir: str | None = None) -> str:
    """Write the merged config to `out_dir` (a fresh temp dir by default) and return its path."""
    merged = apply(yaml.safe_load(open(config_path)), yaml.safe_load(open(overlay_path)))
    out = os.path.join(out_dir or tempfile.mkdtemp(prefix="litellm-"), "litellm-config.resolved.yaml")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        yaml.safe_dump(merged, f, sort_keys=False)
    return out


def main(argv: list[str]) -> None:  # pragma: no cover — exec, exercised by the container start
    head, _, cmd = " ".join(argv).partition(" -- ")
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--overlay", required=True)
    args = p.parse_args(head.split())
    resolved = resolve(args.config, args.overlay)
    print(f"gateway config: {args.config} + {args.overlay} -> {resolved}", flush=True)
    argv_cmd = cmd.split() + ["--config", resolved]
    os.execvp(argv_cmd[0], argv_cmd)


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1:])
