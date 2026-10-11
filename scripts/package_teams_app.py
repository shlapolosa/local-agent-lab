"""Render and zip the Teams meeting app (config/clients/teams-app/manifest.tmpl.json) for ONE tier.

The manifest names the HOST the bot, tab and SSO resource live on, so a package belongs to exactly one
deployment — dev and prod are two apps with two bot ids, and a dev package cannot act on a prod meeting.
The Teams app id is a uuid5 of the bot id: stable across re-packaging (Teams treats a new id as a new
app, orphaning every meeting it was added to), distinct per tier.

Only PUBLIC identifiers are substituted — the bot id and a hostname — so the zip is not sensitive.

Usage: .venv/bin/python scripts/package_teams_app.py <host> [--name "Meeting Notes (dev)"] [--version 1.0.0]
       (bot id from MEETING_APP_ID; writes var/out/teams-app/<host>.zip)
"""
import argparse
import io
import json
import os
import urllib.request
import uuid
import zipfile

import jsonschema
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]

#: The apps this packages, by the `--app` name: where the template lives, which setting holds the bot id,
#: and the mark drawn on the icon. TWO apps, never one: each manifest names the HOST its surfaces live on,
#: so a package belongs to exactly one app on exactly one tier. The FABRIC app's bot is the Copilot Studio
#: agent's own registration — it writes no bot code, so its "bot id" is read from the agent rather than
#: minted (`bot.applicationmanifestinformation.teams.botChannelRegistrationAppId`, 11 Oct 2026).
APPS = {
    # `seed` is the uuid5 input, and the meeting app's MUST stay exactly what it has always been:
    # Teams treats a new id as a NEW APP, orphaning every meeting the old one was added to. Adding the
    # app name to the seed looked tidy and silently re-minted it (caught 11 Oct 2026 by packaging both).
    # A new app gets a scoped seed; an existing one keeps the string that already produced its id.
    "meeting": {"template": "config/clients/teams-app/manifest.tmpl.json", "bot_env": "MEETING_APP_ID",
                "name": "Meeting Notes (dev)", "mark": "bubble", "seed": "teams-app/{bot}"},
    "fabric":  {"template": "config/clients/fabric-app/manifest.tmpl.json", "bot_env": "FABRIC_AGENT_BOT_ID",
                "name": "Fabric", "mark": "graph", "seed": "teams-app/fabric/{bot}"},
}


def render(host: str, bot_id: str, name: str, version: str, *, app: str = "meeting",
           key: str = "") -> dict:
    # `key` is the app's OWN credential, carried on the URLs Teams loads. A package built without
    # one renders a tab whose drawing is 401 wherever the service is gated, so it is passed in
    # rather than defaulted: the packager must not quietly ship a manifest that cannot draw.
    values = {"HOST": host, "BOT_ID": bot_id, "AGENT_BOT_ID": bot_id, "NAME": name, "VERSION": version,
              "APP_KEY": key,
              "TEAMS_APP_ID": str(uuid.uuid5(uuid.NAMESPACE_URL,
                                             APPS[app]["seed"].format(bot=bot_id)))}
    text = (ROOT / APPS[app]["template"]).read_text()
    for k, v in values.items():
        text = text.replace("${" + k + "}", v)
    return _strip_notes(json.loads(text))


def _strip_notes(o):
    """Drop every `//`-prefixed key. The TEMPLATE carries the reasoning — why this app has no bot code,
    why the configuration page is mandatory — beside the thing it explains, which is where a reader of
    the manifest will be. The Teams schema is CLOSED, so the package carries data only: validating with
    the notes in gives `Additional properties are not allowed ('//bots', ...)`, and the upload dialog
    reports any schema violation as "UnknownError" (measured), so this would be invisible at the worst
    moment."""
    if isinstance(o, dict):
        return {k: _strip_notes(v) for k, v in o.items() if not str(k).startswith("//")}
    return [_strip_notes(v) for v in o] if isinstance(o, list) else o


def icon(size: int, outline: bool, mark: str = "bubble") -> bytes:
    """A plain mark. Outline icons must be white on transparent (Teams rule).

    The FABRIC's mark is a small graph — three nodes and the edges between them — because that is what
    the app is for: a conversation can tell you one fact, and only a picture can show you the shape."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0) if outline else (47, 93, 138, 255))
    d = ImageDraw.Draw(img)
    m = size // 5
    if mark == "graph":
        w = max(1, size // 26)
        pts = [(size * 0.28, size * 0.30), (size * 0.72, size * 0.38), (size * 0.44, size * 0.72)]
        for a, b in ((0, 1), (1, 2), (2, 0)):
            d.line([pts[a], pts[b]], fill=(255, 255, 255, 255), width=w)
        for i, (x, y) in enumerate(pts):
            r = size * (0.085 if i == 0 else 0.06)
            d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 255))
        buf = io.BytesIO(); img.save(buf, "PNG"); return buf.getvalue()
    d.rounded_rectangle([m, m, size - m, size - 2 * m], radius=size // 8,
                        outline=(255, 255, 255, 255), width=max(1, size // 24))
    d.polygon([(m * 2, size - 2 * m), (m * 2, size - m), (m * 3, size - 2 * m)], fill=(255, 255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("--app", choices=sorted(APPS), default="meeting")
    ap.add_argument("--name", default=None)
    ap.add_argument("--version", default="1.0.0")
    a = ap.parse_args()
    spec = APPS[a.app]
    manifest = render(a.host, os.environ[spec["bot_env"]], a.name or spec["name"], a.version, app=a.app,
                      key=os.environ.get("FABRIC_APP_KEY", ""))
    # Validate against the schema the manifest itself names. Teams' upload dialog reports a schema
    # violation as "UnknownError" (measured: a short description of 107 chars, limit 80), so this is
    # the only place the real reason is visible.
    with urllib.request.urlopen(manifest["$schema"], timeout=30) as r:
        errors = list(jsonschema.Draft7Validator(json.load(r)).iter_errors(manifest))
    if errors:
        raise SystemExit("manifest invalid:\n" + "\n".join(f"  {list(e.path)}: {e.message}" for e in errors))
    out = ROOT / "var/out/teams-app" / f"{a.app}-{a.host}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("color.png", icon(192, outline=False, mark=spec["mark"]))
        z.writestr("outline.png", icon(32, outline=True, mark=spec["mark"]))
    print(f"{out}  (teams app id {manifest['id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
