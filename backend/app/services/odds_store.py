"""スクレイプしたオッズを保存。Turso / file。"""
import os
import atexit
import json
from pathlib import Path
from datetime import datetime

FILE_PATH = Path("scraped_odds.json")


def _turso_creds():
    u = os.getenv("TURSO_URL")
    t = os.getenv("TURSO_TOKEN")
    if u and t:
        return u, t
    return None, None


class _File:
    name = "file"

    def load(self):
        if not FILE_PATH.exists():
            return []
        try:
            return json.loads(FILE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []

    def upsert(self, race_id, payload):
        items = self.load()
        items = [r for r in items if r.get("race_id") != race_id]
        items.append({"race_id": race_id, "payload": payload, "scraped_at": datetime.now().isoformat()})
        FILE_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


class _Turso:
    name = "turso"

    def __init__(self, url, token):
        import libsql_client
        http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
        self.client = libsql_client.create_client_sync(url=http_url, auth_token=token)
        self.client.execute(
            "CREATE TABLE IF NOT EXISTS scraped_odds ("
            "race_id TEXT PRIMARY KEY,"
            "payload TEXT NOT NULL,"
            "scraped_at TEXT NOT NULL)"
        )

    def close(self):
        try:
            self.client.close()
        except Exception:
            pass

    def load(self):
        r = self.client.execute("SELECT race_id, payload, scraped_at FROM scraped_odds ORDER BY race_id")
        out = []
        for row in r.rows:
            try:
                payload = json.loads(row[1])
            except Exception:
                payload = {}
            out.append({"race_id": row[0], "payload": payload, "scraped_at": row[2]})
        return out

    def upsert(self, race_id, payload):
        pj = json.dumps(payload, ensure_ascii=False)
        self.client.execute(
            "INSERT INTO scraped_odds (race_id, payload, scraped_at) VALUES (?,?,?) "
            "ON CONFLICT (race_id) DO UPDATE SET payload=EXCLUDED.payload, scraped_at=EXCLUDED.scraped_at",
            [race_id, pj, datetime.now().isoformat()],
        )


_backend = None


def _get():
    global _backend
    if _backend is not None:
        return _backend
    u, t = _turso_creds()
    if u and t:
        try:
            _backend = _Turso(u, t)
            print("[odds_store] backend=turso")
            return _backend
        except Exception as e:
            print("[odds_store] turso init failed:", e)
    _backend = _File()
    print("[odds_store] backend=file")
    return _backend


def close_odds_store():
    global _backend
    if _backend is not None and hasattr(_backend, "close"):
        try:
            _backend.close()
        except Exception:
            pass
    _backend = None


atexit.register(close_odds_store)


def save_odds(race_id, payload):
    _get().upsert(race_id, payload)
    return {"saved": True, "race_id": race_id}


def get_odds(race_id):
    for r in _get().load():
        if r.get("race_id") == race_id:
            return r.get("payload")
    return None


def list_odds():
    return _get().load()


def list_race_ids():
    """race_id のリストだけを軽量に取得（payloadなし）。"""
    backend = _get()
    # Tursoの場合: SELECT race_id のみ
    if hasattr(backend, "client"):
        try:
            r = backend.client.execute("SELECT race_id FROM scraped_odds")
            return [row[0] for row in r.rows]
        except Exception as e:
            print("[odds_store] list_race_ids failed:", e)
            return []
    # Fileの場合
    return [it.get("race_id") for it in backend.load() if it.get("race_id")]
