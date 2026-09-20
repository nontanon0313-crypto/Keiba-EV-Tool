from fastapi import APIRouter, HTTPException
from backend.app.services.scraper import netkeiba
from backend.app.services import race_store

router = APIRouter(prefix="/backtest")


@router.post("/ingest")
def ingest(date: str, sleep: float = 1.5):
    """指定日 (YYYYMMDD) の全レース結果を取得して保存。"""
    try:
        ids = netkeiba.fetch_race_list(date)
    except Exception as e:
        raise HTTPException(500, "list failed: " + str(e))
    saved = []
    failed = []
    import time
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
    return {"date": date, "total": len(ids), "saved": len(saved), "failed": len(failed), "saved_ids": saved[:50], "failed_ids": failed[:20]}


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
