"""出走表 (ent1) の事前キャッシュ。未来レースの出走表を保存し、
当日は Turso から読むだけでスクレイプ不要にする。"""
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
            "CREATE TABLE IF NOT EXISTS prefetched_entries ("
            "race_id TEXT PRIMARY KEY,"
            "date TEXT,"
            "payload TEXT NOT NULL,"
            "scraped_at TEXT NOT NULL)"
        )
        self.client.execute(
            "CREATE INDEX IF NOT EXISTS idx_prefetched_entries_date ON prefetched_entries(date)"
        )

    def upsert(self, race_id, date, payload):
        now = datetime.now().isoformat()
        pj = json.dumps(payload, ensure_ascii=False)
        self.client.execute(
            "INSERT INTO prefetched_entries (race_id, date, payload, scraped_at) VALUES (?,?,?,?) "
            "ON CONFLICT (race_id) DO UPDATE SET payload=EXCLUDED.payload, date=EXCLUDED.date, scraped_at=EXCLUDED.scraped_at",
            [race_id, date, pj, now],
        )

    def get(self, race_id):
        r = self.client.execute(
            "SELECT payload, scraped_at FROM prefetched_entries WHERE race_id=?",
            [race_id],
        )
        if not r.rows:
            return None, None
        try:
            payload = json.loads(r.rows[0][0])
        except Exception:
            payload = {}
        return payload, r.rows[0][1]

    def list_by_date(self, date):
        r = self.client.execute(
            "SELECT race_id, payload, scraped_at FROM prefetched_entries WHERE date=? ORDER BY race_id",
            [date],
        )
        out = []
        for row in r.rows:
            try:
                payload = json.loads(row[1])
            except Exception:
                payload = {}
            out.append({"race_id": row[0], "payload": payload, "scraped_at": row[2]})
        return out

    def count(self):
        r = self.client.execute("SELECT COUNT(*) FROM prefetched_entries")
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


def upsert(race_id, date, payload):
    return _get().upsert(race_id, date, payload)


def get(race_id):
    return _get().get(race_id)


def list_by_date(date):
    return _get().list_by_date(date)


def count():
    return _get().count()
