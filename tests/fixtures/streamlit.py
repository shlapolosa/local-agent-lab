"""Shared doubles/harness hoisted from the former `test_review_app_pages` module (restructure): imported by every test that
needs them (`from fixtures.streamlit import …`) instead of test-to-test imports.
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================================ fake streamlit
class Rerun(Exception):
    """st.rerun() — Streamlit raises to abort the script; the fake does the same."""


class Stop(Exception):
    """st.stop()."""


class _Rec:
    """Any st.<attr>: callable (records the call), attribute-chainable, usable as a context manager."""

    def __init__(self, st, path):
        self._st, self._path = st, path

    def __call__(self, *a, **k):
        return self._st._call(self._path, a, k)

    def __getattr__(self, n):
        if n.startswith("__"):
            raise AttributeError(n)
        return _Rec(self._st, f"{self._path}.{n}")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSt:
    """`answers` maps a widget label (or file_uploader key) to the value the widget returns."""

    def __init__(self, **answers):
        self.calls, self.answers, self.session_state = [], answers, {}
        self.has_iframe, self.raise_on = True, {}

    def __getattr__(self, n):
        if n.startswith("__") or (n == "iframe" and not self.has_iframe):
            raise AttributeError(n)
        return _Rec(self, n)

    def _call(self, path, a, k):
        self.calls.append((path, a, k))
        leaf = path.rsplit(".", 1)[-1]
        if leaf in self.raise_on:
            raise self.raise_on[leaf]
        label = a[0] if a else k.get("label")
        if leaf == "fragment":
            return lambda f: f
        if leaf == "rerun":
            raise Rerun()
        if leaf == "stop":
            raise Stop()
        if leaf in ("button", "checkbox"):
            return bool(self.answers.get(label, False))
        if leaf == "toggle":
            return self.answers.get(label, k.get("value", False))
        if leaf in ("text_input", "text_area"):
            return self.answers.get(label, k.get("value", ""))
        if leaf in ("radio", "selectbox"):
            opts = list(a[1] if len(a) > 1 else k.get("options", []))
            return self.answers.get(label, opts[k.get("index", 0)] if opts else None)
        if leaf == "file_uploader":
            return self.answers.get(k.get("key", label))
        if leaf == "columns":
            n = len(a[0]) if isinstance(a[0], (list, tuple)) else a[0]
            return [_Rec(self, f"{path}[{i}]") for i in range(n)]
        if leaf == "tabs":
            return [_Rec(self, f"{path}[{i}]") for i in range(len(a[0]))]
        return _Rec(self, path + "()")

    # --- assertions helpers
    def texts(self, leaf):
        """All positional args (joined) of every call whose method name is `leaf`, in order."""
        return [" ".join(str(x) for x in a) for p, a, _ in self.calls if p.rsplit(".", 1)[-1] == leaf]

    def said(self, leaf, needle):
        return any(needle in t for t in self.texts(leaf))

    def count(self, leaf):
        return len(self.texts(leaf))


def load_app():
    """Load src/lab/substrate/review/app.py with the fake streamlit in place (module-level `@st.fragment` must be
    identity); restore the real module afterwards so other tests are untouched."""
    real = sys.modules.get("streamlit")
    sys.modules["streamlit"] = FakeSt()
    try:
        spec = importlib.util.spec_from_file_location("review_app_pages_under_test",
                                                      os.path.join(ROOT, "src", "lab", "substrate", "review", "app.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if real is not None:
            sys.modules["streamlit"] = real
        else:
            del sys.modules["streamlit"]
    return mod


APP = load_app()


# ============================================================================ fake shared modules
class FakeStore:
    def __init__(self, objects=None):
        self.objects, self.puts = dict(objects or {}), []

    def get(self, ref):
        if ref not in self.objects:
            raise KeyError(f"no artifact {ref}")
        return self.objects[ref]

    def put(self, name, data, content_type):
        self.puts.append((name, data, content_type))
        return f"art://u{len(self.puts)}/{name}"


class FakeApprovals:
    def __init__(self, items=(), events=(), history=()):
        self.items, self.events, self.hist = list(items), list(events), list(history)
        self.acked, self.decisions = [], []

    def channel_events(self, channel, block_ms=0, **_):
        assert channel == "review-app" and block_ms == 0
        return list(self.events)

    def ack(self, channel, eid):
        self.acked.append((channel, eid))

    def pending(self):
        return list(self.items)

    def history(self, limit):
        return self.hist[:limit]

    def decide(self, rid, decision, actor, channel, comment):
        self.decisions.append((rid, decision, actor, channel, comment))

    def human_decision(self, rid, decision, actor, channel, comment=""):
        """The one human-gate path the real module enforces: an identified actor, and one final
        answer. The double keeps the SAME contract so a channel cannot be tested on weaker terms."""
        if not (actor or "").strip():
            raise ValueError("actor is required — a decision must carry the human who made it")
        if any(d[0] == rid and d[1] in ("approve", "decline") for d in self.decisions):
            raise ValueError(f"{rid} is already decided")
        return self.decide(rid, decision, actor, channel, comment)


class FakeWorkflows:
    def __init__(self, recent=(), statuses=None):
        self.recent_items, self.statuses, self.requests = list(recent), dict(statuses or {}), []

    def request(self, process, inputs, requester):
        self.requests.append((process, inputs, requester))
        return f"wfr-{len(self.requests)}"

    def recent(self, n):
        return self.recent_items[:n]

    def status(self, rid):
        return dict(self.statuses.get(rid, {}))


class FakeRunlog:
    def __init__(self, active=(), recent=(), runs=None):
        self.active_runs, self.recent_runs, self.runs = list(active), list(recent), dict(runs or {})

    def active(self):
        return list(self.active_runs)

    def recent(self, n):
        return self.recent_runs[:n]

    def get(self, run_id):
        return dict(self.runs.get(run_id, {}))


def install(st, approvals=None, workflows=None, runlog=None, store=None, uploads=None):
    """Swap the app's collaborators for fakes; returns the fake st for assertions."""
    APP.st = st
    APP.approvals = approvals or FakeApprovals()
    APP.workflows = workflows or FakeWorkflows()
    APP.runlog = runlog or FakeRunlog()
    for provider, fake in ((APP.container.artifacts, store), (APP.container.uploads, uploads)):
        provider.reset_override()                 # the app resolves stores through its container's providers
        provider.override(fake or FakeStore())
    return st


