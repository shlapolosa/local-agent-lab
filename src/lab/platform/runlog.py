"""Live run visibility — a tiny, deterministic progress emitter for workflow hosts.

Why: a CLI run (`python -m lab.workloads.visio_to_archimate.host …`) is a black box for minutes —
stdout is block-buffered when redirected, and nothing is written until exit. This module makes
the CURRENT NODE of every run observable in two places at once:

  * one unbuffered line per node transition on stdout (`[run <id>] <node> start|done 42.1s|fail`)
  * a Redis hash per run that the review app's "Runs" board reads live

Keys (same Redis + client pool as every Redis-backed platform/substrate module: lab.platform.redis_client)
  run:<run_id>   hash: process, input, trace_id, status running|done|failed, node (current),
                 nodes (JSON list of {name,status,ts,t,attrs}), started_at, finished_at, mermaid …
  runs:active    set of run ids currently running
  runs:recent    list of finished run ids, newest first, capped at RECENT_CAP

Contract: NEVER raises on Redis trouble — a visibility tool must not break (or slow) a run. A
Redis failure switches this process to print-only mode (one stderr notice) for RETRY_AFTER_S,
after which the next call tries Redis again — so a dead Redis costs one connect attempt per
window rather than one timeout per node, and a BLIP does not blind the Runs board until restart.
Every entry point takes `client=` (a redis.Redis) to bypass the shared pool — tests, dedicated
pools — exactly as src/lab/platform/locks.py does.

Usage in a host:
    runlog.start(run_id, input=diagram, trace_id=trace_id)
    with runlog.span_node(run_id, "ba"):
        ...
    runlog.finish_from(run_id, error_or_None, approval_id=…)   # the one way a host closes a run
"""
import json
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone

TTL_S = 7 * 24 * 3600          # run:* hashes expire after a week
RECENT_CAP = 50
NODE_STATUSES = ("start", "done", "fail")
RUN_STATUSES = ("running", "done", "failed")

RETRY_AFTER_S = 30             # print-only window after a Redis failure, then try again
ERROR_CHARS = 300              # how much of an exception message any record of it keeps (error_text)

from lab.platform import redis_client  # noqa: E402

_RETRY_AT = 0.0                # epoch seconds until which Redis is NOT tried (0 = try now)


def _client():
    """The process-wide pooled client (lab.platform.redis_client)."""
    return redis_client.client()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _say(line):
    """Unbuffered progress line — visible immediately even when stdout is redirected to a file."""
    print(line, flush=True)


def _redis(op, client=None):
    """Run `op(r)` against Redis (`client` or the shared pool). On ANY failure: one stderr notice,
    print-only until RETRY_AFTER_S has passed, return None. Success clears the latch."""
    global _RETRY_AT
    if _RETRY_AT and time.time() < _RETRY_AT:
        return None
    try:
        out = op(client if client is not None else _client())
    except Exception as e:                       # noqa: BLE001 — visibility must never break a run
        _RETRY_AT = time.time() + RETRY_AFTER_S
        print(f"[runlog] redis unavailable ({type(e).__name__}: {e}) — print-only for {RETRY_AFTER_S}s",
              file=sys.stderr, flush=True)
        return None
    _RETRY_AT = 0.0
    return out


def _key(run_id):
    return f"run:{run_id}"


def _dump(v):
    return json.dumps(v) if isinstance(v, (dict, list)) else ("" if v is None else str(v))


# ------------------------------------------------------------------------------ writers
def start(run_id: str, *, input: str, trace_id: str | None = None,
          process: str = "visio_to_archimate", client=None, **fields) -> None:
    """Register a run as running. Extra `fields` (e.g. mermaid=…, request_id=…) are stored too."""
    fields = {"run_id": run_id, "process": process, "input": _dump(input), "trace_id": trace_id or "",
              "status": "running", "started_at": _now(), "t0": repr(time.time()), "node": "",
              "nodes": "[]", **{k: _dump(v) for k, v in fields.items()}}

    def op(r):
        p = r.pipeline()
        p.hset(_key(run_id), mapping=fields)
        p.expire(_key(run_id), TTL_S)
        p.sadd("runs:active", run_id)
        p.execute()
    _redis(op, client)
    _say(f"[run {run_id}] started {process} input={input}"
         + (f" trace={trace_id}" if trace_id else ""))


