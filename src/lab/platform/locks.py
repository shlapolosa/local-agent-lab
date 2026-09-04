"""Distributed lock over the lab's Redis — serialise a write-critical section across replicas.

Why: several workflow-consumer replicas may process different views of ONE workload at the same
time. The resolve -> architect -> stage section decides whether a shared element is NEW or reused
(e.g. "API Gateway (Kong)"); if two replicas run it concurrently for the same workload they both
see "not found" and both create it. Holding `workload_lock(workload_id)` around that section
makes it one-at-a-time per workload. A single replica needs no lock; this makes N replicas safe.

Mechanism (the standard single-instance Redis lock, nothing more):
  acquire  SET lock:<name> <uuid4> NX EX <ttl>      polled up to `wait` s  -> LockTimeout
  release  Lua compare-and-delete   (DEL only if the stored token is OURS)
  renew    Lua compare-and-expire   (EXPIRE only if the stored token is OURS)
The token check is what makes it correct: if our TTL expires mid-section and another replica
acquires the key, our exit must NOT delete THEIR lock — with a plain DEL it would.

Degradation is EXPLICIT: if Redis cannot be reached the lock raises `LockUnavailable` instead of
silently proceeding unlocked. The caller decides — a single-replica deployment may catch it and
continue (`except LockUnavailable: ...`), a multi-replica one must fail the run. TTL is the safety
net for a crashed holder: size it above the section's worst case, or call `handle.renew()` from
long steps.

Usage:
    from lab.platform.locks import workload_lock, LockTimeout, LockUnavailable
    with workload_lock(workload_id, ttl=300, wait=120) as lk:
        ...resolve existing...
        lk.renew()                     # optional, before a long step
        ...stage...

Uses the process-wide pooled client from src/lab/platform/redis_client.py (as every Redis-backed shared
module does), so a host holds one small pool, not one per module. Dependency-free beyond `redis`.
"""
import logging
import time
import uuid
from contextlib import contextmanager

import redis

from lab.platform import redis_client

log = logging.getLogger(__name__)

PREFIX = "lock:"

# Lua: atomic compare-and-delete — never delete a lock we no longer own.
RELEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("DEL", KEYS[1])
end
return 0
"""

# Lua: atomic compare-and-expire — extend only while we still own the key.
RENEW_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("EXPIRE", KEYS[1], ARGV[2])
end
return 0
"""

_UNAVAILABLE = (redis.ConnectionError, redis.TimeoutError)   # ConnectionError covers auth/busy-loading too


class LockError(Exception):
    """Base class for lock failures."""


class LockTimeout(LockError):
    """Another holder kept the lock for the whole `wait` window."""


class LockUnavailable(LockError):
    """Redis could not be reached — the caller must decide whether to proceed unlocked."""


def _r():
    """The process-wide pooled client (lab.platform.redis_client); `client=` on lock() overrides it."""
    return redis_client.client()


def _s(v):
    """Normalise a Redis reply to str whether or not the client decodes responses."""
    return v.decode() if isinstance(v, bytes) else v


class LockHandle:
    """What `lock()` yields: the token plus renew/held/release against that exact token."""

    __slots__ = ("name", "key", "token", "ttl", "_r", "_released")

    def __init__(self, name, token, ttl, client):
        self.name, self.key, self.token, self.ttl = name, PREFIX + name, token, ttl
        self._r, self._released = client, False

    def renew(self, extra=None):
        """Reset the TTL to `extra` seconds (default: the original ttl) if we still hold the lock.
        Returns True if extended, False if the lock is no longer ours (expired / taken over)."""
        extra = int(self.ttl if extra is None else extra)
        if extra <= 0:
            raise ValueError("extra must be a positive number of seconds")
        try:
            return bool(self._r.eval(RENEW_SCRIPT, 1, self.key, self.token, extra))
        except _UNAVAILABLE as e:
            raise LockUnavailable(f"redis unreachable while renewing {self.key}: {e}") from e

    def held(self):
        """True while the key still carries OUR token."""
        try:
            return _s(self._r.get(self.key)) == self.token
        except _UNAVAILABLE as e:
            raise LockUnavailable(f"redis unreachable while checking {self.key}: {e}") from e

    def release(self):
        """Compare-and-delete. Returns True if we deleted our lock, False if it was not ours
        (already expired, or expired and re-acquired by another holder — left untouched)."""
        if self._released:
            return False
        self._released = True
        return bool(self._r.eval(RELEASE_SCRIPT, 1, self.key, self.token))

    def __repr__(self):
        return f"LockHandle({self.name!r}, token={self.token[:8]}…, ttl={self.ttl})"


@contextmanager
def lock(name, *, ttl=300, wait=120, poll=0.25, client=None):
    """Hold `lock:<name>` for the duration of the block.

    ttl   seconds before Redis drops the key on its own (crash safety); renew() extends it
    wait  seconds to keep polling for the lock before raising LockTimeout (0 = one attempt)
    poll  seconds between attempts
    client  a redis.Redis to use instead of the shared pooled client (tests / dedicated pools)

    Raises LockTimeout (held by someone else) or LockUnavailable (Redis unreachable) BEFORE
    entering the block — the block never runs unlocked.
    """
    if not name or not isinstance(name, str):
        raise ValueError("lock name must be a non-empty str")
    ttl, wait, poll = int(ttl), float(wait), float(poll)
    if ttl <= 0 or wait < 0 or poll <= 0:
        raise ValueError("ttl and poll must be > 0, wait must be >= 0")

    r = client if client is not None else _r()
    key, token = PREFIX + name, uuid.uuid4().hex
    deadline = time.monotonic() + wait
    attempts = 0
    while True:
        attempts += 1
        try:
            if r.set(key, token, nx=True, ex=ttl):
                break
        except _UNAVAILABLE as e:
            raise LockUnavailable(f"redis unreachable while acquiring {key}: {e}") from e
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LockTimeout(f"{key} still held after {wait:g}s ({attempts} attempts)")
        time.sleep(min(poll, remaining))

    handle = LockHandle(name, token, ttl, r)
    try:
        yield handle
    finally:
        # The section is over; a release failure cannot make it unsafe (TTL still bounds the
        # key) and must not mask an exception from the block — so log, never raise, here.
        try:
            if not handle.release():
                log.warning("%s was not ours at exit (expired or taken over) — not deleted", key)
        except _UNAVAILABLE as e:
            log.warning("%s: redis unreachable at release (%s); key expires by ttl=%ss", key, e, ttl)


def workload_lock(workload_id, **kw):
    """The write-critical section of one workload (resolve -> architect -> stage)."""
    if not workload_id:
        raise ValueError("workload_id is required")
    return lock(f"workload:{workload_id}:write", **kw)


__all__ = ["lock", "workload_lock", "LockHandle", "LockError", "LockTimeout", "LockUnavailable",
           "RELEASE_SCRIPT", "RENEW_SCRIPT", "PREFIX"]