XML = (b'<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/" '
       b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
       b'<elements><element identifier="a" xsi:type="ApplicationComponent"><name>Portal</name></element>'
       b'<element identifier="b" xsi:type="Node"><name>Server</name></element>'
       b'<element identifier="c" xsi:type="ApplicationComponent"><name>API</name></element></elements>'
       b'<relationships><relationship identifier="r" xsi:type="Serving" source="a" target="b"/></relationships>'
       b'</model>')

MERMAID = ("flowchart TD\n  read_input[\"read input\"]\n  ba[\"BA\"]\n  store[\"store spec\"]\n"
           "  read_input --> ba\n  ba --> store")


def _request(**over):
    req = {"request_id": "apr-1", "subject": "Malaffi model", "requester": "wf-visio", "status": "pending",
           "created_at": "2026-09-03T10:00:00+00:00", "trace_id": "0123456789abcdef0123456789abcdef",
           "payload": {"xml_ref": "art://x1/model.archimate.xml",
                       "svg_refs": {"Overview": "art://s1/overview.svg", "Detail": "art://s2/detail.svg"},
                       # what the EA repository's ADAPTER says a human must import — opaque to the app
                       "import_artifacts": [
                           {"ref": "art://x1/model.archimate.xml",
                            "label": "Download .archimate.xml (views/diagrams)", "note": "", "media_type": ""},
                           {"ref": "art://x2/objects.xlsx",
                            "label": "Download objects .xlsx (3 objects — create/update)",
                            "note": "Objects are matched by name.", "media_type": ""}],
                       "instructions": "Log in and import BOTH files.",
                       "summary": {"elements": 3, "relations": 1, "views": 2, "violations": 0, "warnings": 1,
                                   "decision": "UPDATE", "base_model": "Malaffi", "domain": "Health",
                                   "matched_existing": 2, "new_elements": 1,
                                   "resolve_rationale": "names match the existing landscape"}}}
    req.update(over)
    return req


def _store_for(req):
    """Every ref the approval mentions — the model, its previews and each import artifact — in a store."""
    p = req["payload"]
    objs = {p["xml_ref"]: XML}
    objs.update({a["ref"]: b"PK-file" for a in p.get("import_artifacts", []) if a["ref"] != p["xml_ref"]})
    objs.update({ref: f"<svg>{label}</svg>".encode() for label, ref in p["svg_refs"].items()})
    return FakeStore(objs)


# ============================================================================ Submit mode
class Upload:
    def __init__(self, name, data):
        self.name, self._data = name, data

    def getvalue(self):
        return self._data


# ============================================================================ Runs mode
def _run(**over):
    h = {"run_id": "run-1", "process": "visio_to_archimate", "input": "/in/sys.vsdx", "status": "running",
         "node": "ba", "node_status": "start", "started_at": "2026-09-03T10:00:00+00:00", "elapsed": 42.0,
         "trace_id": "ff" * 16, "mermaid": MERMAID,
         "nodes": [{"name": "read_input", "status": "start", "ts": "2026-09-03T10:00:01+00:00", "attrs": {}},
                   {"name": "read_input", "status": "done", "ts": "2026-09-03T10:00:03+00:00",
                    "attrs": {"elapsed": 2.0, "shapes": 12}},
                   {"name": "ba", "status": "start", "ts": "2026-09-03T10:00:03+00:00", "attrs": {}}]}
    h.update(over)
    return h
