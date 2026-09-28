"""The publisher's PRIVATE branch — the privacy boundary for masters this public repository may not
carry (review findings F4, 28 Sep 2026). The script is TDD-exempt; this branch is not, because it
decides what content reaches the corpus under a new version."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("_pub", ROOT / "scripts" / "publish_usecase_corpus.py")
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)

AID = sorted(pub.PRIVATE)[0]


def _local(tmp_path, monkeypatch, text):
    monkeypatch.setattr(pub, "PRIVATE_DIR", tmp_path)
    (tmp_path / pub.master_for(AID).name).write_text(text)


def test_a_private_master_with_no_ref_is_deferred_by_name(tmp_path, monkeypatch):
    _local(tmp_path, monkeypatch, "# t\n")
    args, why = pub.private_source(AID, {}, fetch=lambda ref: b"")
    assert args is None and "carries no" in why


def test_the_ref_is_published_when_it_holds_EXACTLY_what_was_imported(tmp_path, monkeypatch):
    _local(tmp_path, monkeypatch, "# imported\n")
    name = pub.master_for(AID).name
    args, why = pub.private_source(AID, {name: f"art://x/{name}"},
                                   fetch=lambda ref: b"# imported\n")
    assert args[:2] == ["--master-ref", f"art://x/{name}"] and not why


def test_a_STALE_upload_is_refused_rather_than_published_under_the_new_version(tmp_path,
                                                                             monkeypatch):
    """Re-import, forget to re-upload, publish: the ref holds last release's rows and they would
    go out signed under the new version — silently, and for content that may not be public."""
    _local(tmp_path, monkeypatch, "# re-imported, newer\n")
    name = pub.master_for(AID).name
    args, why = pub.private_source(AID, {name: f"art://x/{name}"}, fetch=lambda ref: b"# older\n")
    assert args is None and "not the file imported" in why


def test_two_refs_with_one_file_name_are_refused():
    with pytest.raises(ValueError, match="same file name"):
        pub.private_refs(("art://a/x.md", "art://b/x.md"))


def test_refs_are_keyed_by_file_name():
    assert pub.private_refs(("art://a/one.md", " art://b/two.md ")) == {
        "one.md": "art://a/one.md", "two.md": "art://b/two.md"}
