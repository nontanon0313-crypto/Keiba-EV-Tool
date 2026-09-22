"""検証: Turso の analytics_cache テーブルから読み取る。
事前に backend/scripts/build_analytics.py を実行してキャッシュを生成する。
"""
from fastapi import APIRouter, HTTPException
from pathlib import Path
import os
import json
import time

router = APIRouter(prefix="/analytics")

LOCAL_CACHE = Path("analytics_cache.json")


def _load_from_turso():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not url or not token:
        return None, "TURSO_URL/TURSO_TOKEN not set"
    try:
        import libsql_client
    except ImportError:
        return None, "libsql_client not installed"
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    try:
        client = libsql_client.create_client_sync(url=http_url, auth_token=token)
        r = client.execute("SELECT payload, updated_at FROM analytics_cache WHERE id=1")
        rows = list(r.rows)
        try:
            client.close()
        except Exception:
            pass
        if not rows:
            return None, "no cache row"
        payload = json.loads(rows[0][0])
        payload["_updated_at"] = rows[0][1]
        payload["_source"] = "turso"
        return payload, None
    except Exception as e:
        return None, str(e)


def _load_from_file():
    if not LOCAL_CACHE.exists():
        return None, "local cache not found"
    try:
        data = json.loads(LOCAL_CACHE.read_text(encoding="utf-8"))
        data["_source"] = "file"
        data["_age_sec"] = int(time.time() - LOCAL_CACHE.stat().st_mtime)
        return data, None
    except Exception as e:
        return None, str(e)


@router.get("")
def get_analytics():
    data, err = _load_from_turso()
    if data is None:
        data, err2 = _load_from_file()
        if data is None:
            raise HTTPException(503, "analytics cache not available: turso=" + str(err) + " file=" + str(err2))
    return data


@router.get("/status")
def get_status():
    info = {"turso": None, "file": None}
    d, e = _load_from_turso()
    if d is None:
        info["turso"] = {"available": False, "error": e}
    else:
        info["turso"] = {"available": True, "updated_at": d.get("_updated_at"),
                          "races": (d.get("summary") or {}).get("races")}
    if LOCAL_CACHE.exists():
        info["file"] = {"available": True, "age_sec": int(time.time() - LOCAL_CACHE.stat().st_mtime)}
    else:
        info["file"] = {"available": False}
    return info
