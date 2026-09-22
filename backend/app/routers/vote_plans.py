from fastapi import APIRouter, HTTPException
from backend.app.services.race_fetcher import get_races
from backend.app.services.prediction import predict_race
from backend.app.services.ev_calc import build_bets, build_mixed_bets, TICKET_TYPES
from backend.app.services.vote_manager import send_plan
from backend.app.services.prediction_store import save_prediction
from backend.app.models.schemas import VotePlan
from datetime import datetime
import uuid

router = APIRouter(prefix="/vote-plans")


@router.post("")
def create_vote_plan(race_id: str, ticket_type: str = "trifecta", min_prob: float = 0.0, min_odds: float = 0.0, collateral: int = 100000, max_investment: int = 10000):
    if ticket_type != "mixed" and ticket_type not in TICKET_TYPES:
        raise HTTPException(400, "unknown ticket_type")
    races = get_races()
    race = next((r for r in races if r.race_id == race_id), None)
    if not race:
        raise HTTPException(404, "race not found")
    if race.has_critical_change:
        raise HTTPException(409, "critical change detected")
    pred = predict_race(race)
    try:
        save_prediction(race.race_id, pred.model_version, pred.model_dump(mode="json"))
    except Exception as e:
        print("[vote_plans] save_prediction failed:", e)
    if ticket_type == "mixed":
        bets = build_mixed_bets(race, pred, odds_min=max(min_odds, 0) or None, collateral=collateral, max_investment=max_investment)
    else:
        bets = build_bets(race, pred, ticket_type=ticket_type, min_prob=min_prob, min_odds=min_odds, collateral=collateral, max_investment=max_investment)
    if not bets:
        raise HTTPException(204, "no EV positive")
    plan = VotePlan(client_plan_id=f"keiba-{race.date}-{race.venue}-{race.race_number}-{uuid.uuid4().hex[:6]}", venue=race.venue, race_number=race.race_number, start_at=race.start_at, deadline_at=race.deadline_at, bets=bets, total_amount=sum(b.amount for b in bets), created_at=datetime.now(), race_id=race.race_id)
    for b in plan.bets:
        b.model_version = pred.model_version
    result = send_plan(plan)
    return {"plan": plan, "send_result": result, "ticket_type": ticket_type, "model_version": pred.model_version}
