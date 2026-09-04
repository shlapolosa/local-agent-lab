"""src/lab/platform/redis_client.py — the one Redis client seam. OFFLINE: constructing a client never
connects, so every check here runs without a Redis (the bogus-URL case expects a refusal)."""


import redis

from lab.substrate import approvals

from lab.platform import locks, redis_client, runlog, staged_registry, workflows


def test_cached_per_url():
    redis_client.reset()
    a = redis_client.client("redis://127.0.0.1:6390/0")
    b = redis_client.client("redis://127.0.0.1:6390/0")
    c = redis_client.client("redis://127.0.0.1:6390/1")
    assert a is b, "same url must return the same pooled client"
    assert a is not c, "a different url gets its own client"
    assert isinstance(a, redis.Redis)


def test_pool_shape():
    redis_client.reset()
    r = redis_client.client("redis://127.0.0.1:6390/0")
    pool = r.connection_pool
    assert pool.max_connections == redis_client.DEFAULT_MAX_CONNECTIONS == 4
    assert pool.connection_kwargs.get("decode_responses") is True
    assert pool.connection_kwargs.get("socket_timeout") == redis_client.SOCKET_TIMEOUT_S
    r2 = redis_client.client("redis://127.0.0.1:6390/2", max_connections=9)
    assert r2.connection_pool.max_connections == 9


def test_default_is_config_url():
    from lab.platform import config
    redis_client.reset()
    assert redis_client.client() is redis_client.client(config.REDIS_URL)


def test_modules_share_the_seam():
    """approvals / workflows / locks / staged_registry all resolve to the SAME cached client —
    that is the point of the seam (one pool per host, not one per module)."""
    redis_client.reset()
    r = redis_client.client()
    assert approvals._r() is r
    assert workflows._r() is r
    assert locks._r() is r
    assert staged_registry._r() is r
    assert runlog._client() is r


def test_reset_drops_cache():
    a = redis_client.client("redis://127.0.0.1:6390/0")
    redis_client.reset()
    assert redis_client.client("redis://127.0.0.1:6390/0") is not a


def test_injection_bypasses_cache():
    """A caller-supplied client is used as-is (locks' `client=`): a bogus one fails fast with the
    module's own error, and the cache is untouched."""
    redis_client.reset()
    bogus = redis.Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.3, socket_timeout=0.3)
    try:
        with locks.lock("rc-test", ttl=5, wait=0, client=bogus):
            raise AssertionError("entered block on a bogus client")
    except locks.LockUnavailable:
        pass
    assert "redis://127.0.0.1:1/0" not in redis_client._CLIENTS


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  [PASS] {name}")
    print("test_redis_client: ALL PASSED")
