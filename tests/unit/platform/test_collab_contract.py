"""CollabTools — the collaboration PORT (files + meetings), vendor-neutral by construction."""
import pytest

from lab.platform.contracts import CollabTools


def test_alias_and_tools_name_no_vendor():
    """A Microsoft Graph adapter satisfies this port today; a Google Workspace one could tomorrow."""
    banned = ("microsoft", "graph", "sharepoint", "onedrive", "teams", "m365", "entra")
    assert not [v for v in banned if v in CollabTools.SERVER.lower()]
    assert not [n for n in CollabTools.names() for v in banned if v in n.lower()]
    assert CollabTools.SERVER == "collab_mcp"


def test_read_and_write_are_separate_grants():
    """Subscription management is egress to a caller-supplied URL and a durable tenant-side object —
    it must be grantable apart from reading, like ApprovalTools.READ/.WRITE."""
    read, write = set(CollabTools.READ), set(CollabTools.WRITE)
    assert read and write and not (read & write)
    assert read | write == set(CollabTools.names()), "every tool belongs to exactly one grant"
    assert write == {CollabTools.watch, CollabTools.watch_renew, CollabTools.unwatch}


def test_tuples_are_not_mistaken_for_tools():
    """`names()` filters to str attributes, so the grant tuples stay out of the catalogue."""
    assert "READ" not in CollabTools.names() and "WRITE" not in CollabTools.names()
    assert all(isinstance(n, str) for n in CollabTools.names())


def test_gateway_qualifies_and_rejects_a_foreign_tool():
    assert CollabTools.gateway(CollabTools.sites) == "collab_mcp-collab_sites"
    with pytest.raises(ValueError):
        CollabTools.gateway("storage_get")


def test_the_catalogue_covers_the_planned_surface():
    assert set(CollabTools.names()) == {
        "collab_capabilities", "collab_sites", "collab_drives", "collab_user_drive", "collab_list",
        "collab_item", "collab_meetings", "collab_recordings", "collab_transcripts", "collab_fetch",
        "collab_watches", "collab_watch", "collab_watch_renew", "collab_unwatch"}


def test_the_port_is_registered_so_the_gateway_and_the_smoke_test_can_see_it():
    """A catalogue that is not in `SERVERS` is invisible to the parity test, to the gateway alias
    check and to scripts/e2e_smoke.py — i.e. an ungoverned server nothing notices is missing."""
    from lab.platform.contracts import ALL_TOOLS, SERVERS
    assert SERVERS[CollabTools.SERVER] is CollabTools
    assert set(CollabTools.names()) <= ALL_TOOLS


def test_a_persons_own_drive_is_part_of_the_read_grant():
    """A meeting recorded ad hoc is stored in the organiser's own drive, not in any site library, so
    reaching a person's drive is a READ verb — the only route to such content."""
    assert CollabTools.user_drive == "collab_user_drive"
    assert CollabTools.user_drive in CollabTools.READ


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))


def test_the_notification_allowlist_is_parsed_as_a_list_because_an_empty_one_refuses_everything():
    """A security-relevant parse: `GRAPH_NOTIFICATION_ALLOWLIST` is the only thing standing between a
    caller-supplied notification URL and egress, so how it splits is worth pinning."""
    import importlib
    import os
    from lab.platform import config
    saved = dict(os.environ)
    try:
        os.environ["GRAPH_NOTIFICATION_ALLOWLIST"] = " https://a.example , https://b.example ,"
        os.environ["GRAPH_MEETING_USERS"] = "one@lab.example,two@lab.example"
        importlib.reload(config)
        assert config.GRAPH_NOTIFICATION_ALLOWLIST == ("https://a.example", "https://b.example")
        assert config.GRAPH_MEETING_USERS == ("one@lab.example", "two@lab.example")
        os.environ.pop("GRAPH_NOTIFICATION_ALLOWLIST")
        importlib.reload(config)
        assert config.GRAPH_NOTIFICATION_ALLOWLIST == ()          # unset means REFUSE, never allow-all
    finally:
        os.environ.clear(); os.environ.update(saved)
        importlib.reload(config)
