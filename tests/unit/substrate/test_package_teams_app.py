"""Packaging a Teams app — and the one number in it that may never change.

A Teams app ID is its IDENTITY. Teams treats a new id as a NEW APP: the old one keeps whatever it was
added to and the new one starts empty, so re-minting an id silently orphans every meeting, channel and
personal install. The packager derives it from the bot id so it is stable across re-packaging — and that
only holds if the SEED holds.

Caught 11 Oct 2026, by packaging both apps after generalising the script: adding the app name to the seed
looked tidy and re-minted the meeting app's id. Nothing would have failed; the app would simply have
arrived as a stranger.

Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/test_package_teams_app.py
"""
import importlib.util
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("pkg", ROOT / "scripts" / "package_teams_app.py")
pkg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pkg)


def test_the_meeting_apps_identity_is_the_formula_it_has_always_been():
    """If this ever has to change, it is a MIGRATION — every existing install is orphaned — and that
    should be a deliberate act, announced, not a consequence of tidying a script."""
    bot = "11111111-2222-3333-4444-555555555555"
    want = str(uuid.uuid5(uuid.NAMESPACE_URL, f"teams-app/{bot}"))
    assert pkg.render("h.example", bot, "n", "1.0.0", app="meeting")["id"] == want


def test_every_app_has_its_OWN_identity_from_the_same_bot():
    """The fabric app's bot IS the Copilot Studio agent's registration, which other things may also use.
    Two apps sharing a bot must not share an id, or installing one would replace the other."""
    bot = "11111111-2222-3333-4444-555555555555"
    ids = {name: pkg.render("h.example", bot, "n", "1.0.0", app=name)["id"] for name in pkg.APPS}
    assert len(set(ids.values())) == len(ids), ids


def test_the_notes_in_a_template_never_reach_the_package():
    """The template carries the reasoning beside what it explains; the Teams schema is CLOSED and reports
    any violation as "UnknownError", so a note left in would fail at upload with nothing to read."""
    m = pkg.render("h.example", "b", "n", "1.0.0", app="fabric")
    assert not [k for k in m if str(k).startswith("//")]
    assert pkg._strip_notes({"a": 1, "//a": "why", "b": [{"//c": "why", "c": 2}]}) == {"a": 1, "b": [{"c": 2}]}


@pytest.mark.parametrize("app", sorted(pkg.APPS))
def test_each_app_renders_with_no_placeholder_left_behind(app):
    """A `${...}` that survives means a value nobody supplied — and it reaches Teams as a literal."""
    import json
    m = pkg.render("h.example", "11111111-2222-3333-4444-555555555555", "n", "9.9.9", app=app)
    assert "${" not in str(m)
    assert m["version"] == "9.9.9" and m["validDomains"] == ["h.example"]


def test_the_fabric_manifest_carries_the_apps_own_key_on_every_surface_teams_loads():
    """The tab's drawing is gated on a key Teams cannot send as a header, so the manifest is what
    carries it. A package built without one renders a tab that is a 401 — visible only to whoever
    opens it, which is why the packager takes the key rather than defaulting it."""
    m = pkg.render("fab.example", "bot-1", "Fabric", "1.0.0", app="fabric", key="K3Y")
    urls = [m["staticTabs"][0]["contentUrl"], m["staticTabs"][0]["websiteUrl"],
            m["configurableTabs"][0]["configurationUrl"]]
    assert all(u.endswith("k=K3Y") for u in urls), urls


def test_the_meeting_manifest_has_no_app_key_to_leave_behind():
    """`${APP_KEY}` is the fabric template's alone. If it ever appeared unrendered in the other app's
    manifest, Teams would load a literal `${APP_KEY}` and the failure would be a blank tab."""
    m = pkg.render("m.example", "bot-2", "Meeting", "1.0.0", app="meeting")
    assert "${" not in str(m)
