from fastapi import APIRouter
from backend.app.services.race_fetcher import get_races
from backend.app.services.prediction import predict_race
router=APIRouter(prefix="/predictions")
@router.get("/{race_id}")
def get_prediction(race_id:str):
    races=get_races()
    for r in races:
        if r.race_id==race_id:
            return predict_race(r)
    return {"error":"not found"}
