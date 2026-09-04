"""TDD: src/lab/substrate/container.py — the substrate's composition root EXTENDS the platform container
(lab.platform.container.Container: config, redis, tracer) with the substrate-only adapter: the artifact
store (file:// | postgres | s3 → Azure Blob by config). Workloads never see it. Offline."""
import tempfile

import pytest
from dependency_injector.wiring import Provide, inject

from lab.platform import config
from lab.platform.container import Container
from lab.substrate.container import SUBSTRATE_KEYS, SubstrateContainer, build


class FakeStore:
    def __init__(self): self.puts = []
    def put(self, name, data, content_type): self.puts.append(name); return f"art://fake/{name}"


class FakeRedis:
    def ping(self): return True


def test_extends_the_platform_container():
    assert issubclass(SubstrateContainer, Container)
    c = build("adoit-mcp")
    assert c.config.service_name() == "adoit-mcp"
    assert c.config.artifacts_url() == config.ARTIFACTS_URL
    assert c.config.redis_url() == config.REDIS_URL          # inherited providers read the SAME config
    assert c.config.uploads_url() == config.UPLOADS_URL
    assert {"ARTIFACTS_URL", "UPLOADS_URL"} <= set(SUBSTRATE_KEYS)   # the store keys live HERE, not in platform


def test_uploads_provider_uses_uploads_url_not_artifacts_url():
    """UPLOADS_URL (the bucket, cloud) diverges from ARTIFACTS_URL (Postgres): renders must not land in the
    bucket and uploads must not land in the artifact table."""
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as u:
        c = build("storage-mcp", artifacts_url=f"file://{a}", uploads_url=f"file://{u}")
        assert c.uploads() is c.uploads() and c.uploads() is not c.artifacts()
        ref = c.uploads().put("in.txt", b"x", "text/plain")
        assert ref.startswith("art://") and c.uploads().get(ref) == b"x"
        with pytest.raises(FileNotFoundError):
            c.artifacts().get(ref)                          # not in the artifact store


def test_artifact_store_provider_is_a_singleton_built_from_config():
    with tempfile.TemporaryDirectory() as d:
        c = build("adoit-mcp", artifacts_url=f"file://{d}")
        s1, s2 = c.artifacts(), c.artifacts()
        assert s1 is s2
        assert s1.put("x.json", b"{}", "application/json").startswith("art://")


def test_inherited_and_own_providers_can_be_overridden():
    c = build("adoit-mcp")
    fake = FakeStore()
    with c.artifacts.override(fake), c.redis.override(FakeRedis()):
        assert c.artifacts() is fake and c.redis().ping() is True
    assert c.artifacts.overridden == () and c.redis.overridden == ()


def test_singleton_providers_return_the_legacy_memoised_objects():
    """No second pool/client: artifacts.store(url) and redis_client.client(url) memoise per URL, so the
    container's Singletons hand out the SAME objects a direct call returns (see the class docstring)."""
    from lab.platform import redis_client
    from lab.substrate import artifacts
    with tempfile.TemporaryDirectory() as d:
        c = build("adoit-mcp", artifacts_url=f"file://{d}", uploads_url=f"file://{d}", redis_url="redis://127.0.0.1:1/9")
        assert c.artifacts() is artifacts.store(f"file://{d}") and c.uploads() is c.artifacts()
        assert c.redis() is redis_client.client("redis://127.0.0.1:1/9")     # constructing never connects


@inject
def _uses_store(name: str, store=Provide[SubstrateContainer.artifacts]):
    return store.put(name, b"", "text/plain")


def test_wiring_injects_the_store_and_explicit_kwargs_win():
    c = build("adoit-mcp")
    fake = FakeStore()
    with c.artifacts.override(fake):
        c.wire(modules=[__name__])
        try:
            assert _uses_store("a.txt") == "art://fake/a.txt" and fake.puts == ["a.txt"]
            other = FakeStore()
            assert _uses_store("b.txt", store=other) == "art://fake/b.txt" and other.puts == ["b.txt"]
        finally:
            c.unwire()


# ------------------------------------------------------------------ the collaboration provider
def test_the_collaboration_adapter_is_chosen_by_a_registry_not_named_in_code():
    """A second provider (a different collaboration platform) must be ONE registry entry, not an
    edit in the container, the server and the config — so the container names a KEY and the registry
    owns the module. The registry itself is the open/closed seam."""
    from lab.substrate.container import COLLAB_PROVIDERS
    assert COLLAB_PROVIDERS["graph"] == "lab.substrate.mcp.graph.graph_repository"
    assert "COLLAB_PROVIDER" in SUBSTRATE_KEYS
    assert build("graph-mcp").config.collab_provider() == config.COLLAB_PROVIDER


def test_an_unknown_or_empty_provider_names_itself_and_the_ones_that_exist():
    """No silent fallback in the container: `lab.platform.config` is the one env reader and owns the
    default, so an empty COLLAB_PROVIDER is a misconfiguration to say out loud, not to paper over."""
    from lab.substrate.container import collab_repository
    for bad in ("zoom", "", "   "):
        with pytest.raises(ValueError, match="unknown collaboration provider"):
            collab_repository(bad)
    with pytest.raises(ValueError, match="graph"):          # the message lists what IS registered
        collab_repository("zoom")


def test_the_collaboration_provider_is_lazy_and_overridable_like_any_other():
    """Building the container must not construct a provider client (no credential is read, nothing
    is imported) and a test swaps it exactly as it swaps redis or the stores."""
    c = build("graph-mcp")
    fake = object()
    with c.collab.override(fake):
        assert c.collab() is fake
    assert c.collab.overridden == ()


def test_the_registry_builds_the_named_adapter_with_the_overrides_it_is_given():
    """`collab_repository` is the composition root's one call: it resolves the key to the adapter's
    own `build()` and passes configuration through, so nothing below it reads the environment."""
    from lab.substrate.container import collab_repository
    from lab.core.collab import CollabRepository
    made = collab_repository("graph", auth_mode="none", tenant_id="", client_id="", client_secret="")
    assert isinstance(made, CollabRepository)


if __name__ == "__main__":
    import sys
    sys.exit(__import__("pytest").main([__file__, "-q"]))
