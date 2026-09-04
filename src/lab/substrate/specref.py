"""Loading a model spec however a caller hands it over — ONE implementation for both MCP servers.

A spec (the archimate_render / semantic_validate_model JSON) arrives in one of three ways:
  spec       by value — a dict, or the SAME dict serialised as a JSON string (agents frequently
             emit a nested object as a string; AF #2747 flattens nested MCP params, so this is
             the norm, not an edge case)
  spec_ref   by artifact reference `art://<id>/<name>` — read from the `store` the caller injects
             (the server's container-provided artifact store); the preferred shape for agents
             because the tool argument stays small
  spec_path  by local file path — local development only (a workload never holds paths)
Precedence when several are given: spec_ref, then spec_path, then spec.
"""
from __future__ import annotations

import json
from typing import Any

HELP = ("give the spec by value (`spec`, a JSON object or a JSON string), by artifact reference "
        "(`spec_ref`, art://…) or — local dev only — by file path (`spec_path`)")


def coerce(spec: Any, *, what: str = "spec") -> dict:
    """A dict as-is; a JSON string / bytes decoded; anything else is an error."""
    if isinstance(spec, (bytes, bytearray)):
        spec = spec.decode()
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except ValueError as e:
            raise ValueError(f"{what} is a string but not valid JSON: {e}") from e
    if not isinstance(spec, dict):
        raise ValueError(f"{what} must be a JSON object, got {type(spec).__name__}")
    return spec


def load_spec(spec: Any = None, spec_path: str | None = None, spec_ref: str | None = None,
              *, store=None) -> dict:
    """Resolve the three-way input to a dict (see module docstring for precedence). `store` is
    the artifact store a `spec_ref` is read from — required for a ref (no hidden global store)."""
    if spec_ref:
        if store is None:
            raise TypeError("load_spec(spec_ref=…) needs `store` — the artifact store the ref is read from")
        return coerce(store.get(spec_ref), what=f"spec_ref {spec_ref}")
    if spec_path:
        with open(spec_path) as f:
            return coerce(f.read(), what=f"spec_path {spec_path}")
    if spec is None or spec == "":
        raise ValueError("no spec given — " + HELP)
    spec = coerce(spec)                    # check emptiness AFTER coercing: "{}" is as empty as {}
    if not spec:
        raise ValueError("no spec given — " + HELP)
    return spec


__all__ = ["load_spec", "coerce", "HELP"]
