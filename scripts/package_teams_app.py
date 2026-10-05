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
TEMPLATE = ROOT / "config/clients/teams-app/manifest.tmpl.json"


def render(host: str, bot_id: str, name: str, version: str) -> dict:
    values = {"HOST": host, "BOT_ID": bot_id, "NAME": name, "VERSION": version,
              "TEAMS_APP_ID": str(uuid.uuid5(uuid.NAMESPACE_URL, f"teams-app/{bot_id}"))}
    text = TEMPLATE.read_text()
    for k, v in values.items():
        text = text.replace("${" + k + "}", v)
    return json.loads(text)


def icon(size: int, outline: bool) -> bytes:
    """A plain mark: a speech bubble. Outline icons must be white on transparent (Teams rule)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0) if outline else (47, 93, 138, 255))
    d = ImageDraw.Draw(img)
    m = size // 5
    d.rounded_rectangle([m, m, size - m, size - 2 * m], radius=size // 8,
                        outline=(255, 255, 255, 255), width=max(1, size // 24))
    d.polygon([(m * 2, size - 2 * m), (m * 2, size - m), (m * 3, size - 2 * m)], fill=(255, 255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("--name", default="Meeting Notes (dev)")
    ap.add_argument("--version", default="1.0.0")
    a = ap.parse_args()
    manifest = render(a.host, os.environ["MEETING_APP_ID"], a.name, a.version)
    # Validate against the schema the manifest itself names. Teams' upload dialog reports a schema
    # violation as "UnknownError" (measured: a short description of 107 chars, limit 80), so this is
    # the only place the real reason is visible.
    with urllib.request.urlopen(manifest["$schema"], timeout=30) as r:
        errors = list(jsonschema.Draft7Validator(json.load(r)).iter_errors(manifest))
    if errors:
        raise SystemExit("manifest invalid:\n" + "\n".join(f"  {list(e.path)}: {e.message}" for e in errors))
    out = ROOT / "var/out/teams-app" / f"{a.host}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("color.png", icon(192, outline=False))
        z.writestr("outline.png", icon(32, outline=True))
    print(f"{out}  (teams app id {manifest['id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
