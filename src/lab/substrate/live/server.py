"""Watch one run happen — a page that updates IN PLACE, and the stream that drives it.

Why this is not part of the review app: Streamlit is server-rendered. The browser receives element
deltas over Streamlit's own socket, and the only way to change anything is a script RERUN — there is
no hook to take an SSE event and patch the page. Every workaround therefore collapses into "rerun or
reload", and both lose scroll position, open expanders, and (until the open page was moved into the
URL) which page you were on at all. A three-second reload made the Runs board unusable, which is the
measured version of that argument.

Why it is not part of the front door: the browser holds no Entra token, and `/api` is authorised by
app roles with a delegated user token deliberately refused. A page served THERE could not open its
own stream. Serving both from one place is what makes them same-origin, and same-origin is what
makes this work at all.

So: a substrate service on the review app's trust model — its own gate, Redis directly, and no
credential beyond those two. It shows what the RUN LOG knows: status, the step running now, each
step's start, finish and error. What a run PRODUCED stays in the review app, behind the decision
surface where it belongs; this answers "what is happening", which is the question a reload was
being asked.
"""
from __future__ import annotations

import asyncio
import json

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from lab.platform import config, runlog

__all__ = ["build", "frame", "main", "page", "settled", "token", "POLL_S", "MAX_TICKS"]

#: How often the stream re-reads the run, and how long it will hold one connection. The ceiling
#: stops a forgotten tab pinning a connection for ever; an `EventSource` reconnects by itself, so a
#: watcher that still cares is uninterrupted by it.
POLL_S = 1.0
MAX_TICKS = 1800                                          # 30 minutes at the poll interval

_SETTLED = ("done", "failed")


def settled(h) -> bool:
    return str((h or {}).get("status") or "") in _SETTLED


def token(h) -> str:
    """What makes this run different from the last frame sent.

    `elapsed` is excluded deliberately: `runlog._parse` recomputes it on every read for a running
    run, so including it would make every single tick a change and the stream a busy loop.
    """
    h = h or {}
    steps = [(n.get("name"), n.get("status")) for n in (h.get("nodes") or ())]
    return json.dumps([h.get("status"), h.get("node"), h.get("subject"),
                       h.get("error"), steps], sort_keys=True)


def frame(h) -> dict:
    """One run as this page shows it: counts, ids and step names.

    Never model output and never an artifact ref. Anyone holding the gate can watch, and what a run
    CONTAINS is the review app's business — it has a decision surface and this does not.
    """
    if not h:
        return {}
    return {
        "run": h.get("run_id", ""),
        "process": h.get("process", ""),
        # What it is about, once the workload has framed it; what it was given until then.
        "subject": str(h.get("subject") or h.get("input") or ""),
        "status": h.get("status", ""),
        "node": h.get("node", ""),
        "elapsed": h.get("elapsed"),
        "error": str(h.get("error") or ""),
        "steps": _steps(h.get("nodes") or ()),
    }


#: A step's own transitions, collapsed. `fail` is terminal: a later `start` must not overwrite the
#: one row anybody is looking for.
_TERMINAL = ("fail",)


def _steps(nodes) -> list:
    """One row per STEP, in the order they started, showing its latest transition.

    The run log records `start` and then `done` as separate entries and the page rendered every
    one, so every step appeared twice — "• receive" and again "✓ receive" (seen 20 Sep 2026). A
    step is a thing, not a stream of its transitions.

    Whatever the workload stamped on the node travels with it: the record key the step writes, and
    a SHAPE of what it produced — counts and types, never model output. This page is reachable by
    anyone holding the gate, and a run's content belongs behind the review app's decision surface.
    """
    rows: dict = {}
    for n in nodes:
        name = n.get("name", "")
        attrs = n.get("attrs") or {}
        if rows.get(name, {}).get("status") in _TERMINAL:
            continue
        rows[name] = {
            "name": name,
            "status": n.get("status", ""),
            "at": n.get("ts", ""),
            "elapsed": attrs.get("elapsed"),
            "error": str(attrs.get("error") or ""),
            # What the workload chose to say about this step, if anything.
            "key": str(attrs.get("key") or ""),
            "produced": attrs.get("produced") or {},
        }
    return list(rows.values())


