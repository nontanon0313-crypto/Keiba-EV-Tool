"""検証: 事前に生成した analytics_cache.json を読み取るだけ。
計算は backend/scripts/build_analytics.py が行う。
"""
from fastapi import APIRouter, HTTPException
from pathlib import Path
import json
import time

router = APIRouter(prefix="/analytics")

CACHE_FILE = Path("analytics_cache.json")


@router.get("")
def get_analytics():
    if not CACHE_FILE.exists():
        raise HTTPException(503, "analytics not built yet. run backend/scripts/build_analytics.py")
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(500, "cache read failed: " + str(e))
    try:
        data["cache_age_sec"] = int(time.time() - CACHE_FILE.stat().st_mtime)
    except Exception:
        data["cache_age_sec"] = None
    return data


@router.get("/status")
def get_status():
    if not CACHE_FILE.exists():
        return {"built": False}
    return {"built": True, "age_sec": int(time.time() - CACHE_FILE.stat().st_mtime), "size": CACHE_FILE.stat().st_size}
