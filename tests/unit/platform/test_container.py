"""TDD: src/lab/platform/container.py is the lab's composition root (dependency-injector, user decision Sep 3 2026)
for what EVERY tier needs — config, Redis, tracer. The substrate extends it (lab.substrate.container) with the
artifact store, so the platform never imports the substrate. Contract: configuration comes from
lab.platform.config (never raw os.environ in the container), every client is a provider that tests can override
with a fake, hosts receive dependencies via @inject/Provide, and NO other production module declares providers.
Offline: no Redis/Postgres/OTLP is touched."""
from dependency_injector import providers
from dependency_injector.wiring import Provide, inject

from lab.platform import config
from lab.platform.container import CONFIG_KEYS, Container, build


class FakeRedis:
    def __init__(self): self.pings = 0
    def ping(self): self.pings += 1; return True


def test_config_is_loaded_from_shared_config_not_env():
    c = build("test-svc")
    assert c.config.redis_url() == config.REDIS_URL
    assert c.config.gateway_url() == config.GATEWAY_URL
    assert c.config.mcp_shared_secret() == config.MCP_SHARED_SECRET
    assert c.config.service_name() == "test-svc"


def test_redis_provider_is_a_singleton_built_from_config_url():
    seen = []
    c = build("test-svc", redis_url="redis://example.invalid:6379/0")
    with c.redis.override(providers.Singleton(lambda: seen.append(1) or FakeRedis())):
        r1, r2 = c.redis(), c.redis()
        assert r1 is r2 and seen == [1]
    assert c.config.redis_url() == "redis://example.invalid:6379/0"


def test_providers_can_be_overridden_with_fakes():
    c = build("test-svc")
    fake = FakeRedis()
    with c.redis.override(fake):
        assert c.redis() is fake and c.redis().ping() is True
    assert c.redis.overridden == ()             # override is scoped


def test_platform_container_has_no_substrate_provider():
    assert not hasattr(Container, "artifacts"), "the artifact store is a substrate adapter — lab.substrate.container"
    assert not hasattr(Container, "uploads")


def test_workload_container_config_carries_no_store_credentials():
    """CLAUDE.md: workloads hold no store credentials — ARTIFACTS_URL falls back to DATABASE_URL (a DSN with
    a password), so it must not even be a platform config key."""
    assert not {k for k in CONFIG_KEYS if k in ("ARTIFACTS_URL", "UPLOADS_URL") or k.startswith("S3_")}
    c = build("process-x")
    assert not {k for k in c.config() if "artifacts" in k or "uploads" in k or k.startswith("s3_")}, c.config()


def test_tracer_provider_is_noop_without_an_otlp_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    c = build("test-svc")
    t = c.tracer()
    with t.start_as_current_span("x") as span:
        assert span is not None


@inject
def _pings(r=Provide[Container.redis]):
    return r.ping()


def test_wiring_injects_and_explicit_kwargs_win():
    c = build("test-svc")
    fake = FakeRedis()
    with c.redis.override(fake):
        c.wire(modules=[__name__])
        try:
            assert _pings() is True and fake.pings == 1
            other = FakeRedis()
            assert _pings(r=other) is True and other.pings == 1 and fake.pings == 1
        finally:
            c.unwire()


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
