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

# 共有 Turso クライアントを使用（backend/app/services/turso_client.py）
# 全ストアで1つのクライアントを共有することで、aiohttp セッションの
# 多重作成によるメモリリークを防ぐ。
from backend.app.services import turso_client


def _get_client():
    """共有 Turso クライアントを返す。
    Returns: (client, error_message)
    """
    return turso_client.get_client()


def close_client():
    """後方互換のため残す。実際は turso_client.close_client を呼ぶ。"""
    turso_client.close_client()


def _load_from_turso(scope=""):
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not url or not token:
        return None, "TURSO_URL/TURSO_TOKEN not set"
    client, err = _get_client()
    if client is None:
        return None, err
    try:
        if scope:
            r = client.execute("SELECT payload, updated_at FROM analytics_cache WHERE id=1 AND scope=?", [scope])
            rows = list(r.rows)
            if not rows:
                return None, "no cache row for scope=" + str(scope)
            payload = json.loads(rows[0][0])
            payload["_updated_at"] = rows[0][1]
            payload["_source"] = "turso"
            return payload, None
        # scope 未指定: 全スコープを結合
        r = client.execute("SELECT scope, payload, updated_at FROM analytics_cache WHERE id=1")
        rows = list(r.rows)
        if not rows:
            return None, "no cache rows"
        merged = {"scopes": {}, "ticket_stats": [], "meta": {}, "_source": "turso"}
        latest = ""
        for row in rows:
            sc = row[0]
            p2 = json.loads(row[1])
            for k, v in (p2.get("scopes") or {}).items():
                merged["scopes"][k] = v
            if p2.get("ticket_stats") and not merged["ticket_stats"]:
                merged["ticket_stats"] = p2["ticket_stats"]
            if p2.get("meta") and not merged["meta"]:
                merged["meta"] = p2["meta"]
            if row[2] > latest:
                latest = row[2]
        merged["_updated_at"] = latest
        return merged, None
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
def get_analytics(scope: str = ""):
    data, err = _load_from_turso(scope)
    if data is None:
        if scope:
            raise HTTPException(503, "analytics cache not available: turso=" + str(err))
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

@router.get("/feature_single")
def get_feature_single():
    """単一特徴量の検証結果を返す。共有 Turso クライアント経由。"""
    client, err = _get_client()
    if client is None:
        return {"error": err, "features": {}, "samples": 0}
    try:
        r = client.execute("SELECT payload FROM feature_analytics_cache WHERE id=1")
        if not r.rows:
            return {"features": {}, "samples": 0}
        d = json.loads(r.rows[0][0])
    except Exception as e:
        return {"error": str(e), "features": {}, "samples": 0}
    return d


@router.get("/feature_interactions")
def get_feature_interactions():
    """特徴量の交互作用検証結果を返す。レスポンスを上位20件に絞って軽量化。"""
    client, err = _get_client()
    if client is None:
        return {"error": err, "promising_diff": [], "promising_roi": [], "samples": 0}
    try:
        r = client.execute("SELECT payload FROM feature_interactions_cache WHERE id=1")
        if not r.rows:
            return {"promising_diff": [], "promising_roi": [], "samples": 0}
        d = json.loads(r.rows[0][0])
    except Exception as e:
        return {"error": str(e), "promising_diff": [], "promising_roi": [], "samples": 0}
    diff = d.get("promising_diff", [])
    roi = d.get("promising_roi", [])
    return {
        "samples": d.get("samples"),
        "total_cells": d.get("total_cells"),
        "promising_diff": diff[:20],
        "promising_roi": roi[:20],
        "generated_at": d.get("generated_at"),
    }

@router.get("/model_params")
def get_model_params():
    """学習済み PL モデルのパラメータを返す。"""
    client, err = _get_client()
    if client is None:
        return {"error": err}
    try:
        r = client.execute("SELECT payload FROM model_params WHERE id='pl'")
        if not r.rows:
            return {"error": "no model params"}
        d = json.loads(r.rows[0][0])
    except Exception as e:
        return {"error": str(e)}
    # loss_history は 200点あるので 20点に間引く
    lh = d.get("loss_history", [])
    if len(lh) > 20:
        step = max(1, len(lh) // 20)
        d["loss_history"] = lh[::step]
    return d

@router.get("/condition_deviation")
def get_condition_deviation():
    """条件別（会場×距離×馬場×クラス）の市場乖離分析結果を返す。"""
    client, err = _get_client()
    if client is None:
        return {"error": err}
    try:
        r = client.execute("SELECT payload FROM condition_deviation_cache WHERE id=1")
        if not r.rows:
            return {"error": "no cache"}
        d = json.loads(r.rows[0][0])
    except Exception as e:
        return {"error": str(e)}
    return d
