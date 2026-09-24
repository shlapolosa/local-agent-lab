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
import urllib.parse

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from lab.platform import config, runlog

__all__ = ["build", "chain", "frame", "main", "page", "settled", "token", "MAX_CHAIN", "POLL_S",
           "MAX_TICKS"]

#: How far a handover chain is followed. A ceiling rather than a trust: two runs naming each other
#: would otherwise spin, and a watcher page that never returns is worse than one that stops early.
MAX_CHAIN = 8

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
    """One run as this page shows it: what each step did, and links to what it wrote.

    It used to carry neither model output nor an artifact ref, on the argument that a run's
    CONTENTS are the review app's business. That argument has been retired twice by contact with
    the page — first for values (a type name where a value belongs protected nothing), now for
    artifacts. The boundary that actually matters is unchanged and is stronger than the old rule:
    this service never holds a store credential and never serves bytes. It emits a LINK, the review
    app reads the store, and the review app authenticates the person before it does.
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
        "steps": _with_links(_steps(h.get("nodes") or ()), config.REVIEW_APP_URL or ""),
        # Where the work went next, if it went anywhere. Data, so the page follows it without
        # knowing what any process is.
        **({"continued_as": str(h["continued_as"])} if h.get("continued_as") else {}),
        **({"continued_process": str(h["continued_process"])} if h.get("continued_process") else {}),
        # What this run is WAITING ON. A paused run is the commonest place a person is stuck, and
        # the id was already on the record — it only had to be offered as somewhere to go.
        **({"approval": _approval_link(str(h["approval_id"]))} if h.get("approval_id") else {}),
    }


def _approval_link(approval_id: str) -> dict:
    """The approval, and where a person decides it. The review app holds the decision surface and
    authenticates whoever opens it; this page only points."""
    base = config.REVIEW_APP_URL or ""
    return {"id": approval_id,
            "url": (f"{base.rstrip('/')}/?"
                    + urllib.parse.urlencode({"mode": "Review", "approval": approval_id})
                    if base else "")}


def resolve(run_id: str, *, client=None) -> str:
    """A trace id, given either a trace or a workflow REQUEST id.

    A just-released run has a request id and no trace yet — which is exactly when somebody follows
    the link out of an approval they have just given. Resolving here makes that link work now
    rather than once the consumer happens to start; an id that resolves to nothing is returned
    unchanged, so the page says "no such run" instead of this raising.
    """
    if runlog.get(run_id, client=client):
        return run_id
    from lab.platform import workflows
    trace = str((workflows.status(run_id, client=client) or {}).get("trace_id") or "")
    return trace or run_id


def _with_links(steps: list, review_app: str) -> list:
    """Give every artifact the URL a person opens it at.

    Built HERE rather than in the page, so the browser holds no URL logic at all: it renders
    `a.url` if there is one and nothing if there is not. No review app configured means no `url`,
    which means no link — never a link that goes nowhere.
    """
    for step in steps:
        for art in step.get("artifacts") or ():
            art["url"] = download_url(review_app, art.get("ref", ""))
    return steps


def chain(run_id: str, *, client=None) -> list:
    """Every run in this handover chain, oldest first — what ONE page shows.

    A run that ends by releasing another is the normal shape here: screening raises an approval,
    the approval releases design. Watched one run at a time, an approval a person has just given
    looks like it did nothing, because the work moved to a trace they were never given (measured
    23 Sep 2026 — the question was "why is it not progressing?", and it was).

    The links are DATA (`continued_as` / `continued_from`, written where the handover happens), so
    this follows them and renders `process` as it finds it. Nothing here knows what a screening or
    a design IS, which is what keeps a new process from being a change to this file.

    A continuation that has not STARTED yet still appears, as `queued`: the gap between an approval
    releasing a run and a consumer picking it up is exactly when somebody is staring at the page.
    """
    seen, back = [], run_id
    for _ in range(MAX_CHAIN):                  # walk back to the head of the chain first
        h = runlog.get(back, client=client) or {}
        nxt = str(h.get("continued_from") or "")
        if not nxt or nxt in seen:
            break
        seen.append(back)
        back = nxt

    out, current = [], back
    while current and len(out) < MAX_CHAIN:
        h = runlog.get(current, client=client) or {}
        if h:
            out.append(frame(h))
        else:
            # Released but not yet picked up: the run log has nothing, so the link itself is all
            # there is to say — and saying it is the point.
            out.append({"run": current, "process": _released_process(out), "status": "queued",
                        "subject": "", "elapsed": None, "error": "", "steps": []})
            break
        nxt = str(h.get("continued_as") or "")
        if not nxt or any(c["run"] == nxt for c in out):
            break
        current = nxt
    return out


def _released_process(so_far: list) -> str:
    """What the run that released this one said it was releasing."""
    return str(so_far[-1].get("continued_process") or "") if so_far else ""


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
            # What this step DOES, as the WORKLOAD declared it — never composed here. A node id is
            # an address, and a label invented in this service would be it naming somebody else's
            # step, so adding or renaming a step changes no code on this page. Sticky across the
            # collapse: `span_node` stamps the title on the START entry and the `done` entry it
            # writes carries only timings, so taking the latest transition wholesale lost the label
            # exactly when a step finished.
            "title": str(attrs.get("title") or rows.get(name, {}).get("title") or ""),
            # DERIVED: no model formed this answer. Sticky for the same reason the title is — it
            # is stamped once, on the transition that knew it.
            "derived": bool(attrs.get("derived") or rows.get(name, {}).get("derived")),
            "status": n.get("status", ""),
            "at": n.get("ts", ""),
            "elapsed": attrs.get("elapsed"),
            "error": str(attrs.get("error") or ""),
            # What the workload chose to say about this step, if anything.
            "key": str(attrs.get("key") or ""),
            "produced": attrs.get("produced") or {},
            # What the step WROTE, as {ref, name}. This service cannot read an artifact — it holds
            # no store credential and that stays true — so these become LINKS to the review app,
            # which can, and which authenticates the person first.
            "artifacts": list(attrs.get("artifacts") or rows.get(name, {}).get("artifacts") or []),
        }
    return list(rows.values())


def download_url(review_app: str, ref: str) -> str:
    """Where a person opens this artifact: the review app, carrying the ref.

    A LINK and never the bytes. `ROLE_ENV["live"]` grants this service `REDIS_URL` and the gate and
    nothing else — no `ARTIFACTS_URL`, no `DATABASE_URL`, no S3 — so it could not serve an artifact
    if it wanted to, and should not: the review app already reads the store and already
    authenticates a person before it does. Giving this page a store credential to save a click
    would put the bytes behind the weaker of the two doors.

    No review app configured means NO link, rather than one that goes nowhere.
    """
    if not review_app or not ref:
        return ""
    return (review_app.rstrip("/") + "/?"
            + urllib.parse.urlencode({"mode": "Runs", "artifact": ref}))


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
 .id{color:var(--dim);font-size:.75rem;font-family:ui-monospace,SFMono-Regular,monospace}
 #chain{display:flex;flex-wrap:wrap;gap:.6rem;margin:.4rem 0 .6rem;font-size:.8rem}
 a.cta{display:inline-block;margin:.2rem 0 1rem;padding:.5rem .8rem;border:1px solid var(--run);
       border-radius:6px;color:var(--run);text-decoration:none;font-size:.85rem}
 a.cta:hover{background:var(--run);color:var(--bg)}
 .hop{color:var(--dim);text-decoration:none}
 .hop.here{color:var(--fg);font-weight:600}
 .hop.running{color:var(--run)} .hop.failed{color:var(--bad)}
 .runhead{list-style:none;margin:1.2rem 0 .2rem;font-size:.78rem;letter-spacing:.06em;
          text-transform:uppercase;color:var(--dim);border-bottom:1px solid var(--line)}
 .items a{color:inherit;text-decoration:underline;text-underline-offset:2px}
 .items a:hover{text-decoration-thickness:2px}
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
 .detail .items{grid-column:2;display:flex;flex-direction:column;gap:.1rem;margin:.1rem 0 .4rem}
 .detail .items div{color:var(--fg);font-size:.82rem}
 .err{color:var(--bad)}
 .idle{color:var(--dim);font-style:italic}
</style>
<main>
 <h1 id="subject">…</h1>
 <div class="meta"><span id="status" class="pill">…</span> <span id="elapsed"></span>
   · <code>%(run)s</code></div>
 <div id="chain"></div>
 <div id="cta"></div>
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
    for (const [field, value] of produced) {
      if (value && typeof value === "object" && Array.isArray(value.items)) {
        // A list shows WHAT IS IN IT. "matched: 13" is the same complaint one level down — it does
        // not say which 13 — and the workload already truncates and says when it did.
        add(field, value.count + (value.truncated ? " (first " + value.items.length + " shown)" : ""));
        const dd = document.createElement("dd");
        dd.className = "items";
        dd.append(...value.items.map(i => {
          const li = document.createElement("div"); li.textContent = i; return li;
        }));
        dl.append(document.createElement("dt"), dd);
      } else {
        add(field, value === null ? "—" : String(value));
      }
    }
  } else if (s.status === "done") {
    add("produced", "nothing recorded", "none");
  }
  // What the step WROTE. A link per artifact, to the review app — this page never serves bytes.
  const wrote = (s.artifacts || []).filter(a => a.url);
  if (wrote.length) {
    const dt = document.createElement("dt"); dt.textContent = "wrote";
    const dd = document.createElement("dd"); dd.className = "items";
    dd.append(...wrote.map(a => {
      const div = document.createElement("div");
      const link = document.createElement("a");
      link.href = a.url; link.textContent = a.name;
      link.target = "_blank"; link.rel = "noopener";
      div.append(link); return div;
    }));
    dl.append(dt, dd);
  }
  if (s.error) add("error", s.error, "err");
  return dl;
}

function render(payload) {
  // The whole handover chain: this run, and whatever its approval released after it. One page,
  // because a run that hands over is the normal shape and watching one at a time hides it.
  const runs = payload.runs || [payload];
  const d = runs.find(r => r.run === RUN) || runs[runs.length - 1];
  $("subject").textContent = d.subject || runs[0].subject || RUN;
  const st = $("status");
  st.textContent = d.status || "";
  st.className = "pill " + (d.status || "");
  $("elapsed").textContent = secs(d.elapsed);
  $("note").textContent = d.error || "";
  $("note").className = d.error ? "err" : "idle";

  // What to do next: the approval this run is waiting on. Shown only while nothing has followed
  // it — once a continuation exists the chain strip is the better answer.
  const last = runs[runs.length - 1];
  const cta = $("cta");
  if (last.approval && last.approval.url && !last.continued_as) {
    cta.innerHTML = "";
    const a = document.createElement("a");
    a.href = last.approval.url; a.target = "_blank"; a.rel = "noopener"; a.className = "cta";
    a.textContent = "This run is waiting on a decision — open the approval →";
    cta.append(a);
  } else { cta.replaceChildren(); }

  // The strip: every run in the chain, the one being viewed marked, the others a link.
  const strip = $("chain");
  strip.replaceChildren(...(runs.length > 1 ? runs.map((r, i) => {
    const span = document.createElement(r.run === RUN ? "span" : "a");
    if (r.run !== RUN) span.href = "/run/" + encodeURIComponent(r.run) + location.search;
    span.className = "hop " + (r.run === RUN ? "here " : "") + (r.status || "");
    span.textContent = (i ? "→ " : "") + (r.process || r.run) + " · " + (r.status || "");
    return span;
  }) : []));
  // Rebuilt from the frame rather than patched step by step: the list is short, and a diff is a
  // second description of the same state that can disagree with the first.
  // Which rows the reader had OPEN, kept across re-renders: a frame arrives every time the run
  // moves, and a details element that closed itself on each one would be unusable.
  const open = new Set([...document.querySelectorAll("li details[open]")].map(d => d.dataset.step));
  const items = [];
  for (const r of runs) {
    if (runs.length > 1) {
      const head = document.createElement("li");
      head.className = "runhead";
      head.textContent = (r.process || r.run) + " · " + (r.status || "");
      items.push(head);
    }
    items.push(...(r.steps || []).map(s => step_li(s, r, open)));
  }
  $("steps").replaceChildren(...items);
}

function step_li(s, r, open) {
  return ((s) => {
    const li = document.createElement("li");
    const mark = s.status === "done" ? "\u2713" : s.status === "fail" ? "\u2717" : "\u2022";
    li.innerHTML =
      '<details><summary><span class="mark"></span><span class="nm"></span>' +
      '<span class="id"></span><span class="s"></span></summary>' +
      '<div class="detail"></div></details>';
    const det = li.querySelector("details");
    det.dataset.step = r.run + "/" + s.name;   // unique per RUN: two runs share step names
    if (open.has(det.dataset.step)) det.open = true;
    li.querySelector(".mark").textContent = mark;
    // The declaration's label leads; the node id stays beside it, smaller, because it is what a
    // log line and a trace span are keyed by. Neither is composed here — a step with no declared
    // title simply reads as its id.
    li.querySelector(".nm").textContent = s.title || s.name;
    li.querySelector(".id").textContent =
      (s.title ? s.name : "") + (s.derived ? "  derived" : "");
    li.querySelector(".s").textContent = secs(s.elapsed);
    li.querySelector(".detail").replaceChildren(detail(s));
    return li;
  })(s);
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
        redis = container.redis()
        # Either a trace or a workflow request id: a link out of a just-given approval carries the
        # latter, and refusing it there would be refusing the one link somebody actually follows.
        run_id = resolve(request.path_params["run_id"], client=redis)

        async def stream():
            last = None
            for _ in range(MAX_TICKS):
                h = runlog.get(run_id, client=redis) or {}
                now = token(h)
                if now != last:
                    last = now
                    yield (f"data: {json.dumps({'runs': chain(run_id, client=redis)})}"
                           "\n\n")
                # Settled means the CHAIN is settled. A parent that finished by handing over is
                # not the end of the work, and closing the stream there is what made the page look
                # dead at the exact moment the next run started.
                if settled(h) and not h.get("continued_as"):
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
