from fastapi import APIRouter, HTTPException
from backend.app.services.race_fetcher import get_races
from backend.app.services.prediction import predict_race
from backend.app.services.ev_calc import build_bets
from backend.app.services.vote_manager import send_plan
from backend.app.models.schemas import VotePlan
from datetime import datetime
import uuid
router=APIRouter(prefix="/vote-plans")
@router.post("")
def create_vote_plan(race_id:str, budget:int=2000):
    races=get_races()
    race=next((r for r in races if r.race_id==race_id), None)
    if not race:
        raise HTTPException(404,"race not found")
    if race.has_critical_change:
        raise HTTPException(409,"critical change detected")
    pred=predict_race(race)
    bets=build_bets(race,pred,budget=budget)
    if not bets:
        raise HTTPException(204,"no EV positive")
    plan=VotePlan(client_plan_id=f"keiba-{race.date}-{race.venue}-{race.race_number}-{uuid.uuid4().hex[:6]}", venue=race.venue, race_number=race.race_number, start_at=race.start_at, deadline_at=race.deadline_at, bets=bets, total_amount=sum(b.amount for b in bets), created_at=datetime.now(), race_id=race.race_id)
    result=send_plan(plan)
    return {"plan":plan, "send_result":result}
