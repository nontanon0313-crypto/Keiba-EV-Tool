"""投票プランあり vs なし の実績比較（バッチ取得版）。"""
import os
import time
from datetime import datetime

from backend.app.services import race_store, odds_store
from backend.app.services.prediction import predict_race
from backend.app.services.ev_calc import calc_ev, _candidates
from backend.app.models.schemas import Race, Runner
from backend.config import settings


def race_obj(rid, payload):
    runners = []
    for r in payload.get("runners", []):
        runners.append(Runner(
            horse_number=r.get("horse_number", 0), frame_number=r.get("frame_number", 0),
            horse_id="", horse_name="", jockey="", trainer="",
            weight=r.get("weight", 55.0) or 55.0,
            odds_win=r.get("odds_win") or 50.0, popularity=r.get("popularity"),
        ))
    surf = payload.get("surface") or "ダート"
    if surf not in ("芝", "ダート", "障害"):
        surf = "ダート"
    return Race(race_id=rid, venue="中山", date="20240101", race_number=1,
                start_at=datetime.now(), deadline_at=datetime.now(),
                surface=surf, distance=payload.get("distance") or 1600, runners=runners)


def ro(payload, t, combo):
    tt = payload.get(t) or {}
    e = tt.get(combo)
    if not e:
        return None
    if t == "wide":
        return e.get("max") or e.get("min")
    return e.get("odds")


def hit(t, combo, finish):
    if len(finish) < 3:
        return 0
    try:
        nums = [int(x) for x in combo.split("-")]
    except ValueError:
        return 0
    w = list(finish[:3])
    if t == "quinella": return 1 if len(nums) == 2 and sorted(nums) == sorted(w[:2]) else 0
    if t == "trio": return 1 if sorted(nums) == sorted(w) else 0
    if t == "wide":
        if len(nums) != 2: return 0
        s = sorted(nums)
        pairs = [sorted([w[0], w[1]]), sorted([w[0], w[2]]), sorted([w[1], w[2]])]
        return 1 if s in pairs else 0
    return 0


def main():
    t0 = time.time()
    races = race_store.list_races()
    rids = [it["race_id"] for it in races]
    print(f"races: {len(races)}", flush=True)

    # バッチでオッズ取得
    odds_map = odds_store.get_odds_batch(rids)
    print(f"odds fetched: {len(odds_map)} in {time.time()-t0:.0f}s", flush=True)

    buckets = {"plan": [], "non_plan": []}

    for i, it in enumerate(races):
        rid = it["race_id"]
        payload = it.get("payload") or {}
        finish = payload.get("finish_order") or []
        if len(finish) < 3:
            continue
        odds_p = odds_map.get(rid) or {}
        race = race_obj(rid, payload)
        try:
            pred = predict_race(race)
        except Exception:
            continue

        cands = []
        for t in settings.MIXED_TICKETS:
            for combo, prob in _candidates(pred, t):
                o = ro(odds_p, t, combo)
                if not o or o < settings.MIXED_ODDS_MIN:
                    continue
                ev = calc_ev(prob, o)
                if ev < settings.MIXED_EV_MIN:
                    continue
                cands.append({
                    "t": t, "c": combo, "o": o, "ev": ev,
                    "hit": hit(t, combo, finish), "prob": prob,
                })
        cands.sort(key=lambda x: x["ev"], reverse=True)
        picks = cands[:settings.MIXED_TOP_N]
        pick_keys = set((p["t"], p["c"]) for p in picks)
        for c in cands:
            key = (c["t"], c["c"])
            if key in pick_keys:
                buckets["plan"].append(c)
            else:
                buckets["non_plan"].append(c)

        if (i + 1) % 500 == 0:
            print(f"  progress {i+1}/{len(races)} elapsed={time.time()-t0:.0f}s", flush=True)

    print(f"\n=== 結果 (条件: EV>={settings.MIXED_EV_MIN}, odds>={settings.MIXED_ODDS_MIN}, N={settings.MIXED_TOP_N}) ===", flush=True)
    for name, arr in buckets.items():
        n = len(arr)
        if not n:
            continue
        hits = sum(a["hit"] for a in arr)
        ret = sum(a["o"] if a["hit"] else 0 for a in arr)
        roi = (ret / n - 1) * 100
        avg_ev = sum(a["ev"] for a in arr) / n * 100
        avg_prob = sum(a["prob"] for a in arr) / n * 100
        avg_odds = sum(a["o"] for a in arr) / n
        print(f"{name}: n={n} hits={hits} hr={hits/n*100:.2f}% roi={roi:+.1f}% avg_ev={avg_ev:+.1f}% avg_prob={avg_prob:.2f}% avg_odds={avg_odds:.1f}", flush=True)

    print(f"\ndone in {time.time()-t0:.0f}s", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
