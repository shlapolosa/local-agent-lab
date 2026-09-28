"""A pin holds what a run CANNOT work without, strictly — and what only enriches it, if published.

The server fails a WHOLE pin on one artifact with no release (`pg_library.pin`). Pinning a private
master nobody uploaded therefore failed every run at the pin — before any "optional corpus" logic
could run — while the test double froze whatever it was asked for, so every test said otherwise
(review, 28 Sep 2026). Optional artifacts are now checked against the catalogue first.
"""
import asyncio

import pytest

from lab.platform.contracts import ReferenceTools
from lab.workloads.usecase import reference


def _gateway(monkeypatch, published, *, catalogue_fails=False):
    asked = {}

    async def call(cfg, tool, args):
        if tool == ReferenceTools.catalogue:
            if catalogue_fails:
                raise RuntimeError("catalogue down")
            return {"artifacts": [{"artifact_id": a, "version": "v1"} for a in published]}
        if tool == ReferenceTools.pin:
            asked["ids"] = list(args["artifact_ids"])
            missing = [a for a in asked["ids"] if a not in published]
            if missing:
                raise RuntimeError(f"reference unavailable: {missing[0]}")
            return {"pin_id": "p1", "versions": [{"artifact_id": a, "version": "v1"}
                                                 for a in asked["ids"]]}
        raise AssertionError(tool)
    monkeypatch.setattr(reference.gateway, "call", call)
    return asked


def test_an_unpublished_OPTIONAL_artifact_is_left_out_of_the_pin_and_named(monkeypatch):
    asked = _gateway(monkeypatch, {"map", "ontology-concepts"})
    out = asyncio.run(reference.pin({}, ["map"], optional=["ontology-concepts", "private-x"]))
    assert asked["ids"] == ["map", "ontology-concepts"]
    assert out["unpublished"] == ["private-x"]


def test_an_unpublished_REQUIRED_artifact_still_fails_the_pin(monkeypatch):
    _gateway(monkeypatch, {"ontology-concepts"})
    with pytest.raises(RuntimeError, match="map"):
        asyncio.run(reference.pin({}, ["map"], optional=["ontology-concepts"]))


def test_a_catalogue_that_cannot_be_read_pins_the_required_set_and_names_every_optional(monkeypatch):
    """Degrade toward running: the optional artifacts are unavailable, not the run."""
    asked = _gateway(monkeypatch, {"map", "ontology-concepts"}, catalogue_fails=True)
    out = asyncio.run(reference.pin({}, ["map"], optional=["ontology-concepts"]))
    assert asked["ids"] == ["map"] and out["unpublished"] == ["ontology-concepts"]


def test_no_optional_artifacts_never_asks_the_catalogue(monkeypatch):
    asked = _gateway(monkeypatch, {"map"})
    out = asyncio.run(reference.pin({}, ["map"]))
    assert asked["ids"] == ["map"] and out["unpublished"] == []
