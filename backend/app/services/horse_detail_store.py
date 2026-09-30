"""馬詳細キャッシュ (lineageNb -> HorseDetail payload) の Turso ストア。"""
import os
import json
from datetime import datetime


def _turso_creds():
    u = os.getenv("TURSO_URL")
    t = os.getenv("TURSO_TOKEN")
    if u and t:
        return u, t
    return None, None


class _Turso:
    name = "turso"

    def __init__(self):
        from backend.app.services import turso_client
        client, err = turso_client.get_client()
        if client is None:
            raise RuntimeError("turso_client: " + str(err))
        self.client = client
        self.client.execute(
            "CREATE TABLE IF NOT EXISTS horse_details ("
            "lineage_nb TEXT PRIMARY KEY,"
            "payload TEXT NOT NULL,"
            "updated_at TEXT NOT NULL)"
        )

    def upsert(self, lineage_nb, payload):
        now = datetime.now().isoformat()
        pj = json.dumps(payload, ensure_ascii=False)
        self.client.execute(
            "INSERT INTO horse_details (lineage_nb, payload, updated_at) VALUES (?,?,?) "
            "ON CONFLICT (lineage_nb) DO UPDATE SET payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at",
            [str(lineage_nb), pj, now],
        )

    def get(self, lineage_nb):
        r = self.client.execute(
            "SELECT payload, updated_at FROM horse_details WHERE lineage_nb=?",
            [str(lineage_nb)],
        )
        if not r.rows:
            return None, None
        try:
            payload = json.loads(r.rows[0][0])
        except Exception:
            payload = {}
        return payload, r.rows[0][1]

    def count(self):
        r = self.client.execute("SELECT COUNT(*) FROM horse_details")
        return r.rows[0][0] if r.rows else 0


_backend = None


def _get():
    global _backend
    if _backend is not None:
        return _backend
    u, t = _turso_creds()
    if u and t:
        _backend = _Turso()
    else:
        raise RuntimeError("TURSO_URL/TURSO_TOKEN not set")
    return _backend


def upsert(lineage_nb, payload):
    return _get().upsert(lineage_nb, payload)


def get(lineage_nb):
    return _get().get(lineage_nb)


def count():
    return _get().count()
