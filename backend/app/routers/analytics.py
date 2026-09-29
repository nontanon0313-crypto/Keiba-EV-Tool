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

# === Turso クライアントのシングルトン ===
# リクエストごとに create_client_sync すると aiohttp セッションが
# GCまで残り、メモリリークの原因になる。モジュール全体で共有する。
_client = None


def _get_client():
    """Turso クライアントを返す。初回のみ作成、以降は使い回す。
    Returns: (client, error_message)
    """
    global _client
    if _client is not None:
        return _client, None
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
        _client = libsql_client.create_client_sync(url=http_url, auth_token=token)
        return _client, None
    except Exception as e:
        _client = None
        return None, str(e)


def close_client():
    """アプリ終了時に呼ぶ。"""
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
        _client = None


def _load_from_turso():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not url or not token:
        return None, "TURSO_URL/TURSO_TOKEN not set"
    client, err = _get_client()
    if client is None:
        return None, err
    try:
        r = client.execute("SELECT payload, updated_at FROM analytics_cache WHERE id=1")
        rows = list(r.rows)
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

def _load_features_from_turso():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not url or not token:
        return None, "TURSO_URL/TURSO_TOKEN not set"
    client, err = _get_client()
    if client is None:
        return None, err
    try:
        r = client.execute("SELECT payload, updated_at FROM analytics_feature_cache WHERE id=1")
        rows = list(r.rows)
        if not rows:
            return None, "no feature cache row"
        payload = json.loads(rows[0][0])
        payload["_updated_at"] = rows[0][1]
        payload["_source"] = "turso"
        return payload, None
    except Exception as e:
        return None, str(e)


@router.get("/features")
def get_features():
    data, err = _load_features_from_turso()
    if data is None:
        raise HTTPException(503, "feature cache not available: " + str(err))
    return data

@router.get("/multi")
def get_multi():
    """券種別検証の結果を全券種分返す。"""
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not url or not token:
        raise HTTPException(503, "TURSO_URL/TURSO_TOKEN not set")
    client, err = _get_client()
    if client is None:
        raise HTTPException(503, "multi cache load failed: " + str(err))
    try:
        r = client.execute("SELECT ticket, payload, updated_at FROM analytics_multi_cache")
        rows = list(r.rows)
    except Exception as e:
        raise HTTPException(503, "multi cache load failed: " + str(e))
    out = {}
    for row in rows:
        try:
            payload = json.loads(row[1])
            payload["_updated_at"] = row[2]
            out[row[0]] = payload
        except Exception:
            continue
    return {"tickets": out}

@router.get("/frame_by_condition")
def get_frame_by_condition():
    """枠番×会場×芝ダート×距離帯×馬場状態 の集計結果を返す。"""
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not url or not token:
        raise HTTPException(503, "TURSO_URL/TURSO_TOKEN not set")
    client, err = _get_client()
    if client is None:
        raise HTTPException(503, "frame cache load failed: " + str(err))
    try:
        r = client.execute("SELECT payload, updated_at FROM analytics_frame_cache WHERE id=1")
        rows = list(r.rows)
        if not rows:
            raise HTTPException(503, "no frame cache row")
        payload = json.loads(rows[0][0])
        payload["_updated_at"] = rows[0][1]
        return payload
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(503, "frame cache load failed: " + str(e))
