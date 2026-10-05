"""SPIKE helper: a Graph call made with ONLY the meeting app's credential — the RSC principal.
No tenant-wide permission is granted to this app, so whatever succeeds here succeeds by RSC alone."""
import json
import os
import urllib.error
import urllib.request

import msal

_app = msal.ConfidentialClientApplication(
    os.environ["MEETING_APP_ID"], client_credential=os.environ["MEETING_APP_SECRET"],
    authority=f"https://login.microsoftonline.com/{os.environ['ENTRA_TENANT_ID']}")


def token() -> str:
    return _app.acquire_token_for_client(["https://graph.microsoft.com/.default"])["access_token"]


def graph(method: str, path: str, body=None, raw: bool = False, limit: int = 0):
    req = urllib.request.Request("https://graph.microsoft.com/v1.0" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + token(),
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            if raw:
                return r.status, r.headers.get("Content-Type"), r.read(limit or None)
            return r.status, json.load(r) if r.status != 204 else {}
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:600].decode(errors="replace")
