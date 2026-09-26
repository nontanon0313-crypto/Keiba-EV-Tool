"""全件処理でどこまで進むか。"""
import os
from datetime import datetime

from backend.app.services import race_store, odds_store
from backend.app.services.prediction import predict_race
from backend.app.services.ev_calc import _candidates
from backend.app.models.schemas import Race, Runner
from backend.scraper.oddspark_keiba import extract_payouts

def race_obj(rid, payload):
    runners = []
    for r in payload.get("runners", []):
        runners.append(Runner(
            horse_number=r.get("horse_number", 0),
            frame_number=r.get("frame_number", 0),
            horse_id="", horse_name="", jockey="", trainer="",
            weight=r.get("weight", 55.0) or 55.0,
            odds_win=r.get("odds_win") or 50.0,
            popularity=r.get("popularity"),
        ))
    surf = payload.get("surface") or "ダート"
    if surf not in ("芝", "ダート", "障害"):
        surf = "ダート"
    return Race(
        race_id=rid, venue=payload.get("venue", ""), date=payload.get("date", ""),
        race_number=int(payload.get("race_number", 0) or 0),
        start_at=datetime.now(), deadline_at=datetime.now(),
        surface=surf, distance=payload.get("distance") or 1600, runners=runners,
    )

races = race_store.list_races()
rids = [it["race_id"] for it in races]
odds_map = odds_store.get_odds_batch(rids)

processed = 0
for i, it in enumerate(races):
    rid = it["race_id"]
    payload = it.get("payload") or {}
    finish = payload.get("finish_order") or []
    if len(finish) < 3:
        continue
    odds_p = odds_map.get(rid) or {}
    quinella = odds_p.get("quinella") or {}
    if not quinella:
        continue
    try:
        payouts_dict = extract_payouts(payload.get("payouts") or {})
        race = race_obj(rid, payload)
        pred = predict_race(race)
        quinella_probs = dict(_candidates(pred, "quinella"))
    except Exception as e:
        print(f"  err {rid}: {e}", flush=True)
        continue
    processed += 1
    if (i + 1) % 1000 == 0:
        print(f"  i={i+1}/{len(races)} processed={processed}", flush=True)

print(f"完了: processed={processed}", flush=True)
