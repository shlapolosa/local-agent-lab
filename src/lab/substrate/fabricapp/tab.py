"""The pages Teams loads for the fabric's tab — pure strings, so they are the thing the tests assert on.

A TAB, not a link to a file. The corpus picture lived in SharePoint as a snapshot written on publish;
in a tab it gains three things it could not have there: external scripts are permitted (the vendored D3
stays, but the constraint is gone), it is drawn when it is OPENED rather than when it was last
published, and TeamsJS knows WHO IS LOOKING — so a steward and a researcher can be handed the same
renderer with different defaults.

The configuration page is not optional. Measured on the meeting app, 6 Oct 2026: with no page the add
dialog showed "Not Found" with Save disabled, and closing it cancelled the whole opt-in. A tab without
a config page cannot be added to a channel at all.
"""
from __future__ import annotations

from html import escape

__all__ = ["TEAMS_JS", "config_page", "shell_page", "privacy_page", "terms_page", "MODE_FOR"]

#: Microsoft's own CDN for TeamsJS — the host Teams documents for tab pages. Reachable here, unlike in
#: a SharePoint-served page, which is why the fabric's own D3 is vendored and this is not.
TEAMS_JS = "https://res.cdn.office.net/teams-js/2.24.0/js/MicrosoftTeams.min.js"

#: Which view a person lands on. A COURTESY, never a control: a researcher is shown the join because it
#: is what they came for, not because that is how they are prevented from curating. Authority lives in
#: the gateway's per-tool grants and `ApiRoles`, and a hidden control is security by absence.
MODE_FOR = {"steward": "vocabulary", "researcher": "about", "author": "about"}


def _frame(title: str, body: str, *, script: str = "") -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
 :root {{ color-scheme: light dark }}
 body {{ margin:0; font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
         padding:22px 24px; color:#1f2a37 }}
 h1 {{ font-size:19px; margin:0 0 6px }}
 p {{ margin:.5em 0; max-width:46em }}
 .sub {{ color:#5b6b7a; font-size:13px }}
 code {{ background:#eef1f4; padding:.1em .35em; border-radius:3px }}
 @media (prefers-color-scheme: dark) {{ body {{ color:#e8eaed }} .sub {{ color:#9aa0a6 }}
   code {{ background:#2b2b2b }} }}
</style></head>
<body>{body}
<script src="{TEAMS_JS}"></script>
<script>{script}</script>
</body></html>
"""


def config_page() -> str:
    """The page Teams shows when the tab is added to a channel. It must declare itself VALID or Teams
    leaves Save disabled and the add is cancelled — there is nothing to configure here, so it says so
    and saves immediately."""
    return _frame("Add the fabric", """
<h1>The corpus, drawn</h1>
<p>This tab shows every record the fabric holds and what each is about, redrawn from the graph each time
it is opened.</p>
<p class="sub">Nothing to configure. Select <b>Save</b>.</p>""", script="""
microsoftTeams.app.initialize().then(function () {
  microsoftTeams.pages.config.registerOnSaveHandler(function (e) {
    microsoftTeams.pages.config.setConfig({
      entityId: "fabric-corpus",
      // the key this page was opened with is the key the tab it creates must carry
      contentUrl: window.location.origin + "/tab" + window.location.search,
      suggestedDisplayName: "Fabric"
    });
    e.notifySuccess();
  });
  microsoftTeams.pages.config.setValidityState(true);
});""")


def shell_page(view_url: str, *, mode: str = "about") -> str:
    """The tab itself: a frame that loads the drawing, and says plainly how it was read.

    The picture is fetched with the SERVICE'S credential, not the viewer's — identity propagation
    gateway->MCP is blocked, so reading on somebody's behalf is not available. That is honest for a
    corpus picture, which carries counts, labels and links and no document content, and every member of
    the team may see the same one. SAYING so is the part that makes it honest rather than convenient."""
    return _frame("Fabric — the corpus", f"""
<h1>The corpus, by what it is about</h1>
<p class="sub">Every published record and the concepts it is about. Drawn when you opened this.</p>
<iframe src="{escape(view_url)}#{escape(mode)}" title="The corpus, drawn"
        style="width:100%;height:calc(100vh - 150px);border:1px solid #cfd8dd;border-radius:8px"></iframe>
<p class="sub">Read with the fabric's own credential, so everyone here sees the same picture. It carries
counts, labels and links — never the content of a document.</p>""", script="""
microsoftTeams.app.initialize().catch(function () {});""")


def privacy_page() -> str:
    return _frame("Privacy", """
<h1>Privacy</h1>
<p>This tab draws the fabric's CATALOGUE: titles, lifecycle state, the concepts a record is about, and
how each of those is known. It does not read, store or display the contents of any document — those stay
in the system of record, reached under that system's own permissions.</p>""")


def terms_page() -> str:
    return _frame("Terms", """
<h1>Terms of use</h1>
<p>An internal lab tool. It records what it is told and shows what it holds; it decides nothing. Every
change to the knowledge it describes is made by a named person through the approval gate.</p>""")
