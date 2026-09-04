"""src/lab/core/collab/port.py — `CollabRepository`, the DOMAIN port for collaboration (files and
meetings). A Protocol only: it declares what the domain needs, names no provider, and holds no
behaviour of its own. The tests below double as its executable specification — the in-memory
`_Fake` is what any adapter must look like from outside.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/core/collab/test_port.py"""
import ast
import os
import sys

import pytest

from lab.core.collab import errors, model, port
from lab.core.collab.model import (ContentHandle, Drive, DriveItem, MediaKind, MediaRecord, Meeting,
                                   Page, Site, Watch, clamp_limit)
from lab.core.collab.port import CAPABILITIES, CollabRepository

PORT_METHODS = ("capabilities", "sites", "drives", "items", "item", "open", "meetings", "recordings",
                "transcripts", "watches", "watch", "renew", "unwatch")


class _Fake:
    """A complete, in-memory realisation of the port — the shape an adapter has to satisfy."""

    def capabilities(self, deep=False):
        return dict.fromkeys(CAPABILITIES, None) | {
            "recordings": errors.CollabUnavailable("recordings", "no grant", "ask an administrator")}

    def sites(self, query="", limit=None, cursor=None):
        return Page(items=(Site("s1", "Clinical Governance"),)[: clamp_limit(limit)])

    def drives(self, site_id, limit=None, cursor=None):
        return Page(items=(Drive("d1", "Documents", site_id),))

    def items(self, drive_id, path="", limit=None, cursor=None):
        return Page(items=(DriveItem("i1", "policy.docx", drive_id, path=path),), cursor="more")

    def item(self, handle):
        return DriveItem(handle.id, "policy.docx", handle.scope)

    def open(self, handle):
        yield b"bytes for " + str(handle).encode()

    def meetings(self, since="", until="", organizer="", limit=None, cursor=None):
        return Page(items=(Meeting("m1", "EA review", organizer or "maria", since, until),))

    def recordings(self, meeting_id, limit=None, cursor=None):
        return Page(items=(MediaRecord("r1", MediaKind.RECORDING, meeting_id),))

    def transcripts(self, meeting_id, limit=None, cursor=None):
        return Page(items=(MediaRecord("t1", MediaKind.TRANSCRIPT, meeting_id),))

    def watches(self, limit=None, cursor=None):
        return Page(items=(Watch("w1", "drives/d1/root", "https://flow.example/hook", ["created"]),))

    def watch(self, resource, notification_url, events, expires=""):
        return Watch("w1", resource, notification_url, events, expires)

    def renew(self, watch_id, expires):
        return Watch(watch_id, "drives/d1/root", "https://flow.example/hook", ["created"], expires)

    def unwatch(self, watch_id):
        return None


def test_the_port_is_a_runtime_checkable_protocol_any_adapter_can_satisfy_structurally():
    assert isinstance(_Fake(), CollabRepository)          # no inheritance needed — structural typing

    class Partial:
        def sites(self, query="", limit=None, cursor=None): ...

    assert not isinstance(Partial(), CollabRepository)


def test_the_port_declares_exactly_the_collaboration_verbs_and_nothing_else():
    declared = {n for n in vars(CollabRepository) if not n.startswith("_")}
    assert declared == set(PORT_METHODS)


def test_every_method_documents_its_contract():
    for name in PORT_METHODS:
        doc = getattr(CollabRepository, name).__doc__ or ""
        assert len(doc.strip()) > 60, f"{name} has no contract in its docstring"


def test_the_protocol_itself_holds_no_behaviour():
    """Explicit inheritance is allowed (an adapter may subclass for the docstrings); every inherited
    body is empty, so nothing is silently answered by the port."""

    class Stub(CollabRepository):
        pass

    stub = Stub()
    assert stub.capabilities() is None and stub.sites() is None and stub.drives("s1") is None
    assert stub.items("d1") is None and stub.item(ContentHandle.item("d", "i")) is None
    assert stub.open(ContentHandle.item("d", "i")) is None and stub.meetings() is None
    assert stub.recordings("m1") is None and stub.transcripts("m1") is None
    assert stub.watches() is None and stub.watch("r", "https://cb", ("created",)) is None
    assert stub.renew("w1", "2026-09-07T00:00:00Z") is None and stub.unwatch("w1") is None


