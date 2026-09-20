"""予想スナップショット保存。storage.py と同じ環境変数を参照。"""
import os
import atexit
import json
from datetime import datetime
from pathlib import Path

FILE_PATH = Path("predictions.json")


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

    def upsert(self, race_id, model_version, created_at, payload):
        items = self.load()
        items = [p for p in items if not (p.get("race_id") == race_id and p.get("model_version") == model_version)]
        items.append({"race_id": race_id, "model_version": model_version, "created_at": created_at, "payload": payload})
        FILE_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


class _Turso:
    name = "turso"

    def __init__(self, url, token):
        import libsql_client
        http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
        self.client = libsql_client.create_client_sync(url=http_url, auth_token=token)
        self.client.execute(
            "CREATE TABLE IF NOT EXISTS predictions ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "race_id TEXT NOT NULL,"
            "model_version TEXT NOT NULL,"
            "created_at TEXT NOT NULL,"
            "payload TEXT NOT NULL,"
            "UNIQUE(race_id, model_version))"
        )

    def close(self):
        try:
            self.client.close()
        except Exception:
            pass

    def load(self):
        r = self.client.execute("SELECT race_id, model_version, created_at, payload FROM predictions ORDER BY id")
        out = []
        for row in r.rows:
            try:
                payload = json.loads(row[3])
            except Exception:
                payload = {}
            out.append({"race_id": row[0], "model_version": row[1], "created_at": row[2], "payload": payload})
        return out

    def upsert(self, race_id, model_version, created_at, payload):
        pj = json.dumps(payload, ensure_ascii=False)
        self.client.execute(
            "INSERT INTO predictions (race_id, model_version, created_at, payload) VALUES (?,?,?,?) "
            "ON CONFLICT (race_id, model_version) DO UPDATE SET created_at = EXCLUDED.created_at, payload = EXCLUDED.payload",
            [race_id, model_version, created_at, pj],
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
            print("[pred_store] backend=turso")
            return _backend
        except Exception as e:
            print("[pred_store] turso init failed:", e)
    _backend = _File()
    print("[pred_store] backend=file")
    return _backend


def close_prediction_store():
    global _backend
    if _backend is not None and hasattr(_backend, "close"):
        try:
            _backend.close()
        except Exception:
            pass
    _backend = None


atexit.register(close_prediction_store)


def save_prediction(race_id, model_version, payload):
    created_at = datetime.now().isoformat()
    _get().upsert(race_id, model_version, created_at, payload)
    return {"saved": True, "race_id": race_id, "model_version": model_version}


def get_latest(race_id, model_version=None):
    items = [p for p in _get().load() if p.get("race_id") == race_id]
    if model_version:
        items = [p for p in items if p.get("model_version") == model_version]
    if not items:
        return None
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items[0]


def list_all(race_id=None):
    items = _get().load()
    if race_id:
        items = [p for p in items if p.get("race_id") == race_id]
    return items
