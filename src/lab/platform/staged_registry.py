"""Workload-scoped STAGED-OBJECT REGISTRY — the in-flight counterpart of the EA repository.

Why: a multi-view workload runs as one workflow request per view. `resolve_existing` searches
ADOIT so shared components ("API Gateway (Kong)") are REUSED, not duplicated — but a view's NEW
objects reach ADOIT only after a human approves + imports them. A later view that runs before that
import cannot see the earlier view's objects and would create them again. This registry records
every canonical object the moment its view is STAGED for approval, so later views consult it IN
ADDITION to ADOIT and reuse the same element ids.

Deterministic, no LLM. The `canonical` key is produced elsewhere (src/lab/core/canon.py); here it is an
opaque string.

Keys
  workload:<id>:objects   hash: field = canonical -> JSON entry (TTL refreshed on every write)
                          entry = {canonical, name, type, domain, element_id, view, views[],
                                   status: staged|imported, staged_at, imported_at?}

Rules
  * FIRST WRITER WINS on element_id: re-staging an already-`staged` canonical keeps the original
    entry (its element_id is what later views must reuse) and only appends to `views`.
  * An `imported` entry is never overwritten (it now lives in ADOIT; `resolve_existing` finds it).
  * Reads never raise on Redis trouble — they log and return None / {} / []; writes DO raise so a
    caller knows a stage failed (silently losing a staged object is exactly the duplicate bug).

CLI:  python -m lab.platform.staged_registry list <workload> | imported <workload> [canonical ...]
                                       | clear <workload>
"""
import json
import logging
import sys
from datetime import datetime, timezone

import redis

from lab.platform import redis_client

log = logging.getLogger("staged_registry")

REQUIRED = ("canonical", "name", "type", "domain", "element_id", "view")
DEFAULT_TTL_DAYS = 14


def _r():
    """The process-wide pooled client (lab.platform.redis_client)."""
    return redis_client.client()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def key(workload_id):
    if not workload_id or not isinstance(workload_id, str):
        raise ValueError("workload_id must be a non-empty string")
    return f"workload:{workload_id}:objects"


# --- atomic writes (Lua): first-writer-wins must hold even if two views stage concurrently ---

# KEYS[1] = hash; ARGV[1] = ttl seconds; ARGV[2..] = JSON entries (each already carries views=[view]).
# Returns the number of fields written (new entries + entries whose `views` grew).
_STAGE = """
local key, ttl, written = KEYS[1], tonumber(ARGV[1]), 0
for i = 2, #ARGV do
  local new = cjson.decode(ARGV[i])
  local cur = redis.call('HGET', key, new.canonical)
  if not cur then
    redis.call('HSET', key, new.canonical, ARGV[i]); written = written + 1
  else
    local old = cjson.decode(cur)
    if old.status ~= 'imported' then
      local seen = false
      for _, v in ipairs(old.views or {}) do if v == new.view then seen = true end end
      if not seen then
        old.views = old.views or {}
        old.views[#old.views + 1] = new.view
        redis.call('HSET', key, new.canonical, cjson.encode(old)); written = written + 1
      end
    end
  end
end
redis.call('EXPIRE', key, ttl)
return written
"""

# KEYS[1] = hash; ARGV[1] = ttl; ARGV[2] = imported_at; ARGV[3..] = canonicals (none = every field).
_MARK_IMPORTED = """
local key, ttl, at, n = KEYS[1], tonumber(ARGV[1]), ARGV[2], 0
local fields = {}
if #ARGV > 2 then
  for i = 3, #ARGV do fields[#fields + 1] = ARGV[i] end
else
  fields = redis.call('HKEYS', key)
end
for _, f in ipairs(fields) do
  local cur = redis.call('HGET', key, f)
  if cur then
    local e = cjson.decode(cur)
    if e.status ~= 'imported' then
      e.status = 'imported'; e.imported_at = at
      redis.call('HSET', key, f, cjson.encode(e)); n = n + 1
    end
  end
end
if redis.call('EXISTS', key) == 1 then redis.call('EXPIRE', key, ttl) end
return n
"""


