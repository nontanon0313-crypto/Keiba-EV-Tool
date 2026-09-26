"""analyze_quinella のどこで止まるか切り分け。"""
import os
import sys
from collections import defaultdict
from datetime import datetime

from backend.app.services import race_store, odds_store
from backend.app.services.prediction import predict_race
from backend.app.services.ev_calc import _candidates
from backend.app.models.schemas import Race, Runner
from backend.scraper.oddspark_keiba import extract_payouts

print("step1: imports OK", flush=True)

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

print("step2: race_obj OK", flush=True)

races = race_store.list_races()
print(f"step3: races={len(races)}", flush=True)

rids = [it["race_id"] for it in races]
odds_map = odds_store.get_odds_batch(rids)
print(f"step4: odds_map={len(odds_map)}", flush=True)

processed = 0
for i, it in enumerate(races[:50]):  # 50件だけ
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
    except Exception as e:
        print(f"  extract_payouts error: {e}", flush=True)
        continue
    try:
        race = race_obj(rid, payload)
    except Exception as e:
        print(f"  race_obj error: {e}", flush=True)
        continue
    try:
        pred = predict_race(race)
    except Exception as e:
        print(f"  predict_race error: {e}", flush=True)
        continue
    try:
        quinella_probs = dict(_candidates(pred, "quinella"))
    except Exception as e:
        print(f"  _candidates error: {e}", flush=True)
        continue
    processed += 1

print(f"step5: processed (先頭50件中) = {processed}", flush=True)
print("step6: 完了", flush=True)
