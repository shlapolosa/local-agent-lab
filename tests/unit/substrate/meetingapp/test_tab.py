"""lab.substrate.meetingapp.tab — the pages Teams loads when the app is added to a meeting.

Adding the app with "+" goes through its tab's CONFIGURATION page, and Teams will not finish the add —
so never installs the bot — until that page says it is valid and saves. Measured 6 Oct 2026: with no
page (404) the dialog showed "Not Found" with Save disabled, and closing it cancelled the whole opt-in.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/meetingapp/test_tab.py"""
from fastapi.testclient import TestClient

from lab.substrate.meetingapp import service, tab


def client():
    return TestClient(service.web(client_state="s"))


def test_the_config_page_makes_the_add_saveable_and_points_the_tab_at_the_status_page():
    r = client().get("/tab/config")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "setValidityState(true)" in r.text and "registerOnSaveHandler" in r.text
    assert "/tab" in r.text and tab.TEAMS_JS in r.text


def test_the_status_page_and_the_manifests_two_policy_links_resolve():
    c = client()
    for path in ("/tab", "/tab/privacy", "/tab/terms"):
        r = c.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html"), path
    assert "consent" in c.get("/tab/privacy").text.lower()
