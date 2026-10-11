"""The fabric's Teams app — four pages and a drawing, and no bot.

ONE app, not one per cohort: a Teams app declares SCOPES, so "steward" and "researcher" are where it is
installed and who is looking. NO bot code: the Copilot Studio agent the lab already runs is declared as
this app's bot and already holds `approvals_list · approvals_get · approvals_decide`. What this adds is
the one thing a conversation cannot be — a picture.

Offline: the gateway and the artifact store are both injected.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/fabricapp/
"""
import pytest
from fastapi.testclient import TestClient

from lab.platform.contracts import SemanticTools
from lab.substrate.fabricapp import service, tab


@pytest.fixture
def app():
    drawn = {"n": 0}

    async def call(calls):
        drawn["n"] += 1
        assert [n for n, _ in calls] == [SemanticTools.view_corpus]
        return [{"ref": f"art://corpus/{drawn['n']}.html"}]

    ticks = {"t": 0.0}
    client = TestClient(service.web(call=call, read=lambda ref: f"<html>{ref}</html>".encode(),
                                    now=lambda: ticks["t"]))
    client.drawn, client.ticks = drawn, ticks          # type: ignore[attr-defined]
    return client


def test_the_configuration_page_declares_itself_valid_or_the_tab_cannot_BE_added(app):
    """Measured on the meeting app, 6 Oct 2026: with no config page the add dialog showed "Not Found"
    with Save disabled, and closing it cancelled the whole opt-in. There is nothing to configure here,
    so the page says so and saves — but it must exist and must call `setValidityState`."""
    body = app.get("/tab/config").text
    assert "setValidityState(true)" in body and "registerOnSaveHandler" in body
    assert "setConfig" in body and "contentUrl" in body


def test_the_tab_lands_a_person_on_the_view_their_ROLE_came_for(app):
    """A courtesy, never a control. Every mode is one click away on the drawing itself, and authority
    lives in the gateway's per-tool grants — a hidden control would be security by absence."""
    assert "#vocabulary" in app.get("/tab?role=steward").text
    assert "#about" in app.get("/tab?role=researcher").text
    assert "#about" in app.get("/tab").text                 # no role: the join, which serves everyone
    assert "#about" in app.get("/tab?role=nonsense").text    # ...and an unknown role is not an error


def test_the_tab_SAYS_whose_credential_drew_it(app):
    """Identity propagation gateway->MCP is blocked, so reading on the viewer's behalf is not available.
    A corpus picture carries counts, labels and links and no document content, so one picture for
    everyone is honest — and saying so is the part that makes it honest rather than convenient."""
    body = app.get("/tab").text
    assert "fabric's own credential" in body and "never the content of a document" in body


def test_the_drawing_comes_from_the_GATEWAY_and_is_served_as_it_was_drawn(app):
    r = app.get("/corpus")
    assert r.status_code == 200 and "art://corpus/1.html" in r.text
    assert r.headers["content-type"].startswith("text/html")
    # A tab IS an iframe: the header that protects every other surface would make this one an empty box
    assert "x-frame-options" not in {k.lower() for k in r.headers}


def test_a_picture_a_minute_old_is_not_redrawn_for_every_viewer(app):
    """A whole-catalogue redraw is O(the catalogue) — 4.9 s at 61 records, measured — so a channel of
    five people opening a tab must not be five redraws. The records it describes do not change that
    fast; the projector debounces its own copy for the same reason."""
    for _ in range(4):
        app.get("/corpus")
    assert app.drawn["n"] == 1
    app.ticks["t"] = service.CACHE_S + 1
    app.get("/corpus")
    assert app.drawn["n"] == 2


def test_the_static_pages_are_there_because_a_manifest_PROMISES_them():
    """`privacyUrl` and `termsOfUseUrl` are required by the manifest and are fetched by Teams; a 404
    there fails validation at publish time, which is the worst moment to find out."""
    for page in (tab.privacy_page(), tab.terms_page()):
        assert page.lstrip().startswith("<!doctype html>") and "</html>" in page
    assert "does not read, store or display the contents" in tab.privacy_page()


def test_it_holds_no_bot_because_the_agent_IS_the_bot():
    """The whole reason this app is small. If bot code ever appears here, the decision of 11 Oct was
    reversed and that should be a deliberate act rather than a drift."""
    import lab.substrate.fabricapp as pkg
    from pathlib import Path
    names = {p.name for p in Path(pkg.__file__).parent.glob("*.py")}
    assert names == {"__init__.py", "service.py", "tab.py"}, names


# --- the gate -----------------------------------------------------------------------------------
# A tab binds to the open internet, and `netbind.refuse_open` exists so that a service which does
# cannot start without a credential it ENFORCES. This app is not an MCP server: handing it
# MCP_SHARED_SECRET would satisfy the guard while gating nothing, and would put the key to every MCP
# server into a manifest zip and a browser history. So it holds its OWN key, carried by the manifest
# (which only ever reaches people inside the tenant) and checked here.

def gated(key="s3kr3t"):
    async def call(calls):
        return [{"ref": "art://corpus/1.html"}]
    return TestClient(service.web(call=call, read=lambda ref: b"<html>drawn</html>", key=key))


def test_the_drawing_is_refused_without_the_apps_own_key():
    assert gated().get("/corpus").status_code == 401


@pytest.mark.parametrize("ask", [
    lambda c: c.get("/corpus?k=s3kr3t"),
    lambda c: c.get("/corpus", headers={"Authorization": "Bearer s3kr3t"}),
])
def test_the_drawing_is_served_to_a_caller_that_carries_the_key(ask):
    """Teams loads an iframe, which cannot carry a header — so the query parameter is the one that
    matters in production and the bearer is what a script or a probe would use."""
    got = ask(gated())
    assert got.status_code == 200 and b"drawn" in got.content


def test_a_wrong_key_is_refused_as_firmly_as_none():
    assert gated().get("/corpus?k=nearly").status_code == 401


def test_the_tab_hands_the_drawing_the_key_it_was_opened_with():
    """The shell page is public — it is a frame and says so. The key rides the URL Teams was given in
    the manifest, and the frame must pass it on or the picture inside it is a 401."""
    body = gated().get("/tab?k=s3kr3t").text
    assert "/corpus?k=s3kr3t" in body


def test_with_no_key_configured_the_drawing_is_open():
    """Local development binds to loopback, where `refuse_open` already permits no credential at all.
    A gate that could not be switched off would make the offline loop need a secret to draw a picture."""
    assert gated(key="").get("/corpus").status_code == 200
