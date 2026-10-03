from fastapi import APIRouter, HTTPException, Query
import os
import json

from backend.app.services import turso_client

router = APIRouter(prefix="/jockeys")


def _get_client():
    return turso_client.get_client()


@router.get("/search")
def search_jockeys(q: str = Query("", min_length=1), limit: int = 50):
    """騎手名で部分一致検索する。"""
    client, err = _get_client()
    if client is None:
        raise HTTPException(500, "turso_client: " + str(err))
    try:
        r = client.execute("SELECT payload FROM jockey_stats_cache WHERE id=1")
        if not r.rows:
            return {"items": []}
        d = json.loads(r.rows[0][0])
    except Exception as e:
        raise HTTPException(500, "load error: " + repr(e))
    jockeys = d.get("jockeys") or []
    out = []
    for j in jockeys:
        name = j.get("name") or ""
        if q in name:
            out.append({
                "name": name,
                "n": j.get("n"),
                "win_rate": j.get("win_rate"),
                "place_rate": j.get("place_rate"),
                "show_rate": j.get("show_rate"),
                "roi_pct": j.get("roi_pct"),
            })
            if len(out) >= limit:
                break
    return {"items": out, "generated_at": d.get("generated_at")}


@router.get("/{name}")
def get_jockey(name: str):
    """騎手の詳細成績を返す。"""
    client, err = _get_client()
    if client is None:
        raise HTTPException(500, "turso_client: " + str(err))
    try:
        r = client.execute("SELECT payload FROM jockey_stats_cache WHERE id=1")
        if not r.rows:
            return {"error": "no cache"}
        d = json.loads(r.rows[0][0])
    except Exception as e:
        raise HTTPException(500, "load error: " + repr(e))
    jockeys = d.get("jockeys") or []
    for j in jockeys:
        if j.get("name") == name:
            return j
    return {"error": "not found"}
