"""lab.substrate.review.uploads — the command-line uploader: files -> `/api/uploads` -> art:// refs.

A client of the seam like the review app it belongs to: it hands bytes to the LabApi client and never
opens a store. Offline: the client is faked.
"""
import contextlib
import io

import pytest

from lab.platform.filetypes import content_type_for
from lab.substrate.review import uploads as U


class FakeClient:
    def __init__(self):
        self.puts = []

    def upload(self, name, data, content_type):
        self.puts.append((name, data, content_type))
        return f"art://{len(self.puts)}/{name}"


@pytest.fixture
def files(tmp_path):
    a, b = tmp_path / "sys.vsdx", tmp_path / "req.docx"
    a.write_bytes(b"VSDX"); b.write_bytes(b"DOCX")
    return str(a), str(b)


def test_upload_sends_each_file_by_name_with_its_content_type(files):
    client = FakeClient()
    assert U.upload(list(files), client=client) == ["art://1/sys.vsdx", "art://2/req.docx"]
    assert client.puts == [("sys.vsdx", b"VSDX", content_type_for("sys.vsdx")),
                           ("req.docx", b"DOCX", content_type_for("req.docx"))]


def test_cli_upload_prints_ref_per_file(files):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        U.main(["upload", *files], client=FakeClient())
    assert buf.getvalue() == f"art://1/sys.vsdx\t{files[0]}\nart://2/req.docx\t{files[1]}\n"


def test_cli_usage_exits_without_files():
    for argv in ([], ["upload"], ["list", "x"]):
        with pytest.raises(SystemExit, match="usage:"):
            U.main(argv, client=FakeClient())
