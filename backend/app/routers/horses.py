from fastapi import APIRouter, HTTPException, Query
from backend.scraper.oddspark_keiba import fetch_horse_detail
from backend.app.services import horse_store, horse_detail_store

router = APIRouter()


@router.get("/horses/search")
def search_horses(q: str = Query("", min_length=1), limit: int = 50):
    if not q:
        return {"items": []}
    try:
        return {"items": horse_store.search(q, limit=limit)}
    except Exception as e:
        import traceback
        print("[horses.search] ERROR: " + repr(e), flush=True)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="search failed: " + repr(e))


@router.get("/horses/{lineage_nb}")
def get_horse(lineage_nb: str, refresh: int = 0):
    # refresh=1 で強制再取得、それ以外はキャッシュ優先
    if not refresh:
        try:
            payload, updated = horse_detail_store.get(lineage_nb)
            if payload and payload.get("title"):
                payload["_cache"] = "hit"
                payload["_updated_at"] = updated
                return payload
        except Exception as e:
            print("[horses.cache] lookup error: " + repr(e), flush=True)
    try:
        d = fetch_horse_detail(lineage_nb)
    except Exception as e:
        raise HTTPException(status_code=502, detail="horse fetch failed: " + str(e))
    try:
        horse_detail_store.upsert(lineage_nb, d)
    except Exception as e:
        print("[horses.cache] upsert error: " + repr(e), flush=True)
    d["_cache"] = "miss"
    return d
