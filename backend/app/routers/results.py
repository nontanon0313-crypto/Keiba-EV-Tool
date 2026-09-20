from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from backend.app.services.result_store import record_result, all_results, get_result

router = APIRouter(prefix="/results")


class ResultIn(BaseModel):
    race_id: str
    finish_order: List[int]


@router.post("")
def post_result(body: ResultIn):
    if len(body.finish_order) < 3:
        raise HTTPException(400, "finish_order needs at least 3 entries")
    return record_result(body.race_id, body.finish_order[:3])


@router.get("")
def list_results():
    return all_results()


@router.get("/{race_id}")
def get_one(race_id: str):
    r = get_result(race_id)
    if r is None:
        raise HTTPException(404, "not found")
    return {"race_id": race_id, "finish_order": r}
