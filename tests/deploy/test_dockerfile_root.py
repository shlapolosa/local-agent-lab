"""Every image that ships the lab's code can find its repo root at import time.

`lab.platform.config` searches upward for pyproject.toml + skills/ and RAISES when it finds neither,
so an image that copies only `src/` (the voiceprint service does: it needs three modules, not the
workspace) must state its root as configuration. Learned when that image failed CI's smoke import
on 43e09b5 — a failure this test would have caught offline.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILES = sorted(p for p in (ROOT / "deploy").rglob("Dockerfile*") if p.is_file())


def test_the_images_are_found():
    assert ROOT / "deploy" / "Dockerfile" in DOCKERFILES


@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_an_image_with_the_code_can_find_its_root(dockerfile):
    text = dockerfile.read_text()
    if not re.search(r"^COPY\s+src/", text, re.M):
        return
    declared = re.search(r"^ENV\b.*\bLAB_REPO_ROOT=", text, re.M)
    searchable = re.search(r"^COPY\s+pyproject\.toml\b", text, re.M) and re.search(r"^COPY\s+skills/", text, re.M)
    assert declared or searchable, f"{dockerfile.name}: COPY pyproject.toml and skills/, or set ENV LAB_REPO_ROOT"


def test_the_full_image_carries_what_hangs_off_its_root():
    """A search that succeeds guarantees skills/ (it is the marker), not config/. Paths derived from
    the root fail QUIETLY when absent — FABRIC_OWNER_MAP defaults to config/fabric-owners.json, and a
    missing map leaves every owner unresolved instead of raising."""
    text = (ROOT / "deploy" / "Dockerfile").read_text()
    for d in ("skills/", "config/"):
        assert re.search(rf"^COPY\s+{re.escape(d)}\s+/app/{re.escape(d)}", text, re.M), d
    assert (ROOT / "config" / "fabric-owners.json").is_file()
