from fastapi import APIRouter
from backend.app.services.race_fetcher import get_races

router = APIRouter(prefix="/races")


@router.get("")
def list_races():
    """Turso に保存された実レースのみ返す。"""
    return get_races()


@router.get("/{race_id}")
def get_race(race_id: str):
    for r in get_races():
        if r.race_id == race_id:
            return r
    return {"error": "not found"}
