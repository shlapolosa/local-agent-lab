"""Where the repo is: from configuration, else found by searching upward — never by counting parents.

`parents[3]` was true only while config.py sat exactly three levels under the root. Moving the
kernel into `packages/kernel/src/lab/platform/` (the monorepo plan) would silently point REPO_ROOT,
and with it `var/`, `skills/` and `config/`, at `packages/`.
"""
from pathlib import Path

import pytest

from lab.platform import config


def _workspace(tmp_path: Path) -> Path:
    """A workspace root carrying every plausible marker, with a member package nested inside it."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "lab"\n\n[tool.uv.workspace]\nmembers = ["packages/*"]\n')
    for d in ("skills", "config", ".git"):
        (tmp_path / d).mkdir()
    pkg = tmp_path / "packages" / "kernel"
    (pkg / "src" / "lab" / "platform").mkdir(parents=True)
    (pkg / "pyproject.toml").write_text('[project]\nname = "lab-kernel"\n')
    return pkg / "src" / "lab" / "platform"


def test_the_current_layout_resolves_to_the_checkout():
    root = config.find_repo_root(Path(config.__file__).resolve().parent)
    assert (root / "skills").is_dir() and (root / "config").is_dir()
    assert root == config.REPO_ROOT


def test_a_member_package_is_not_mistaken_for_the_workspace(tmp_path):
    assert config.find_repo_root(_workspace(tmp_path)) == tmp_path


def test_no_root_found_fails_loudly(tmp_path):
    lone = tmp_path / "a" / "b"
    lone.mkdir(parents=True)
    with pytest.raises(RuntimeError):
        config.find_repo_root(lone)


def test_the_setting_wins_over_the_search(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_REPO_ROOT", str(tmp_path))
    assert config.repo_root() == tmp_path