def node(run_id: str, name: str, status: str, *, client=None, **attrs) -> None:
    """Record a node transition: start | done | fail. `attrs` are free-form (error=…, elapsed=…);
    `elapsed` is derived from the node's own start entry when not given."""
    if status not in NODE_STATUSES:
        raise ValueError(f"status must be one of {NODE_STATUSES}")
    t = time.time()
    entry = {"name": name, "status": status, "ts": _now(), "t": t,
             "attrs": {k: v for k, v in attrs.items() if v is not None}}

    def op(r):
        # NOTE: HGET -> mutate -> HSET is not atomic; concurrent writers to ONE run could drop an
        # entry. A run is written by one host today. The RPUSH-per-node / Lua append lands with the
        # multi-request refactor (review A-F13), together with subscribing to AF workflow events.
        key = _key(run_id)
        try:
            nodes = json.loads(r.hget(key, "nodes") or "[]")
        except ValueError:
            nodes = []
        if status != "start" and "elapsed" not in entry["attrs"]:
            st = next((n for n in reversed(nodes) if n["name"] == name and n["status"] == "start"), None)
            if st:
                entry["attrs"]["elapsed"] = round(t - st["t"], 1)
        nodes.append(entry)
        p = r.pipeline()
        p.hset(key, mapping={"nodes": json.dumps(nodes), "node": name, "node_status": status,
                             "updated_at": entry["ts"]})
        p.expire(key, TTL_S)
        p.execute()
    _redis(op, client)

    el = entry["attrs"].get("elapsed")
    tail = {"start": "… start",
            "done": f"done{f' {el}s' if el is not None else ''}",
            "fail": f"FAIL{f' {el}s' if el is not None else ''}"
                    + (f": {entry['attrs']['error']}" if entry["attrs"].get("error") else "")}[status]
    _say(f"[run {run_id}] {name} {tail}")


def update(run_id: str, *, client=None, **fields) -> None:
    """Attach/overwrite fields on a run (e.g. mermaid=<graph>, trace_id=…, request_id=…)."""
    upd = {k: _dump(v) for k, v in fields.items() if v is not None}
    if not upd:
        return
    _redis(lambda r: r.hset(_key(run_id), mapping=upd), client)


def finish(run_id: str, status: str, *, client=None, **fields) -> None:
    """Close a run: status done | failed, finished_at, moved from runs:active to runs:recent."""
    if status not in RUN_STATUSES[1:]:
        raise ValueError("status must be 'done' or 'failed'")
    upd = {"status": status, "finished_at": _now(), **{k: _dump(v) for k, v in fields.items() if v is not None}}

    def op(r):
        key = _key(run_id)
        t0 = r.hget(key, "t0")
        if t0:
            upd["elapsed"] = str(round(time.time() - float(t0), 1))
        p = r.pipeline()
        p.hset(key, mapping=upd)
        p.expire(key, TTL_S)
        p.srem("runs:active", run_id)
        p.lrem("runs:recent", 0, run_id)
        p.lpush("runs:recent", run_id)
        p.ltrim("runs:recent", 0, RECENT_CAP - 1)
        p.execute()
    _redis(op, client)
    _say(f"[run {run_id}] {status.upper()}"
         + (f" {upd['elapsed']}s" if upd.get("elapsed") else "")
         + (f" — {fields['error']}" if fields.get("error") else ""))


