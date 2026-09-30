from fastapi import APIRouter, HTTPException
from backend.scraper.oddspark_keiba import fetch_horse_detail

router = APIRouter()


@router.get("/horses/{lineage_nb}")
def get_horse(lineage_nb: str):
    try:
        return fetch_horse_detail(lineage_nb)
    except Exception as e:
        raise HTTPException(status_code=502, detail="horse fetch failed: " + str(e))
