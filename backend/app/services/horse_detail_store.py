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


    def get_many(self, lineage_nbs):
        """複数の lineage_nb を一括取得。{lineage_nb: payload} を返す。"""
        if not lineage_nbs:
            return {}
        out = {}
        # Turso の IN 句は可変長制限があるため、500件ずつ
        CHUNK = 500
        ids = [str(x) for x in lineage_nbs if x]
        for i in range(0, len(ids), CHUNK):
            chunk = ids[i:i+CHUNK]
            placeholders = ",".join(["?"] * len(chunk))
            r = self.client.execute(
                "SELECT lineage_nb, payload FROM horse_details WHERE lineage_nb IN (" + placeholders + ")",
                chunk,
            )
            for row in r.rows:
                try:
                    out[row[0]] = json.loads(row[1])
                except Exception:
                    pass
        return out

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

def get_many(lineage_nbs):
    return _get().get_many(lineage_nbs)
