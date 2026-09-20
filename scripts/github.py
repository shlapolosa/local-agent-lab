"""GitHub from the PAT in `.env`, over the REST API. The replacement for the `gh` CLI.

    set -a && source .env && set +a
    python scripts/github.py runs [n]              # recent CI runs, newest first
    python scripts/github.py run <id>              # one run: per-job conclusions
    python scripts/github.py failed <id>           # the log lines of the FAILED steps
    python scripts/github.py watch <id>            # block until it finishes, then report
    python scripts/github.py rerun <id>            # re-run just the FAILED jobs of a run
    python scripts/github.py secret <NAME> <path>  # set an Actions secret from a file
    python scripts/github.py whoami                # what this token can actually do

`gh` was a second credential and a second thing to keep signed in, and its token was scoped
differently from the one this repository already holds. Both `gh secret set` and `gh run rerun`
were refused with "Resource not accessible by personal access token" — and BOTH work through this
PAT (verified: 204 and 201). So two capabilities were reported as missing all day when what was
missing was the right credential. One credential, one path, and `whoami` says what it may do.

Stdlib only and `sys.path`-based for the same reason as `deploy/railway.py`: it must run wherever
the profile is sourced, with nothing installed.

A secret is SEALED before it leaves this machine (libsodium sealed box, the API's requirement), so
that one subcommand needs PyNaCl; everything else is stdlib.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
REPO = os.environ.get("GITHUB_REPO", "shlapolosa/local-agent-lab")
#: Terminal states. Anything else means the run is still going.
DONE = ("completed", "cancelled", "failure", "success", "skipped", "timed_out")


def _token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise SystemExit("GITHUB_TOKEN is not set — `set -a && source .env && set +a` first")
    return token


def call(path: str, *, method: str = "GET", body: dict | None = None, raw: bool = False,
         attempts: int = 3):
    """One API call. `raw` returns bytes (logs are a zip), otherwise parsed JSON.

    A TRANSPORT error is retried; an HTTP error is not. `watch` polls for the length of a deploy,
    and a single DNS hiccup killed one mid-run with a stack trace — the network dropping for a
    second is not news about the workflow. An HTTPError, by contrast, is the server's ANSWER: a 404
    or a 403 means the same thing on the third try as the first, and retrying it only delays the
    report. Same split `deploy/railway.py` already makes.
    """
    url = path if path.startswith("http") else f"{API}/repos/{REPO}/{path}"
    request = urllib.request.Request(
        url, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {_token()}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = response.read()
                if raw:
                    return payload, response.status
                return (json.loads(payload) if payload else {}), response.status
        except urllib.error.HTTPError:
            raise                                          # the server's answer, not a hiccup
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == attempts:
                raise
            print(f"  network hiccup ({type(e).__name__}) — retrying {attempt}/{attempts - 1}",
                  file=sys.stderr)
            time.sleep(2 * attempt)
    raise AssertionError("unreachable")


def runs(limit: int = 10) -> int:
    data, _ = call(f"actions/runs?per_page={int(limit)}")
    for run in data.get("workflow_runs", []):
        state = run.get("conclusion") or run.get("status")
        print(f"{run['id']}  {str(state):12} {run['created_at']}  "
              f"{run.get('display_title', '')[:64]}")
    return 0


def run(run_id: str) -> int:
    data, _ = call(f"actions/runs/{run_id}")
    print(f"{data['id']}  {data.get('conclusion') or data.get('status')}  "
          f"{data.get('display_title', '')}")
    jobs, _ = call(f"actions/runs/{run_id}/jobs")
    for job in jobs.get("jobs", []):
        print(f"  {job['name']:12} {job['status']:12} {job.get('conclusion') or '-'}")
    return 0 if data.get("conclusion") in (None, "success") else 1


def failed(run_id: str) -> int:
    """The log of every step that failed. `gh run view --log-failed`, without gh.

    The API serves logs as a ZIP of per-job files; the failed STEPS are not separable, so this
    prints the tail of each failed job's log — which is where a failure says what it was.
    """
    import io
    import zipfile

    jobs, _ = call(f"actions/runs/{run_id}/jobs")
    bad = [j for j in jobs.get("jobs", []) if j.get("conclusion") not in (None, "success", "skipped")]
    if not bad:
        print("no failed jobs")
        return 0
    body, _ = call(f"actions/runs/{run_id}/logs", raw=True)
    archive = zipfile.ZipFile(io.BytesIO(body))
    for job in bad:
        print(f"\n===== {job['name']} ({job.get('conclusion')}) =====")
        for name in archive.namelist():
            if name.startswith(job["name"] + "/") or name.startswith(job["name"] + ".txt"):
                text = archive.read(name).decode("utf-8", "replace").splitlines()
                for line in text[-40:]:
                    print("  " + line[:200])
    return 1


def watch(run_id: str, every: int = 20) -> int:
    """Block until the run finishes. Prints each state change, not each poll."""
    last = None
    while True:
        data, _ = call(f"actions/runs/{run_id}")
        state = data.get("conclusion") or data.get("status")
        if state != last:
            print(f"  {state}")
            last = state
        if data.get("status") == "completed":
            return run(run_id)
        time.sleep(every)


def rerun(run_id: str) -> int:
    """Re-run the FAILED jobs of a run — not the whole thing.

    A rerun takes a FRESH snapshot of the repository's secrets, which is what makes it the recovery
    path for a deploy that failed on stale configuration: fix `.env`, `secret LAB_ENV`, `rerun`.
    """
    _, status = call(f"actions/runs/{run_id}/rerun-failed-jobs", method="POST")
    print(f"rerun requested for {run_id} -> HTTP {status}; `watch {run_id}` to follow it")
    return 0


def secret(name: str, path: str) -> int:
    """Set an Actions secret from a FILE, sealed before it leaves this machine.

    A file rather than an argument: the value never reaches a shell history or a process list, and
    `LAB_ENV` is a whole `.env` that could not be passed inline anyway.
    """
    import base64

    from nacl import encoding, public                      # the one non-stdlib dependency

    body = open(path, "rb").read()
    key, _ = call("actions/secrets/public-key")
    sealed = public.SealedBox(public.PublicKey(key["key"].encode(), encoding.Base64Encoder()))
    _, status = call(f"actions/secrets/{urllib.parse.quote(name)}", method="PUT", body={
        "encrypted_value": base64.b64encode(sealed.encrypt(body)).decode(),
        "key_id": key["key_id"]})
    meta, _ = call(f"actions/secrets/{urllib.parse.quote(name)}")
    print(f"{name} <- {path} ({len(body):,} bytes) HTTP {status}; updated_at {meta.get('updated_at')}")
    return 0


def whoami() -> int:
    """What this token may actually do — asked, not assumed.

    Worth asking, because the answer was got wrong twice in one day. `gh secret set` and
    `gh run rerun` were both refused with "Resource not accessible by personal access token", and
    both were reported as capabilities the project did not have. They were capabilities GH's OWN
    token did not have: through this PAT the same two operations return 204 and 201. A refusal
    names the tool that was refused, never the credential that would have worked.
    """
    data, _ = call(f"{API}/repos/{REPO}")
    print(f"repo {data.get('full_name')}  private={data.get('private')}")
    print(f"permissions {data.get('permissions')}")
    for label, probe in (("read runs", lambda: call("actions/runs?per_page=1")),
                         ("read secrets", lambda: call("actions/secrets/public-key")),
                         # A run id that cannot exist: a 404 proves the ROUTE was permitted, which
                         # is what is being asked. A 403 is the refusal that matters.
                         ("rerun a run", lambda: call("actions/runs/0/rerun-failed-jobs",
                                                      method="POST"))):
        try:
            probe()
            print(f"  {label:14} yes")
        except urllib.error.HTTPError as e:
            # 404 on a run id that does not exist still proves the ROUTE was allowed; 403 is the
            # refusal that matters.
            print(f"  {label:14} {'yes (route allowed)' if e.code == 404 else f'NO ({e.code})'}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        raise SystemExit(__doc__)
    command, rest = argv[0], argv[1:]
    table = {"runs": lambda: runs(int(rest[0]) if rest else 10), "run": lambda: run(*rest),
             "failed": lambda: failed(*rest), "watch": lambda: watch(rest[0]),
             "rerun": lambda: rerun(*rest), "secret": lambda: secret(*rest), "whoami": whoami}
    if command not in table:
        raise SystemExit(__doc__)
    try:
        return table[command]()
    except urllib.error.HTTPError as e:
        print(f"{command}: HTTP {e.code} {e.read()[:300].decode('utf-8', 'replace')}",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
