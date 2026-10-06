"""The pages Teams loads for the app's meeting tab — static, so pure strings.

Adding the app to a meeting with "+" goes through the tab's CONFIGURATION page, and Teams finishes the
add — and so installs the bot — only once that page declares itself valid and saves. Measured 6 Oct
2026: with no page the dialog showed "Not Found" with Save disabled, and closing it cancelled the whole
opt-in. The tab itself is a short status page for now; the run status and downloads are a later piece.
"""
from __future__ import annotations

__all__ = ["TEAMS_JS", "config_page", "status_page", "privacy_page", "terms_page"]

#: Microsoft's own CDN for the TeamsJS library — the host Teams itself documents for tab pages.
TEAMS_JS = "https://res.cdn.office.net/teams-js/2.34.0/js/MicrosoftTeams.min.js"

_STYLE = ("<style>body{font-family:'Segoe UI',system-ui,sans-serif;margin:24px;line-height:1.5;"
          "color:#242424;background:#fff}@media (prefers-color-scheme:dark){body{color:#fff;"
          "background:#1f1f1f}}h1{font-size:18px}p{max-width:42em}</style>")


def _page(title: str, body: str, script: str = "") -> str:
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{title}</title>"
            f"{_STYLE}{script}</head><body>{body}</body></html>")


def config_page() -> str:
    """Valid at once — there is nothing to configure — and on save, the tab is the status page.

    Every step REPORTS itself, on the page and to `/tab/log`: Teams turns any failure here into a
    generic "Unable to save tab configuration" and discards the reason, and the first time that
    happened nothing on either side said why (6 Oct 2026). An instrument that cannot fail loudly is not
    an instrument."""
    script = (f'<script src="{TEAMS_JS}"></script><script>'
              "function say(stage,detail){var d=String(detail||'');"
              "var el=document.getElementById('status');if(el){el.textContent=stage+(d?': '+d:'');}"
              "try{navigator.sendBeacon('/tab/log',JSON.stringify({stage:stage,detail:d.slice(0,300)}));}catch(e){}}"
              "document.addEventListener('DOMContentLoaded',function(){"
              "if(!window.microsoftTeams){say('teams-js not loaded');}else{"
              "say('initialising');"
              "microsoftTeams.app.initialize().then(function(){"
              "say('ready');"
              "microsoftTeams.pages.config.registerOnSaveHandler(function(e){"
              "say('saving');"
              "microsoftTeams.pages.config.setConfig({entityId:'meeting-notes',"
              "contentUrl:location.origin+'/tab',websiteUrl:location.origin+'/tab',"
              "suggestedDisplayName:'Meeting Notes'})"
              ".then(function(){say('saved');e.notifySuccess();},"
              "function(err){say('setConfig failed',(err&&(err.message||err.errorCode))||JSON.stringify(err));"
              "e.notifyFailure(String((err&&err.message)||err));});});"
              "microsoftTeams.pages.config.setValidityState(true);"
              "},function(err){say('initialize failed',(err&&err.message)||err);});}});</script>")
    return _page("Meeting Notes", "<h1>Meeting Notes</h1><p>Select <b>Save</b> to turn Meeting Notes on for "
                                  "this meeting. Nothing else to set.</p><p id=\"status\" style=\"opacity:.6\">"
                                  "loading…</p>", script)


def status_page() -> str:
    """This meeting's transcript, minutes and comparison, per lane — for the people in it.

    The page asks Teams who is viewing (a sign-in token for THIS app) and which chat it sits in, and the
    service checks both on every request. A download is fetched with that token and saved from memory,
    so the token never appears in a URL."""
    script = (f'<script src="{TEAMS_JS}"></script><script>'
              "function el(id){return document.getElementById(id);}"
              "function show(t){el('files').textContent=t;}"
              "document.addEventListener('DOMContentLoaded',function(){"
              "microsoftTeams.app.initialize().then(function(){return microsoftTeams.app.getContext();})"
              ".then(function(ctx){var chat=(ctx.chat&&ctx.chat.id)||'';"
              "return microsoftTeams.authentication.getAuthToken().then(function(tok){"
              "return fetch('/tab/api/files?chat='+encodeURIComponent(chat),{headers:{Authorization:'Bearer '+tok}})"
              ".then(function(r){if(!r.ok){throw new Error(r.status===403?'Only people in this meeting can see its notes.':'Not available ('+r.status+').');}return r.json();})"
              ".then(function(j){var box=el('files');box.textContent='';"
              "if(!j.files.length){show('Nothing yet — the files appear here once the organiser has named the speakers.');return;}"
              "j.files.forEach(function(f){var b=document.createElement('button');b.textContent=f.name;"
              "b.onclick=function(){fetch('/tab/api/file?chat='+encodeURIComponent(chat)+'&name='+encodeURIComponent(f.name),"
              "{headers:{Authorization:'Bearer '+tok}}).then(function(r){return r.blob();}).then(function(blob){"
              "var a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=f.name;a.click();});};"
              "var row=document.createElement('div');row.appendChild(b);box.appendChild(row);});});});})"
              ".catch(function(e){show(String(e.message||e));});});</script>")
    return _page("Meeting Notes", "<h1>Meeting Notes</h1>"
                 "<p>After the meeting the organiser names the speakers in the chat; the transcript, the minutes "
                 "and the comparison then appear here, one set per transcription lane.</p>"
                 "<div id=\"files\">Loading…</div>"
                 "<style>#files button{margin:4px 0;padding:6px 10px;cursor:pointer}</style>", script)


def privacy_page() -> str:
    return _page("Meeting Notes — privacy", "<h1>Privacy</h1><p>Only meetings this app was added to are read. "
                 "A recording is transcribed after the meeting; the organiser names the speakers. A voice is "
                 "kept for recognising a speaker next time only with that speaker's consent, ticked by the "
                 "organiser.</p>")


def terms_page() -> str:
    return _page("Meeting Notes — terms", "<h1>Terms</h1><p>An internal tool of this organisation, provided "
                 "as-is for its own meetings.</p>")
