"""What a corpus read must say about itself: who consulted it for which derived field, and which
versions moved between two pins. Pure; pinning and reading are the workload's
(`lab.workloads.usecase.reference`)."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

__all__ = ["attribution", "drift"]


def attribution(cfg: Mapping[str, Any], field: str) -> dict:
    """Who is consulting the corpus, and for which derived field. A CLI or test run with no run
    id is still attributed — as what it is — because the server refuses a blank."""
    return {"run_id": cfg.get("run_id") or "local", "process": cfg.get("process") or "local",
            "field": field}


def drift(previous: Iterable[Mapping[str, Any]], current: Iterable[Mapping[str, Any]]) -> list[dict]:
    """Per artifact in BOTH sets, the version pair where they differ — what a later run must say
    about an earlier one's citations."""
    before = {v["artifact_id"]: v["version"] for v in previous}
    return [{"artifact_id": v["artifact_id"], "before": before[v["artifact_id"]],
             "after": v["version"]}
            for v in current
            if v["artifact_id"] in before and before[v["artifact_id"]] != v["version"]]
