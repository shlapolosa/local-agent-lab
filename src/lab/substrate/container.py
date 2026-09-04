"""The substrate's composition root: the platform container (config, redis, tracer) plus the adapters
only the shared plane may hold — the artifact store and the upload store (file:// | postgres | s3 →
Railway Bucket / Azure Blob via its S3 gateway), and the COLLABORATION provider (files + meetings,
chosen from `COLLAB_PROVIDERS` by the `COLLAB_PROVIDER` setting). MCP servers and the review app
build THIS container; workloads build `lab.platform.container` and never see a store or provider
credential.

    from lab.substrate.container import build
    c = build("adoit-mcp")
    c.wire(modules=[__name__])
"""
import importlib

from dependency_injector import providers

from lab.platform.container import CONFIG_KEYS, Container, configure
from lab.substrate import artifacts as _artifacts

# the platform allowlist + the store settings that exist ONLY here
SUBSTRATE_KEYS = CONFIG_KEYS + ("ARTIFACTS_URL", "UPLOADS_URL", "S3_ENDPOINT", "S3_REGION",
                                "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_URL_STYLE",
                                "COLLAB_PROVIDER", "SPEECH_PROVIDER")

# The COLLABORATION port's adapters, by name: the ONE place a provider module is named. The
# container binds a KEY (`COLLAB_PROVIDER`), so a second collaboration platform — a different
# files-and-meetings vendor — is one entry here plus its own adapter package, and neither the
# container, the server nor any caller changes. The module must expose `build(**overrides)`.
COLLAB_PROVIDERS: dict[str, str] = {"graph": "lab.substrate.mcp.graph.graph_repository"}

# The SPEECH port's adapters, by name — the same shape and for the same reason. Research settled the
# first one, but not permanently: a second provider (one whose cloud is out of region, or one whose
# diarization keeps speaker labels stable across a long recording) is one entry here plus its adapter.
SPEECH_PROVIDERS: dict[str, str] = {"munsit": "lab.substrate.mcp.speech.repository"}


def collab_repository(provider: str, **overrides):
    """The `lab.core.collab.CollabRepository` this deployment runs. Imported LAZILY by name so the
    substrate container — which every MCP server and the review app build — does not drag a
    provider SDK into processes that will never call one; the adapter's own `build()` stays the only
    place its configuration is read."""
    # No default HERE: `lab.platform.config` is the one env reader and owns the default, and the
    # platform tier cannot import this module — so a second fallback would be a second home for the
    # same decision, silently disagreeing the day one of them changed.
    name = str(provider or "").strip().lower()
    if name not in COLLAB_PROVIDERS:
        raise ValueError(f"unknown collaboration provider {name!r} — COLLAB_PROVIDER must be one of "
                         f"{sorted(COLLAB_PROVIDERS)}")
    return importlib.import_module(COLLAB_PROVIDERS[name]).build(**overrides)


def speech_transcriber(provider: str, **overrides):
    """The `lab.core.speech.Transcriber` this deployment runs. Imported LAZILY by name, for the same
    reason as the collaboration adapter: only the speech role should ever load a speech provider."""
    name = str(provider or "").strip().lower()
    if name not in SPEECH_PROVIDERS:
        raise ValueError(f"unknown speech provider {name!r} — SPEECH_PROVIDER must be one of "
                         f"{sorted(SPEECH_PROVIDERS)}")
    return importlib.import_module(SPEECH_PROVIDERS[name]).build(**overrides)


class SubstrateContainer(Container):
    """Inherits config/redis/tracer; adds the store ports → adapters chosen by URL scheme.

    No second pool: `lab.platform.redis_client.client()` and `lab.substrate.artifacts.store()` are
    memoised per URL inside their modules, so these Singleton providers hand out the SAME client /
    store objects a legacy direct call returns for that URL (verified by tests/unit/substrate/
    test_container.py) — a process that mixes both paths still holds one Redis pool and one store
    client per URL."""

    artifacts = providers.Singleton(_artifacts.store, url=Container.config.artifacts_url)   # specs, XML, SVG, XLSX
    uploads = providers.Singleton(_artifacts.store, url=Container.config.uploads_url)       # submitted inputs (bucket in the cloud)
    # the collaboration provider (files + meetings), by registry key — the graph-mcp role's adapter
    collab = providers.Singleton(collab_repository, provider=Container.config.collab_provider)
    # the speech provider (recorded talk -> attributable words) — the speech-mcp role's adapter
    speech = providers.Singleton(speech_transcriber, provider=Container.config.speech_provider)


def build(service_name: str, *, instrument_urllib: bool = False, **overrides) -> SubstrateContainer:
    return configure(SubstrateContainer(), service_name, keys=SUBSTRATE_KEYS,
                     instrument_urllib=instrument_urllib, **overrides)