def _validate(obj):
    if not isinstance(obj, dict):
        raise ValueError(f"object must be a dict, got {type(obj).__name__}")
    missing = [f for f in REQUIRED if not (obj.get(f) or "").strip()]
    if missing:
        raise ValueError(f"object {obj.get('canonical')!r} missing {missing}")
    return {f: str(obj[f]).strip() for f in REQUIRED}


def _decode(raw):
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        log.warning("staged_registry: undecodable entry %r", raw[:80])
        return None


# --- public API ---

def stage(workload_id, objects, *, ttl_days=DEFAULT_TTL_DAYS):
    """Record a view's canonical objects as staged-for-approval. Each object:
    {canonical, name, type, domain, element_id, view}. Returns the number of hash fields written
    (new entries + existing `staged` entries whose `views` list grew). Raises on bad input or
    Redis failure — a lost stage is a future duplicate, so the caller must know."""
    k = key(workload_id)
    ttl = int(ttl_days * 86400)
    if ttl <= 0:
        raise ValueError("ttl_days must be positive")
    now = _now()
    entries = []
    for o in objects or []:
        e = _validate(o)
        e.update(views=[e["view"]], status="staged", staged_at=now)
        entries.append(json.dumps(e, ensure_ascii=False))
    r = _r()
    if not entries:
        if r.exists(k):
            r.expire(k, ttl)
        return 0
    n = int(r.eval(_STAGE, 1, k, ttl, *entries))
    log.info("staged_registry: %s wrote %d/%d objects", k, n, len(entries))
    return n


def lookup(workload_id, canonical):
    """The registry entry for one canonical, or None (also None when Redis is unreachable)."""
    try:
        return _decode(_r().hget(key(workload_id), canonical))
    except (redis.RedisError, OSError) as e:
        log.warning("staged_registry: lookup failed (%s) — treating as absent", e)
        return None


def lookup_many(workload_id, canonicals):
    """{canonical: entry} for the canonicals that are registered — one HMGET. {} on Redis trouble."""
    canonicals = list(dict.fromkeys(c for c in (canonicals or []) if c))
    if not canonicals:
        return {}
    try:
        raws = _r().hmget(key(workload_id), canonicals)
    except (redis.RedisError, OSError) as e:
        log.warning("staged_registry: lookup_many failed (%s) — treating as absent", e)
        return {}
    out = {}
    for c, raw in zip(canonicals, raws):
        e = _decode(raw)
        if e:
            out[c] = e
    return out


def mark_imported(workload_id, canonicals=None, *, ttl_days=DEFAULT_TTL_DAYS):
    """After the human-approved import lands in ADOIT: flip entries to `imported` (+imported_at).
    None = every entry in the workload. Returns the number of entries flipped (already-imported
    and unknown canonicals are skipped). Raises on Redis failure."""
    k = key(workload_id)
    fields = list(dict.fromkeys(c for c in (canonicals or []) if c))
    if canonicals is not None and not fields:
        return 0
    n = int(_r().eval(_MARK_IMPORTED, 1, k, int(ttl_days * 86400), _now(), *fields))
    log.info("staged_registry: %s marked %d imported", k, n)
    return n


def list_objects(workload_id):
    """Every entry for the workload, ordered by (staged_at, canonical). [] on Redis trouble."""
    try:
        raw = _r().hgetall(key(workload_id))
    except (redis.RedisError, OSError) as e:
        log.warning("staged_registry: list failed (%s) — treating as empty", e)
        return []
    entries = [e for e in (_decode(v) for v in raw.values()) if e]
    return sorted(entries, key=lambda e: (e.get("staged_at", ""), e.get("canonical", "")))


def clear(workload_id):
    """Drop the workload's registry. Returns True if a hash existed. Raises on Redis failure."""
    return bool(_r().delete(key(workload_id)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "list":
        for e in list_objects(a[1]):
            print(f'{e["status"]:8} {e["canonical"]:40} {e["element_id"]:30} {e["type"]:22} '
                  f'{e["domain"]:15} views={",".join(e.get("views", []))}')
    elif len(a) >= 2 and a[0] == "imported":
        print(mark_imported(a[1], a[2:] or None))
    elif len(a) >= 2 and a[0] == "clear":
        print(clear(a[1]))
    else:
        sys.exit(__doc__)
