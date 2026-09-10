"""The governed corpus, from a workload's side: pin once per run, read under it, record what moved.

A pin is the unit of reproducibility. Every workload declares the artifacts it reads and pins
exactly those before its first derivation, so the versions a run cites are frozen for the run —
and NOT the whole corpus, because every pinned artifact records a consumption row, and a miss on
fifty unread artifacts is noise in the reverse index. A read that names an artifact the pin lacks
is refused by the server; a step whose corpus is absent is deferred by the run, never answered
from nothing.

DRIFT is recorded, never blocked on (user decision, 10 Sep 2026). The criticality approval can
wait days, and the corpus may cut a release in between; the design run re-pins — deriving against
the CURRENT release is what a release means — and states per artifact "screened at v0.26,
designed at v0.27" so a reviewer sees it. Refusing would block every in-flight case on a routine
release.

`attribution` is what FR-44 asks of every read: the run, the process and the DERIVED FIELD it
was consulted for. The pin, the versions and the drift ride the run board and the record.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Sequence

from lab.core.reference.cells import rows
from lab.platform import runlog
from lab.platform.contracts import ReferenceTools
from lab.workloads import gateway

__all__ = ["attribution", "drift", "pin", "records"]


def _payload(res: Any) -> dict:
    return res if isinstance(res, dict) else json.loads(res or "{}")


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


async def pin(cfg: Mapping[str, Any], artifact_ids: Sequence[str], *,
              previous: Iterable[Mapping[str, Any]] = ()) -> dict:
    """Freeze this run's versions of exactly `artifact_ids`; annotate the run board; note drift
    against the versions an earlier run of the same case cited (`previous`)."""
    out = _payload(await gateway.call(cfg, ReferenceTools.pin,
                                      {"artifact_ids": list(artifact_ids)}))
    versions = [{"artifact_id": v["artifact_id"], "version": v["version"],
                 "retrieval": v.get("retrieval", "key")} for v in out.get("versions") or []]
    pinned = {"pin_id": out["pin_id"], "versions": versions,
              "drift": drift(previous, versions)}
    if cfg.get("run_id"):
        runlog.update(cfg["run_id"], pin_id=pinned["pin_id"],
                      pinned_versions=versions)
    return pinned


async def records(cfg: Mapping[str, Any], pin_id: str, artifact_id: str, *, record_type: str,
                  field: str, key: Mapping[str, Any] | None = None, limit: int = 500) -> list[dict]:
    """An EXACT read under the pin, as the domain's rows. `key={}` with a `whole` artifact returns
    every record whatever the limit; a miss is `[]` and is recorded by the server as a miss."""
    out = _payload(await gateway.call(cfg, ReferenceTools.lookup, {
        "pin_id": pin_id, "artifact_id": artifact_id, "record_type": record_type,
        "key": dict(key or {}), "limit": limit, **attribution(cfg, field)}))
    records_ = out.get("records") or []
    # A read the server had to cut at the limit is refused, not matched over: the surviving
    # subset is ordered by a content hash, so nothing downstream could tell it was partial.
    if len(records_) >= limit:
        raise RuntimeError(f"{artifact_id}: the read hit the {limit}-row limit for {dict(key or {})} "
                           f"— the artifact outgrew this reader; raise the limit or page")
    return rows(records_)