#: The page. Deliberately one file with no build step and no CDN: a live view that could not render
#: because a network fetch failed would be worse than none, and this service exists precisely for
#: the moments when somebody is watching something go wrong.
_PAGE = """<!doctype html><meta charset="utf-8"><title>run %(run)s</title>
<style>
 :root{color-scheme:light dark;--fg:#1a1a1a;--dim:#6b7280;--line:#e5e7eb;--ok:#15803d;
       --run:#b45309;--bad:#b91c1c;--bg:#fbfbfa}
 @media (prefers-color-scheme:dark){:root{--fg:#e7e5e4;--dim:#9ca3af;--line:#30302e;--bg:#1c1c1a}}
 body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 ui-sans-serif,system-ui,sans-serif}
 main{max-width:52rem;margin:0 auto;padding:2rem 1.25rem}
 h1{font-size:1.15rem;margin:0 0 .25rem;font-weight:600;text-wrap:balance}
 .meta{color:var(--dim);font-size:.82rem;margin-bottom:1.5rem}
 .pill{display:inline-block;padding:.1rem .5rem;border-radius:999px;font-size:.72rem;
       font-weight:600;letter-spacing:.02em;text-transform:uppercase}
 .running{background:#fef3c7;color:var(--run)}.done{background:#dcfce7;color:var(--ok)}
 .failed{background:#fee2e2;color:var(--bad)}
 ol{list-style:none;margin:0;padding:0}
 li{border-bottom:1px solid var(--line)}
 summary{display:flex;gap:.75rem;align-items:baseline;padding:.55rem 0;cursor:pointer;
         list-style:none}
 summary::-webkit-details-marker{display:none}
 summary::before{content:"\25B8";color:var(--dim);font-size:.7rem;width:.8rem;flex:none;
                 transition:transform .12s}
 details[open] summary::before{transform:rotate(90deg)}
 summary .mark{width:1rem;flex:none}
 summary .s{margin-left:auto;font-variant-numeric:tabular-nums;color:var(--dim);font-size:.82rem}
 .detail{padding:.25rem 0 .9rem 1.8rem;font-size:.85rem;color:var(--dim)}
 .detail dl{display:grid;grid-template-columns:auto 1fr;gap:.2rem .9rem;margin:0}
 .detail dt{color:var(--dim)}
 .detail dd{margin:0;color:var(--fg);font-variant-numeric:tabular-nums}
 .detail .none{font-style:italic}
 .err{color:var(--bad)}
 .idle{color:var(--dim);font-style:italic}
</style>
<main>
 <h1 id="subject">…</h1>
 <div class="meta"><span id="status" class="pill">…</span> <span id="elapsed"></span>
   · <code>%(run)s</code></div>
 <ol id="steps"></ol>
 <p id="note" class="idle">waiting for the first event…</p>
</main>
<script>
const RUN = %(run_json)s;
const $ = (id) => document.getElementById(id);
const secs = (v) => v == null ? "" : (v < 60 ? v.toFixed(1) + "s" : (v / 60).toFixed(1) + "m");

function detail(s) {
  const dl = document.createElement("dl");
  const add = (term, value, cls) => {
    const dt = document.createElement("dt"); dt.textContent = term;
    const dd = document.createElement("dd"); dd.textContent = value;
    if (cls) dd.className = cls;
    dl.append(dt, dd);
  };
  add("status", s.status || "—");
  if (s.at) add("at", s.at.replace("T", " ").slice(0, 19));
  if (s.elapsed != null) add("took", secs(s.elapsed));
  if (s.key) add("writes", s.key);
  const produced = Object.entries(s.produced || {});
  if (produced.length) {
    // COUNTS AND TYPES, never a value — what the workload stamped. The run's content lives in the
    // review app, which is the surface with a decision on it.
    for (const [field, shape] of produced) add(field, shape);
  } else if (s.status === "done") {
    add("produced", "nothing recorded", "none");
  }
  if (s.error) add("error", s.error, "err");
  return dl;
}

function render(d) {
  $("subject").textContent = d.subject || RUN;
  const st = $("status");
  st.textContent = d.status || "";
  st.className = "pill " + (d.status || "");
  $("elapsed").textContent = secs(d.elapsed);
  $("note").textContent = d.error || "";
  $("note").className = d.error ? "err" : "idle";
  // Rebuilt from the frame rather than patched step by step: the list is short, and a diff is a
  // second description of the same state that can disagree with the first.
  // Which rows the reader had OPEN, kept across re-renders: a frame arrives every time the run
  // moves, and a details element that closed itself on each one would be unusable.
  const open = new Set([...document.querySelectorAll("li details[open]")].map(d => d.dataset.step));
  $("steps").replaceChildren(...(d.steps || []).map(s => {
    const li = document.createElement("li");
    const mark = s.status === "done" ? "\u2713" : s.status === "fail" ? "\u2717" : "\u2022";
    li.innerHTML =
      '<details><summary><span class="mark"></span><span class="nm"></span>' +
      '<span class="s"></span></summary><div class="detail"></div></details>';
    const det = li.querySelector("details");
    det.dataset.step = s.name;
    if (open.has(s.name)) det.open = true;
    li.querySelector(".mark").textContent = mark;
    li.querySelector(".nm").textContent = s.name;
    li.querySelector(".s").textContent = secs(s.elapsed);
    li.querySelector(".detail").replaceChildren(detail(s));
    return li;
  }));
}

// The browser reconnects on its own when the server closes the stream, which is how a watch
// outlives the server's per-connection ceiling without anybody refreshing anything.
const es = new EventSource("/events/" + encodeURIComponent(RUN));
es.onmessage = (e) => render(JSON.parse(e.data));
es.onerror = () => { $("note").textContent = "reconnecting…"; };
</script>"""