def test_capabilities_answers_for_every_declared_area_with_a_typed_reason_or_none():
    caps = _Fake().capabilities()
    assert set(caps) == set(CAPABILITIES) and len(set(CAPABILITIES)) == len(CAPABILITIES)
    assert caps["sites"] is None                                        # available
    assert isinstance(caps["recordings"], errors.CollabUnavailable)     # and why it is not
    assert "Remedy" in caps["recordings"].sentence


def test_the_reading_verbs_return_domain_objects_page_by_page():
    fake = _Fake()
    assert [s.id for s in fake.sites()] == ["s1"]
    assert [d.id for d in fake.drives("s1")] == ["d1"]
    listing = fake.items("d1", path="Policies")
    assert listing.more and listing.items[0].path == "Policies"
    assert fake.item(ContentHandle.item("d1", "i1")).drive_id == "d1"
    assert b"".join(fake.open(ContentHandle.item("d1", "i1"))) == b"bytes for collab://item/d1/i1"


def test_the_meeting_verbs_answer_with_one_media_shape_for_both_kinds():
    fake = _Fake()
    assert [m.id for m in fake.meetings(organizer="omar")] == ["m1"]
    rec, = fake.recordings("m1").items
    tra, = fake.transcripts("m1").items
    assert rec.kind is MediaKind.RECORDING and tra.kind is MediaKind.TRANSCRIPT
    assert rec.handle.scope == tra.handle.scope == "m1"


def test_the_subscription_verbs_are_the_write_side_of_the_port():
    fake = _Fake()
    w = fake.watch("drives/d1/root", "https://flow.example/hook", ("created",), "2026-09-07T00:00:00Z")
    assert w.resource == "drives/d1/root" and w.expires == "2026-09-07T00:00:00Z"
    assert fake.renew("w1", "2026-09-14T00:00:00Z").expires == "2026-09-14T00:00:00Z"
    assert fake.unwatch("w1") is None and [x.id for x in fake.watches()] == ["w1"]


# ------------------------------------------------------------------ purity
def test_the_collaboration_domain_imports_nothing_but_the_standard_library_and_itself():
    """`lab.core` states what it needs and depends on nothing: no adapter, no kernel, no third party.
    (The tier ratchet in tests/governance/test_import_boundaries.py checks `lab.*`; this checks the
    rest — a stray `import msal`/`requests` here would drag a credential into the domain.)"""
    folder = os.path.dirname(model.__file__)
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(folder, name), encoding="utf-8").read())
        for node in ast.walk(tree):
            mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                    else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for mod in mods:
                root = mod.split(".")[0]
                assert not root or root in sys.stdlib_module_names or mod.startswith("lab.core.collab"), \
                    f"{name} imports {mod}"


def test_the_package_exports_the_whole_port_in_one_place():
    import lab.core.collab as collab

    assert set(collab.__all__) >= {"CollabRepository", "CAPABILITIES", "ContentHandle", "HandleKind",
                                   "Site", "Drive", "DriveItem", "Meeting", "MediaKind", "MediaRecord",
                                   "ChangeType", "Watch", "Page", "clamp_limit",
                                   "CollabError", "CollabUnavailable", "CollabNotConfigured",
                                   "CollabThrottled"}
    assert all(hasattr(collab, n) for n in collab.__all__)
    assert collab.CollabRepository is CollabRepository and collab.Site is model.Site
    assert port.CAPABILITIES is CAPABILITIES


@pytest.mark.parametrize("word", ["microsoft", "graph", "sharepoint", "onedrive", "teams", "m365",
                                  "office365", "entra", "azure"])
def test_no_module_in_the_domain_port_names_a_provider(word):
    """The port is neutral by construction: a provider's name appears in its ADAPTER and in the
    SERVICE that holds its credentials, never here — otherwise a second provider cannot satisfy it."""
    folder = os.path.dirname(model.__file__)
    for name in sorted(n for n in os.listdir(folder) if n.endswith(".py")):
        text = open(os.path.join(folder, name), encoding="utf-8").read().lower()
        assert word not in text, f"{name} names a provider: {word}"
