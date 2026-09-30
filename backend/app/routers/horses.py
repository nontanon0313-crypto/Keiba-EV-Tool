from fastapi import APIRouter, HTTPException, Query
from backend.scraper.oddspark_keiba import fetch_horse_detail
from backend.app.services import horse_store

router = APIRouter()


@router.get("/horses/search")
def search_horses(q: str = Query("", min_length=1), limit: int = 50):
    if not q:
        return {"items": []}
    try:
        return {"items": horse_store.search(q, limit=limit)}
    except Exception as e:
        raise HTTPException(status_code=502, detail="search failed: " + str(e))


@router.get("/horses/{lineage_nb}")
def get_horse(lineage_nb: str):
    try:
        return fetch_horse_detail(lineage_nb)
    except Exception as e:
        raise HTTPException(status_code=502, detail="horse fetch failed: " + str(e))
