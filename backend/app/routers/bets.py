from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Any
from backend.app.services import bet_store
import json

router = APIRouter(prefix="/bets")


class BetIn(BaseModel):
    race_id: str
    combo: str
    amount: int
    odds: float
    prob: Optional[float] = None
    ev: Optional[float] = None
    ticket_type: Optional[str] = "trifecta"


class SettleIn(BaseModel):
    payout: int


@router.post("")
def create(b: BetIn):
    return bet_store.add_bet(b.race_id, b.combo, b.amount, b.odds, b.prob, b.ev, b.ticket_type or "trifecta")


@router.get("")
def list_all():
    return bet_store.list_bets()


@router.get("/export")
def export_bets():
    data = bet_store._load()
    return JSONResponse(content=data, headers={"Content-Disposition": "attachment; filename=bets.json"})


@router.post("/import")
def import_bets(payload: List[Any]):
    return bet_store.replace_all(payload)


@router.get("/summary")
def get_summary():
    return bet_store.summary()


@router.get("/curve")
def get_curve():
    return bet_store.curve()


@router.post("/{bet_id}/settle")
def settle(bet_id: int, body: SettleIn):
    return bet_store.settle_bet(bet_id, body.payout)


@router.delete("/{bet_id}")
def delete(bet_id: int):
    return bet_store.delete_bet(bet_id)
