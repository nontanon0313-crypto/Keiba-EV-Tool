from fastapi import APIRouter, HTTPException
from backend.app.services.scraper import netkeiba
from backend.app.services import race_store
from backend.app.services.backtest import run_backtest
import time

router = APIRouter(prefix="/backtest")


@router.post("/ingest")
def ingest(date: str, sleep: float = 1.5):
    try:
        ids = netkeiba.fetch_race_list(date)
    except Exception as e:
        raise HTTPException(500, "list failed: " + str(e))
    saved = []
    failed = []
    for i, rid in enumerate(ids):
        try:
            data = netkeiba.fetch_race_result(rid)
            if data and data.get("finish_order"):
                race_store.save_race(rid, data)
                saved.append(rid)
            else:
                failed.append(rid)
        except Exception as e:
            failed.append(rid + ":" + str(e)[:40])
        if i < len(ids) - 1:
            time.sleep(sleep)
    return {"date": date, "total": len(ids), "saved": len(saved), "failed": len(failed),
            "saved_ids": saved[:50], "failed_ids": failed[:20]}


@router.get("/races")
def list_saved():
    items = race_store.list_races()
    out = []
    for it in items:
        p = it.get("payload") or {}
        out.append({
            "race_id": it["race_id"],
            "race_name": p.get("race_name", ""),
            "surface": p.get("surface", ""),
            "distance": p.get("distance", 0),
            "runners": len(p.get("runners", [])),
            "finish_order": p.get("finish_order", []),
            "scraped_at": it.get("scraped_at", ""),
        })
    return {"count": len(out), "races": out}


@router.get("/run")
def run(tickets: str = None, min_prob: float = 0.0, amount: int = 100):
    """保存済みレースでバックテスト実行。tickets=trifecta,trio,... (カンマ区切り)。"""
    tl = None
    if tickets:
        tl = [t.strip() for t in tickets.split(",") if t.strip()]
    try:
        result = run_backtest(tickets=tl, amount=amount, min_prob=min_prob)
    except Exception as e:
        raise HTTPException(500, "backtest failed: " + str(e))
    result.pop("per_race", None)
    return result
