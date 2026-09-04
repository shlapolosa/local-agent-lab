"""lab.substrate.review.uploads — the local-dev uploader: files -> the UPLOAD store -> art:// refs,
and its CLI (`python -m lab.substrate.review.uploads upload <files>`). Substrate side by design (a
workload never opens the store). Offline: the store is faked.
Run: .venv/bin/python tests/unit/substrate/review/test_uploads.py   (also pytest-compatible)"""
import contextlib
import io
import os
import runpy
import sys
from types import SimpleNamespace

from lab.substrate import artifacts
from lab.substrate.review import uploads as U


def _fake_artifacts(monkey):
    puts = []

    def put_file(path, content_type=None, target=None):
        puts.append((path, content_type, target))
        return f"art://{len(puts)}/{os.path.basename(path)}"
    monkey.put_file, monkey.uploads = put_file, lambda: "UPLOAD-STORE"
    return puts


def test_upload_stores_each_file_in_the_upload_store_with_its_content_type():
    fake = SimpleNamespace(content_type_for=artifacts.content_type_for)
    puts = _fake_artifacts(fake)
    saved = U.artifacts
    U.artifacts = fake
    try:
        refs = U.upload(["/in/sys.vsdx", "/in/req.docx"])
    finally:
        U.artifacts = saved
    assert refs == ["art://1/sys.vsdx", "art://2/req.docx"]
    assert puts == [("/in/sys.vsdx", artifacts.content_type_for("sys.vsdx"), "UPLOAD-STORE"),
                    ("/in/req.docx", artifacts.content_type_for("req.docx"), "UPLOAD-STORE")]


def _run_cli(argv):
    saved_argv, saved = sys.argv, (artifacts.put_file, artifacts.uploads)
    puts = _fake_artifacts(artifacts)
    sys.argv, buf = ["uploads.py", *argv], io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            runpy.run_module("lab.substrate.review.uploads", run_name="__main__", alter_sys=True)
    finally:
        sys.argv = saved_argv
        artifacts.put_file, artifacts.uploads = saved
    return puts, buf.getvalue()


def test_cli_upload_prints_ref_per_file():
    puts, out = _run_cli(["upload", "/in/sys.vsdx", "/in/req.md"])
    assert [p[0] for p in puts] == ["/in/sys.vsdx", "/in/req.md"]
    assert out == "art://1/sys.vsdx\t/in/sys.vsdx\nart://2/req.md\t/in/req.md\n"


def test_cli_usage_exits_without_files():
    for argv in ([], ["upload"], ["list", "x"]):
        try:
            _run_cli(argv)
            raise AssertionError("usage -> SystemExit")
        except SystemExit as e:
            assert "usage:" in str(e)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("ok", name)
    print("ALL TESTS PASSED")
