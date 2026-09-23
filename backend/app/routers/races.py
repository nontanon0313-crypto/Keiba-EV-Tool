from fastapi import APIRouter
from backend.app.services.race_fetcher import get_races, get_real_races

router = APIRouter(prefix="/races")


@router.get("")
def list_races(source: str = "auto"):
    """source: auto(実データ優先) / mock / real"""
    if source == "mock":
        return get_races()
    real = get_real_races()
    if source == "real" or (source == "auto" and real):
        return real
    return get_races()


@router.get("/{race_id}")
def get_race(race_id: str):
    real = get_real_races()
    for r in real:
        if r.race_id == race_id:
            return r
    races = get_races()
    for r in races:
        if r.race_id == race_id:
            return r
    return {"error": "not found"}
