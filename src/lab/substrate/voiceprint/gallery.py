"""`PostgresGallery` — the `VoiceprintGallery` port on the substrate's Postgres. Vectors only, never audio.

One table, `lab_voiceprints`, created on first use. Matching happens in Python: a gallery is the people
of one organisation's meetings — tens, not millions — so a vector index (pgvector) would be machinery
with nothing to speed up. The rows are biometric data, so the table is touched ONLY through this class,
and only speech-mcp is built with it.
"""
from __future__ import annotations

from lab.core.speech import SpeechUnavailable
from lab.core.speech.voiceprint import Voiceprint

DDL = """
CREATE TABLE IF NOT EXISTS lab_voiceprints (
    id           BIGSERIAL PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('identity', 'tag')),
    key          TEXT NOT NULL,
    model        TEXT NOT NULL,
    vector       REAL[] NOT NULL,
    consented_by TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT '',
    seconds      REAL NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS lab_voiceprints_model ON lab_voiceprints (model);
"""


class PostgresGallery:
    def __init__(self, url: str, connect=None) -> None:
        if not (url or "").startswith(("postgres://", "postgresql://")):
            raise SpeechUnavailable("voiceprints", "the voiceprint gallery needs a Postgres store",
                                    "set ARTIFACTS_URL to a postgresql:// URL")
        if connect is None:
            import psycopg
            connect = psycopg.connect
        self._url, self._connect, self._ready = url, connect, False

    def _conn(self):
        conn = self._connect(self._url)
        if not self._ready:
            with conn.cursor() as cur:
                cur.execute(DDL)
            conn.commit()
            self._ready = True
        return conn

    def voiceprints(self, model: str) -> list[Voiceprint]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT kind, key, vector, model, consented_by, source, seconds, created_at "
                        "FROM lab_voiceprints WHERE model = %s ORDER BY id", (model,))
            return [Voiceprint(kind=k, key=key, vector=tuple(v), model=m, consented_by=c, source=s,
                               seconds=float(sec), created_at=str(at))
                    for k, key, v, m, c, s, sec, at in cur.fetchall()]

    def add(self, vp: Voiceprint) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO lab_voiceprints (kind, key, model, vector, consented_by, source, seconds) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (vp.kind, vp.key, vp.model, list(vp.vector), vp.consented_by, vp.source, vp.seconds))
            conn.commit()
