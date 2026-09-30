"""馬マスタ (lineageNb -> 馬名/所属/性齢) の Turso ストア。"""
import os
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
            "CREATE TABLE IF NOT EXISTS horses ("
            "lineage_nb TEXT PRIMARY KEY,"
            "name TEXT NOT NULL,"
            "age_sex TEXT,"
            "affiliation TEXT,"
            "updated_at TEXT NOT NULL)"
        )
        self.client.execute(
            "CREATE INDEX IF NOT EXISTS idx_horses_name ON horses(name)"
        )

    def upsert_many(self, rows):
        if not rows:
            return 0
        now = datetime.now().isoformat()
        n = 0
        for r in rows:
            ln = r.get("lineage_nb")
            nm = r.get("name")
            if not ln or not nm:
                continue
            try:
                self.client.execute(
                    "INSERT INTO horses (lineage_nb, name, age_sex, affiliation, updated_at) "
                    "VALUES (?,?,?,?,?) "
                    "ON CONFLICT (lineage_nb) DO UPDATE SET "
                    "name=EXCLUDED.name, age_sex=EXCLUDED.age_sex, "
                    "affiliation=EXCLUDED.affiliation, updated_at=EXCLUDED.updated_at",
                    [ln, nm, r.get("age_sex") or "", r.get("affiliation") or "", now],
                )
                n += 1
            except Exception:
                continue
        return n

    def search(self, q, limit=50):
        if not q:
            return []
        like = "%" + q + "%"
        r = self.client.execute(
            "SELECT lineage_nb, name, age_sex, affiliation FROM horses "
            "WHERE name LIKE ? OR lineage_nb LIKE ? "
            "ORDER BY name LIMIT ?",
            [like, like, int(limit)],
        )
        return [
            {"lineage_nb": row[0], "name": row[1], "age_sex": row[2], "affiliation": row[3]}
            for row in r.rows
        ]

    def count(self):
        r = self.client.execute("SELECT COUNT(*) FROM horses")
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


def upsert_many(rows):
    return _get().upsert_many(rows)


def search(q, limit=50):
    return _get().search(q, limit)


def count():
    return _get().count()
