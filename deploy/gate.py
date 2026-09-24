"""The QUIET GATE every deploy target runs before it restarts the gateway (see `quiet_board`)."""
import json
import os
import sys
import time
import urllib.error
import urllib.request


# ---------------------------------------------------------------------------- the quiet gate
#
# A rollout restarts the gateway, and every LLM, tool and embedding call in flight gets a 502 while
# it comes back — a run an hour of tokens in ends with "upstream error" (measured 11 Sep 2026: two
# derives, an adjudication and a publish's embedding batches all died under one push). So a deploy
# first asks the front door what is still running and WAITS for it to finish, up to
# LAB_DEPLOY_WAIT_S (default 30 min, a screening run), then refuses. LAB_DEPLOY_FORCE=1 skips the
# gate for the case where the gateway itself is what is broken. A front door that cannot be asked
# (no PUBLIC_GATEWAY_URL in the profile, or unreachable) is reported and the deploy proceeds: a gate
# that blocks the repair of the thing it cannot reach would be worse than none.
QUIET_POLL_S = 30
#: How long an UNREACHABLE front door is waited for before the gate gives up asking. Two rolls
#: close together produce exactly this: the gateway is still restarting from the previous deploy,
#: the gate cannot ask, and "cannot ask → proceed" let a deploy through over a board it never saw
#: (measured by the meeting session, 12 Sep 2026). A restart is a few minutes; a gateway that is
#: down for longer than this is the thing being repaired, and the deploy proceeds with a line.
QUIET_UNREACHABLE_WAIT_S = 300


def open_runs(profile: dict):
    """The runs the front door says are still pending or running, or None when it cannot be asked."""
    url, key = profile.get("PUBLIC_GATEWAY_URL", ""), profile.get("LITELLM_MASTER_KEY", "")
    if not url or not key:
        return None
    try:
        req = urllib.request.Request(f"{url.rstrip('/')}/api/runs/open",
                                     headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return list(json.load(r).get("runs") or [])
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        print(f"  quiet gate: front door unreachable ({type(e).__name__}: {str(e)[:80]})",
              file=sys.stderr, flush=True)
        return None


def quiet_board(profile: dict, wait_s: int | None = None) -> bool:
    """True when nothing is running (or nothing can be known); False when runs are still in flight
    after waiting. Prints what it waited for, because a deploy that pauses silently looks hung."""
    if os.environ.get("LAB_DEPLOY_FORCE") == "1":
        print("  quiet gate: LAB_DEPLOY_FORCE=1 — deploying over whatever is running")
        return True
    if not profile.get("PUBLIC_GATEWAY_URL"):
        print("  quiet gate: no PUBLIC_GATEWAY_URL in the profile — cannot ask, proceeding")
        return True
    budget = int(os.environ.get("LAB_DEPLOY_WAIT_S", "1800")) if wait_s is None else wait_s
    waited = unreachable = 0
    while True:
        runs = open_runs(profile)
        if runs is None:                                   # cannot ask (yet): a restart in progress?
            if unreachable >= QUIET_UNREACHABLE_WAIT_S:
                print(f"  quiet gate: front door unreachable for {unreachable}s — proceeding "
                      f"unasked (the gateway itself may be what this deploy repairs)", flush=True)
                return True
            print(f"  quiet gate: front door unreachable — waiting for it … {unreachable}/"
                  f"{QUIET_UNREACHABLE_WAIT_S}s", flush=True)
            time.sleep(QUIET_POLL_S)
            unreachable += QUIET_POLL_S
            continue
        if not runs:
            if waited or unreachable:
                print(f"  quiet gate: board quiet after {waited + unreachable}s")
            return True
        names = ", ".join(f"{r.get('process')}/{r.get('request_id')}" for r in runs[:4])
        if waited >= budget:
            print(f"  quiet gate: {len(runs)} run(s) still in flight after {waited}s ({names}) — "
                  f"refusing to restart the gateway under them; LAB_DEPLOY_FORCE=1 overrides",
                  file=sys.stderr, flush=True)
            return False
        print(f"  quiet gate: waiting for {len(runs)} run(s) ({names}) … {waited}/{budget}s", flush=True)
        time.sleep(QUIET_POLL_S)
        waited += QUIET_POLL_S


def _require_quiet(profile: dict) -> None:
    if not quiet_board(profile):
        raise SystemExit(3)