def page(run_id: str) -> str:
    """The watch page for one run. `run_id` reaches the markup as JSON, never as raw text: it comes
    from the URL, and a value spliced into a <script> is how a path becomes script."""
    return _PAGE % {"run": run_id.replace("<", "&lt;"), "run_json": json.dumps(run_id)}


def _authorised(request: Request) -> bool:
    """The review app's gate, verbatim: a shared password when one is configured, open when not.

    Deliberately the SAME contract rather than a second one — two gates that can disagree is how a
    surface ends up open because somebody secured the other one. On Azure, Container Apps Entra
    auth goes in front of both and this returns True.
    """
    want = config.REVIEW_APP_PASSWORD
    if not want:
        return True
    return request.query_params.get("k") == want or request.cookies.get("lab_live") == want


def _gate(request: Request):
    if _authorised(request):
        return None
    return Response("not authorised", status_code=401)


def _watch(container):
    async def watch(request: Request) -> Response:
        if (denied := _gate(request)) is not None:
            return denied
        run_id = request.path_params["run_id"]
        body = page(run_id)
        response = HTMLResponse(body)
        # Carry the gate forward so the page's own EventSource is authorised without the secret
        # having to live in every link. httponly: the page never needs to read it.
        if config.REVIEW_APP_PASSWORD and request.query_params.get("k"):
            response.set_cookie("lab_live", config.REVIEW_APP_PASSWORD, httponly=True,
                                samesite="strict")
        return response
    return watch


def _events(container):
    async def events(request: Request) -> Response:
        if (denied := _gate(request)) is not None:
            return denied
        run_id = request.path_params["run_id"]
        redis = container.redis()

        async def stream():
            last = None
            for _ in range(MAX_TICKS):
                h = runlog.get(run_id, client=redis) or {}
                now = token(h)
                if now != last:
                    last = now
                    yield f"data: {json.dumps(frame(h))}\n\n"
                if settled(h):
                    return
                if await request.is_disconnected():
                    return
                await asyncio.sleep(POLL_S)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "Connection": "keep-alive",
            # Nothing may buffer an event stream: a proxy that waits for a complete response turns
            # "live" into "all at once at the end", which looks exactly like broken.
            "X-Accel-Buffering": "no"})
    return events


async def _healthz(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def build(container) -> Starlette:
    """The ASGI app. `container` supplies Redis — the only client this service has."""
    return Starlette(routes=[
        Route("/healthz", _healthz, methods=["GET"]),
        Route("/run/{run_id}", _watch(container), methods=["GET"]),
        # ONE stream route, absolute. There used to be a second, nested one to catch a RELATIVE
        # "events/<id>" — which does not resolve the way that comment assumed: from `/run/<id>`
        # the browser REPLACES the last segment, asking for `/run/events/<id>`, which matched
        # neither. Two routes for one thing is also how the page came to be tested against a URL
        # it never requests.
        Route("/events/{run_id}", _events(container), methods=["GET"]),
    ])


def main() -> None:
    import uvicorn

    from lab.substrate.container import build as build_container
    # The same line every other role prints, in the same shape `deploy/railway.py substrate
    # versions` greps for. Without it the report says "(no build line in its logs)" — which is what
    # it said about the review app until today, and is worth exactly nothing when you are trying to
    # find out which build is serving. A new service inherits the gap unless it inherits the line.
    print(f"live: serving on http://{config.BIND_HOST}:{config.LIVE_PORT}  {config.build_id()}",
          flush=True)
    uvicorn.run(build(build_container("live")), host=config.BIND_HOST, port=config.LIVE_PORT)


if __name__ == "__main__":
    main()
