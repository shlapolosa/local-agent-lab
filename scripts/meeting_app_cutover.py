"""Cut the meeting pipeline over from the Power Automate folder watcher to the opt-in meeting app — or back.

The watcher (`teams-recordings`) submits EVERY recording saved to the organiser's OneDrive to the DEV
gateway and asks for speakers in the Workflows chat; its notify flow (`meeting-minutes-notify`) posts the
folder-delivered minutes. With the app live, only meetings the app was added to are processed, the
question is asked in the meeting chat and the files are served in its tab — so both flows stop.

Deliberately NOT touched:
- `meeting-minutes-notify (Prod)`: production's, and production has no meeting app yet (Azure session).
- Graph permissions and the `Lab-Collab-Read` access policy: the reader still FETCHES the bytes of an
  opted-in meeting's recording (Microsoft cannot download by resource-specific consent — option A).

Stopping a flow cancels any run waiting on a card answer: the script lists Running runs first and
refuses to stop while one is open, unless --force.

Usage:  scripts/meeting_app_cutover.py               # dry run: what would change
        scripts/meeting_app_cutover.py --apply       # stop both dev flows
        scripts/meeting_app_cutover.py --rollback    # start them again
"""
import argparse
import json
import subprocess
import sys
import urllib.request

ENVIRONMENT = "Default-b911f4d4-de30-405f-96e9-bb1c773fe2ff"
FLOWS = {"teams-recordings": "38a1f0ae-536e-62c3-37d9-8bc33bd68047",
         "meeting-minutes-notify": "b761c030-ca15-ba17-f8f0-016c4ef79b1b"}
BASE = f"https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple/environments/{ENVIRONMENT}/flows"
API = "api-version=2016-11-01"


def _token() -> str:
    return subprocess.run(["az", "account", "get-access-token", "--resource", "https://service.flow.microsoft.com/",
                           "--query", "accessToken", "-o", "tsv"], capture_output=True, text=True,
                          check=True).stdout.strip()


def _call(method: str, url: str, token: str):
    req = urllib.request.Request(url, method=method, data=b"" if method == "POST" else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read()
        return json.loads(body) if body else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--force", action="store_true", help="stop even with a run waiting on a card answer")
    a = ap.parse_args()
    token = _token()
    verb = "start" if a.rollback else "stop"
    for name, fid in FLOWS.items():
        flow = _call("GET", f"{BASE}/{fid}?{API}", token)["properties"]
        running = [r for r in _call("GET", f"{BASE}/{fid}/runs?{API}&$top=50", token)["value"]
                   if r["properties"].get("status") == "Running"]
        print(f"{name}: {flow.get('state')}, {len(running)} run(s) waiting")
        if not (a.apply or a.rollback):
            continue
        if verb == "stop" and running and not a.force:
            print(f"  NOT stopped: {len(running)} run(s) still waiting on an answer (answer them, or --force)")
            continue
        try:
            _call("POST", f"{BASE}/{fid}/{verb}?{API}", token)
        except TimeoutError:
            # measured 6 Oct 2026: the stop TOOK EFFECT while the reply timed out — read the state instead
            print("  (no reply in time — reading the flow's state)")
        print(f"  {verb}ped" if verb == "stop" else "  started",
              "->", _call("GET", f"{BASE}/{fid}?{API}", token)["properties"].get("state"))
    if not (a.apply or a.rollback):
        print("dry run — pass --apply to stop, --rollback to start again")
    return 0


if __name__ == "__main__":
    sys.exit(main())
