"""The substrate's composition root: the platform container (config, redis, tracer) plus the adapters
only the shared plane may hold — the artifact store and the upload store (file:// | postgres | s3 →
Railway Bucket / Azure Blob via its S3 gateway). MCP servers and the review app build THIS container;
workloads build `lab.platform.container` and never see a store credential.

    from lab.substrate.container import build
    c = build("adoit-mcp")
    c.wire(modules=[__name__])
"""
from dependency_injector import providers

from lab.platform.container import CONFIG_KEYS, Container, configure
from lab.substrate import artifacts as _artifacts

# the platform allowlist + the store settings that exist ONLY here
SUBSTRATE_KEYS = CONFIG_KEYS + ("ARTIFACTS_URL", "UPLOADS_URL", "S3_ENDPOINT", "S3_REGION",
                                "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_URL_STYLE")


class SubstrateContainer(Container):
    """Inherits config/redis/tracer; adds the store ports → adapters chosen by URL scheme.

    No second pool: `lab.platform.redis_client.client()` and `lab.substrate.artifacts.store()` are
    memoised per URL inside their modules, so these Singleton providers hand out the SAME client /
    store objects a legacy direct call returns for that URL (verified by tests/unit/substrate/
    test_container.py) — a process that mixes both paths still holds one Redis pool and one store
    client per URL."""

    artifacts = providers.Singleton(_artifacts.store, url=Container.config.artifacts_url)   # specs, XML, SVG, XLSX
    uploads = providers.Singleton(_artifacts.store, url=Container.config.uploads_url)       # submitted inputs (bucket in the cloud)


def build(service_name: str, *, instrument_urllib: bool = False, **overrides) -> SubstrateContainer:
    return configure(SubstrateContainer(), service_name, keys=SUBSTRATE_KEYS,
                     instrument_urllib=instrument_urllib, **overrides)