def error_text(e: BaseException) -> str:
    """ONE phrasing of "what went wrong" for every run, node and request that records an exception:
    `<ExceptionType>: <message>` bounded to ERROR_CHARS, so a huge payload can never fill a Redis
    hash or a log. One phrasing means one bound too — a run row and a request hash have no reason
    to truncate differently."""
    return f"{type(e).__name__}: {str(e)[:ERROR_CHARS]}"


def finish_from(run_id: str, error: BaseException | None = None, *, client=None, **fields) -> str:
    """Close a run the way EVERY host closes one — the single implementation of "the run is over".
    Returns the status written.

    Two ways a run fails, and both count: the call raised (`error`), or the run's own timeline holds
    a `fail` node. The second matters because Agent Framework can surface an executor error as an
    EVENT rather than an exception (the DevUI path), so a stream that ends cleanly is not proof the
    run succeeded. `fields` (approval_id, xml_ref, … — whatever the run produced) are attached
    either way; None values are dropped by `finish`."""
    if error is not None:
        finish(run_id, "failed", error=error_text(error), client=client, **fields)
        return "failed"
    failed = next((n for n in reversed(get(run_id, client=client).get("nodes") or [])
                   if n["status"] == "fail"), None)
    if failed:
        finish(run_id, "failed", error=failed["attrs"].get("error", "node failed"), client=client, **fields)
        return "failed"
    finish(run_id, "done", client=client, **fields)
    return "done"


@contextmanager
def span_node(run_id: str, name: str, *, client=None, **attrs):
    """Wrap an executor body: emits start on entry, done (with elapsed) on exit, fail on exception
    (re-raised — this only observes)."""
    t0 = time.time()
    node(run_id, name, "start", client=client, **attrs)
    try:
        yield
    except BaseException as e:
        node(run_id, name, "fail", elapsed=round(time.time() - t0, 1),
             error=error_text(e), client=client)
        raise
    else:
        node(run_id, name, "done", elapsed=round(time.time() - t0, 1), client=client)


# ------------------------------------------------------------------------------ readers
def _parse(h: dict) -> dict:
    if not h:
        return {}
    try:
        h["nodes"] = json.loads(h.get("nodes") or "[]")
    except ValueError:
        h["nodes"] = []
    for k in ("t0", "elapsed"):
        if h.get(k):
            try:
                h[k] = float(h[k])
            except ValueError:
                pass
    if h.get("status") == "running" and isinstance(h.get("t0"), float):
        h["elapsed"] = round(time.time() - h["t0"], 1)
    return h


def get(run_id: str, *, client=None) -> dict:
    """The run hash with `nodes` decoded (and a live `elapsed` while running); {} if unknown."""
    return _parse(_redis(lambda r: r.hgetall(_key(run_id)), client) or {})


def active(*, client=None) -> list[dict]:
    """Runs currently in flight, oldest first. Ids whose hash expired are pruned from the set."""
    ids = _redis(lambda r: list(r.smembers("runs:active")), client) or []
    out = []
    for i in ids:
        h = get(i, client=client)
        if h:
            out.append(h)
        else:
            _redis(lambda r, i=i: r.srem("runs:active", i), client)
    return sorted(out, key=lambda h: h.get("started_at", ""))


def recent(n: int = 20, *, client=None) -> list[dict]:
    """Finished runs, newest first."""
    ids = _redis(lambda r: r.lrange("runs:recent", 0, max(0, n - 1)), client) or []
    return [h for h in (get(i, client=client) for i in ids) if h]


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "list":
        for h in active() + recent(20):
            print(f'{h.get("run_id")}  {h.get("status", ""):8} node={h.get("node", ""):18} '
                  f'{h.get("process", "")}  {h.get("input", "")}  ({h.get("started_at")}, {h.get("elapsed", "")}s)')
    elif a[0] == "show" and len(a) > 1:
        print(json.dumps(get(a[1]), indent=1))
    else:
        sys.exit(__doc__)
