"""The lab's composition root for what EVERY tier needs (dependency-injector, user decision Sep 3 2026):
configuration, the pooled Redis client, the process tracer. The substrate extends it with its own
adapters (`lab.substrate.container`: the artifact store) — so this module never imports the substrate
and a workload container never carries store credentials.

Every process (workflow host, consumer, MCP server, review app) builds its container and receives
clients through providers — never by constructing Redis/Postgres/S3/OTel/chat clients itself. Rules
(enforced by tests/unit/platform/test_container.py + tests/governance/test_di_boundaries.py):
- Configuration enters from `lab.platform.config` (the one env reader), never raw `os.environ` here.
- `providers.*` / `DeclarativeContainer` appear ONLY in the two container modules; other modules take
  dependencies as parameters (`@inject` + `Provide[Container.x]`, or plain arguments).
- Tests swap any client with `container.<provider>.override(fake)`; the Azure move swaps adapters
  (Blob store, App Insights exporter, APIM URL) here or in `.env` — never in domain code.

    from lab.platform.container import build
    c = build("process-visio-to-archimate")      # config from lab.platform.config, service name for OTel
    c.wire(modules=[__name__])                    # then @inject functions receive providers
"""
from dependency_injector import containers, providers

from lab.platform import config as _config
from lab.platform import otel as _otel
from lab.platform import redis_client as _redis_client

# lab.platform.config names -> container config keys (lower-case). One table, so a new setting is one line.
# Deliberately an ALLOWLIST, never `vars(config)`: store URLs / S3 credentials are substrate-only
# (lab.substrate.container.SUBSTRATE_KEYS) — a workload container must never carry them (CLAUDE.md invariant).
CONFIG_KEYS = (
    "GATEWAY_URL", "GATEWAY_MCP_URL", "REDIS_URL",
    "ADOIT_MCP_URL", "SEMANTIC_MCP_URL", "STORAGE_MCP_URL", "WORKFLOW_MCP_URL",
    "REVIEW_APP_URL", "JAEGER_UI_URL",
    "BIND_HOST", "MCP_SHARED_SECRET", "ADOIT_REST_WRITE",
)


class Container(containers.DeclarativeContainer):
    """Ports → adapters. Singletons are per-container (one container per process)."""

    config = providers.Configuration()

    # Redis (limiter/approval streams/run-log/locks) — Azure Cache for Redis is still redis
    redis = providers.Singleton(_redis_client.client, url=config.redis_url)

    # Observability: the process tracer (no-op without an OTLP endpoint; App Insights = exporter swap)
    tracer = providers.Singleton(_otel.tracer, service=config.service_name,
                                 instrument_urllib=config.instrument_urllib)


def configure(c: Container, service_name: str, *, keys=CONFIG_KEYS, instrument_urllib: bool = False,
              **overrides) -> Container:
    """Feed `c.config` from `lab.platform.config` (the `keys` allowlist). `overrides` are config keys
    (lower-case) for tests or hosts that must diverge (e.g. `redis_url="redis://…"`). Shared by every
    tier's `build()`."""
    values = {k.lower(): getattr(_config, k) for k in keys}
    values.update(service_name=service_name, instrument_urllib=instrument_urllib, **overrides)
    c.config.from_dict(values)
    return c


def build(service_name: str, *, instrument_urllib: bool = False, **overrides) -> Container:
    """The platform container (config, redis, tracer) — what a workload host needs."""
    return configure(Container(), service_name, instrument_urllib=instrument_urllib, **overrides)
