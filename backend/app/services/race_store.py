"""スクレイプしたレースを保存。Turso / file の2バックエンド。"""
import os
import atexit
import json
from pathlib import Path
from datetime import datetime

FILE_PATH = Path("scraped_races.json")


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

    def list_today_open(self, today_str):
        """本日かつ未完了のレースのみ返す（メモリ内でフィルタ）。"""
        out = []
        for it in self.load():
            p = it.get("payload") or {}
            if p.get("date") != today_str:
                continue
            fo = p.get("finish_order")
            if fo:
                continue
            out.append(it)
        return out


class _Turso:
    name = "turso"

    def __init__(self):
        from backend.app.services import turso_client
        client, err = turso_client.get_client()
        if client is None:
            raise RuntimeError("turso_client: " + str(err))
        self.client = client
        self.client.execute(
            "CREATE TABLE IF NOT EXISTS scraped_races ("
            "race_id TEXT PRIMARY KEY,"
            "payload TEXT NOT NULL,"
            "scraped_at TEXT NOT NULL)"
        )

    def close(self):
        # 共有クライアントは閉じない（turso_client.close_client で一括）
        pass

    def load(self):
        r = self.client.execute("SELECT race_id, payload, scraped_at FROM scraped_races ORDER BY race_id")
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
            "INSERT INTO scraped_races (race_id, payload, scraped_at) VALUES (?,?,?) "
            "ON CONFLICT (race_id) DO UPDATE SET payload=EXCLUDED.payload, scraped_at=EXCLUDED.scraped_at",
            [race_id, pj, datetime.now().isoformat()],
        )

    def list_today_open(self, today_str):
        """本日かつ未完了のレースのみ返す（SQL側でフィルタ）。"""
        r = self.client.execute(
            "SELECT race_id, payload, scraped_at FROM scraped_races "
            "WHERE json_extract(payload, '$.date') = ? "
            "AND (json_extract(payload, '$.finish_order') IS NULL "
            "     OR json_extract(payload, '$.finish_order') = '[]')",
            [today_str],
        )
        out = []
        for row in r.rows:
            try:
                payload = json.loads(row[1])
            except Exception:
                payload = {}
            out.append({"race_id": row[0], "payload": payload, "scraped_at": row[2]})
        return out


_backend = None


def _get():
    global _backend
    if _backend is not None:
        return _backend
    u, t = _turso_creds()
    if u and t:
        try:
            _backend = _Turso()
            print("[race_store] backend=turso")
            return _backend
        except Exception as e:
            print("[race_store] turso init failed:", e)
    _backend = _File()
    print("[race_store] backend=file")
    return _backend


def close_race_store():
    """_backend の参照を切るだけ。共有クライアントは閉じない。"""
    global _backend
    _backend = None


# atexit は使わない（main.py の shutdown で一括クリーンアップする）


def save_race(race_id, payload):
    _get().upsert(race_id, payload)
    return {"saved": True, "race_id": race_id}


def get_race(race_id):
    for r in _get().load():
        if r.get("race_id") == race_id:
            return r.get("payload")
    return None


def list_races():
    return _get().load()


def list_today_open_races(today_str):
    """本日かつ未完了のレースのみ返す。"""
    return _get().list_today_open(today_str)


def list_race_ids():
    """race_id のリストだけを軽量に取得。"""
    backend = _get()
    if hasattr(backend, "client"):
        try:
            r = backend.client.execute("SELECT race_id FROM scraped_races")
            return [row[0] for row in r.rows]
        except Exception as e:
            print("[race_store] list_race_ids failed:", e)
            return []
    return [it.get("race_id") for it in backend.load() if it.get("race_id")]
