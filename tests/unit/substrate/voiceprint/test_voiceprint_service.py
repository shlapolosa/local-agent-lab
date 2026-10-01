"""src/lab/substrate/voiceprint/{service,client,gallery}.py — the model as a service, and its adapters.

No model and no database here: the service takes an injected embedder, the client an injected
opener, the gallery an injected connection. What is pinned is the BOUNDARY — who may call, what goes
over the wire, what is refused, and that the stored rows carry consent.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/substrate/voiceprint/"""
import base64
import io
import json
import urllib.error

import pytest
from starlette.testclient import TestClient

from lab.core.speech import SpeechUnavailable
from lab.core.speech.voiceprint import Voiceprint
from lab.platform import config
from lab.substrate.voiceprint import service
from lab.substrate.voiceprint.client import HttpEmbedder
from lab.substrate.voiceprint.gallery import PostgresGallery


class FakeModel:
    model = "fake-ecapa"

    def __init__(self):
        self.seen = []

    def embed(self, clips):
        self.seen.append(list(clips))
        if any(c == b"bad" for c in clips):
            raise ValueError("clips must be 16 kHz mono WAV")
        return [(1.0, 0.0) for _ in clips]


def client(monkeypatch, secret="shh"):
    monkeypatch.setattr(config, "MCP_SHARED_SECRET", secret)
    model = FakeModel()
    return TestClient(service.app_for(model)), model


def b64(*clips):
    return {"clips": [base64.b64encode(c).decode() for c in clips]}


# ------------------------------------------------------------------ the service
def test_only_a_caller_with_the_shared_secret_gets_vectors(monkeypatch):
    """Vectors are biometric data: no secret, no answer."""
    c, model = client(monkeypatch)
    assert c.post("/embed", json=b64(b"x")).status_code == 401
    assert model.seen == []
    ok = c.post("/embed", json=b64(b"x", b"y"), headers={"Authorization": "Bearer shh"})
    assert ok.status_code == 200 and ok.json() == {"model": "fake-ecapa", "vectors": [[1.0, 0.0]] * 2}


def test_healthz_is_open_and_says_which_model_runs(monkeypatch):
    c, _ = client(monkeypatch)
    assert c.get("/healthz").json() == {"model": "fake-ecapa"}


@pytest.mark.parametrize("body,status", [({"clips": ["not base64!"]}, 400), ({"clips": []}, 400),
                                         (b64(b"bad"), 422)])
def test_a_malformed_or_unreadable_request_is_refused_with_a_sentence(monkeypatch, body, status):
    c, _ = client(monkeypatch)
    got = c.post("/embed", json=body, headers={"Authorization": "Bearer shh"})
    assert got.status_code == status and got.json()["error"]


def test_too_many_clips_in_one_call_is_refused(monkeypatch):
    c, model = client(monkeypatch)
    monkeypatch.setattr(service, "MAX_CLIPS", 2)
    assert c.post("/embed", json=b64(b"a", b"b", b"c"), headers={"Authorization": "Bearer shh"}).status_code == 413
    assert model.seen == []


def test_the_service_refuses_to_start_open_on_a_network(monkeypatch):
    monkeypatch.setattr(config, "BIND_HOST", "0.0.0.0")
    monkeypatch.setattr(config, "MCP_SHARED_SECRET", "")
    with pytest.raises(SystemExit, match="refusing"):
        service.main()


# ------------------------------------------------------------------ the client
class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_client_sends_base64_clips_with_the_bearer_and_learns_the_model():
    sent = {}

    def opener(req, timeout):
        sent["auth"], sent["body"] = req.headers.get("Authorization"), json.loads(req.data)
        return Resp(json.dumps({"model": "m9", "vectors": [[0.6, 0.8]]}).encode())

    e = HttpEmbedder("http://vp:9650/", "shh", opener=opener)
    assert e.embed([b"wav"]) == [(0.6, 0.8)] and e.model == "m9"
    assert sent["auth"] == "Bearer shh" and base64.b64decode(sent["body"]["clips"][0]) == b"wav"


def test_an_unreachable_or_refusing_service_is_a_typed_refusal_naming_the_setting():
    def down(req, timeout):
        raise urllib.error.URLError("connection refused")

    with pytest.raises(SpeechUnavailable, match="VOICEPRINT_URL"):
        HttpEmbedder("http://vp:9650", opener=down).embed([b"wav"])
    with pytest.raises(SpeechUnavailable, match="VOICEPRINT_URL"):
        HttpEmbedder("").embed([b"wav"])

    def refuses(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 422, "bad", {}, None)

    with pytest.raises(SpeechUnavailable, match="422"):
        HttpEmbedder("http://vp:9650", opener=refuses).embed([b"wav"])


def test_a_short_answer_is_refused_rather_than_misaligning_clips_and_vectors():
    def short(req, timeout):
        return Resp(json.dumps({"model": "m9", "vectors": [[1.0]]}).encode())

    with pytest.raises(SpeechUnavailable, match="2 vectors and got 1"):
        HttpEmbedder("http://vp:9650", opener=short).embed([b"a", b"b"])


# ------------------------------------------------------------------ the gallery
class FakeCursor:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        self.db.sql.append(sql)
        if sql.startswith("INSERT"):
            self.db.rows.append(params)
        self._params = params

    def fetchall(self):
        kind, key, model, vec, by, src, sec = range(7)
        return [(r[kind], r[key], r[vec], r[model], r[by], r[src], r[sec], "2026-10-01")
                for r in self.db.rows if r[model] == self._params[0]]


class FakeConn:
    def __init__(self):
        self.sql, self.rows, self.commits = [], [], 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1


def test_the_gallery_keeps_vectors_and_consent_and_reads_back_only_its_model():
    db = FakeConn()
    g = PostgresGallery("postgresql://lab/db", connect=lambda url: db)
    g.add(Voiceprint(kind="tag", key="Nabeel", vector=(3.0, 4.0), model="m1", consented_by="org@x", source="apr-1", seconds=9))
    g.add(Voiceprint(kind="tag", key="Ahmed", vector=(1.0, 0.0), model="old", consented_by="org@x"))
    got = g.voiceprints("m1")
    assert [(v.key, v.consented_by, v.source) for v in got] == [("Nabeel", "org@x", "apr-1")]
    assert got[0].vector == pytest.approx((0.6, 0.8))
    assert sum("CREATE TABLE" in s for s in db.sql) == 1, "the table is created once, not per call"
    assert not any("audio" in s.lower() for s in db.sql), "the gallery stores vectors, never audio"


def test_a_gallery_without_postgres_is_a_typed_refusal():
    with pytest.raises(SpeechUnavailable, match="ARTIFACTS_URL"):
        PostgresGallery("file:///tmp/artifacts")
