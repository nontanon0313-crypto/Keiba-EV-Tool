"""実データで閾値を再探索。総当たりでROI最良のパラメータを探す。"""
import os
import time
from datetime import datetime
from itertools import product

from backend.app.services import race_store, odds_store
from backend.app.services.prediction import predict_race
from backend.app.services.ev_calc import calc_ev, real_odds_for, _candidates, _TICKET_LABEL
from backend.app.models.schemas import Race, Runner


def _race_obj(rid, payload):
    runners = []
    for r in payload.get("runners", []):
        try:
            runners.append(Runner(
                horse_number=int(r.get("horse_number", 0)),
                frame_number=int(r.get("frame_number", 0)),
                horse_id=r.get("horse_id", ""),
                horse_name=r.get("horse_name", ""),
                jockey=r.get("jockey", ""),
                trainer=r.get("trainer", ""),
                weight=float(r.get("weight", 55.0) or 55.0),
                horse_weight=r.get("horse_weight"),
                horse_weight_change=r.get("horse_weight_change"),
                odds_win=float(r.get("odds_win", 50.0) or 50.0),
                popularity=r.get("popularity"),
                status=r.get("status", "出走"),
            ))
        except (ValueError, TypeError):
            continue
    surf = payload.get("surface") or "ダート"
    if surf not in ("芝", "ダート", "障害"):
        surf = "ダート"
    return Race(
        race_id=rid, venue=payload.get("venue", ""), date=payload.get("date", ""),
        race_number=int(payload.get("race_number", 0)),
        start_at=datetime.now(), deadline_at=datetime.now(),
        surface=surf, distance=int(payload.get("distance", 0) or 0),
        runners=runners,
    )


def _hit(ticket, combo, finish):
    if not finish or len(finish) < 3:
        return 0
    try:
        nums = [int(x) for x in combo.split("-")]
    except ValueError:
        return 0
    w = list(finish[:3])
    if ticket == "trifecta": return 1 if nums == w else 0
    if ticket == "trio": return 1 if sorted(nums) == sorted(w) else 0
    if ticket == "exacta": return 1 if len(nums) == 2 and nums == w[:2] else 0
    if ticket == "quinella": return 1 if len(nums) == 2 and sorted(nums) == sorted(w[:2]) else 0
    if ticket == "wide":
        if len(nums) != 2: return 0
        s = sorted(nums)
        pairs = [sorted([w[0], w[1]]), sorted([w[0], w[2]]), sorted([w[1], w[2]])]
        return 1 if s in pairs else 0
    if ticket == "win": return 1 if len(nums) == 1 and nums[0] == w[0] else 0
    if ticket == "place": return 1 if len(nums) == 1 and nums[0] in w[:3] else 0
    return 0


def _build_candidates_all(race, pred):
    """1レースの全券種候補を実オッズで返す。"""
    out = []
    for t in ["quinella", "wide", "exacta", "trio", "trifecta"]:
        for combo, prob in _candidates(pred, t):
            if prob <= 0:
                continue
            odds = real_odds_for(race.race_id, t, combo)
            if odds is None:
                continue
            out.append({"ticket": t, "combo": combo, "prob": prob, "odds": odds, "ev": calc_ev(prob, odds)})
    return out


def simulate(cands_per_race, tickets, min_prob, min_odds, ev_min, top_n, stake=100):
    """1レースあたり上位N点を均等賭け。ROI・的中率を返す。"""
    total_bets = 0
    hits = 0
    stake_total = 0
    payout_total = 0
    races_bet = 0
    for r in cands_per_race:
        filtered = [c for c in r["cands"] if c["ticket"] in tickets and c["prob"] >= min_prob and c["odds"] >= min_odds and c["ev"] >= ev_min]
        if not filtered:
            continue
        filtered.sort(key=lambda x: x["ev"], reverse=True)
        picks = filtered[:top_n]
        races_bet += 1
        for p in picks:
            total_bets += 1
            stake_total += stake
            hit = _hit(p["ticket"], p["combo"], r["finish"])
            if hit:
                hits += 1
                payout_total += int(stake * p["odds"])
    roi = (payout_total - stake_total) / stake_total * 100 if stake_total else 0
    hr = hits / total_bets * 100 if total_bets else 0
    return {"races": races_bet, "bets": total_bets, "hits": hits, "hit_rate": hr, "roi": roi,
            "stake": stake_total, "payout": payout_total}


def main():
    t0 = time.time()
    items = race_store.list_races()
    print(f"races: {len(items)}", flush=True)
    rids = [it["race_id"] for it in items]
    odds_map = odds_store.get_odds_batch(rids) if hasattr(odds_store, "get_odds_batch") else {}
    print(f"odds: {len(odds_map)}", flush=True)

    cands_per_race = []
    for i, it in enumerate(items):
        rid = it["race_id"]
        payload = it.get("payload") or {}
        finish = payload.get("finish_order") or []
        if len(finish) < 3:
            continue
        try:
            race = _race_obj(rid, payload)
            pred = predict_race(race)
        except Exception:
            continue
        cands = _build_candidates_all(race, pred)
        if cands:
            cands_per_race.append({"rid": rid, "finish": finish, "cands": cands})
        if (i + 1) % 200 == 0:
            print(f"  scan {i+1}/{len(items)} {time.time()-t0:.0f}s", flush=True)
    print(f"races with candidates: {len(cands_per_race)}", flush=True)

    # グリッド
    ticket_sets = {
        "quinella": ("quinella",),
        "wide": ("wide",),
        "quinella+wide": ("quinella", "wide"),
        "quinella+wide+trio": ("quinella", "wide", "trio"),
        "all5": ("quinella", "wide", "exacta", "trio", "trifecta"),
    }
    min_probs = [0.0, 0.01, 0.02, 0.03, 0.05]
    min_odds_list = [0, 10, 20, 30, 50, 100]
    ev_mins = [0.0, 0.1, 0.2, 0.5, 1.0]
    top_ns = [1, 2, 3, 5]

    results = []
    total_grid = len(ticket_sets) * len(min_probs) * len(min_odds_list) * len(ev_mins) * len(top_ns)
    done = 0
    for tname, tickets in ticket_sets.items():
        for mp in min_probs:
            for mo in min_odds_list:
                for em in ev_mins:
                    for tn in top_ns:
                        r = simulate(cands_per_race, tickets, mp, mo, em, tn)
                        done += 1
                        if r["bets"] < 100:
                            continue
                        results.append({"tickets": tname, "min_prob": mp, "min_odds": mo,
                                        "ev_min": em, "top_n": tn, **r})
        print(f"  {tname} done {done}/{total_grid} {time.time()-t0:.0f}s", flush=True)

    results.sort(key=lambda x: x["roi"], reverse=True)
    print("\n=== TOP 20 (ROI順) ===")
    print(f"{'tickets':<20} {'min_prob':>8} {'min_odds':>8} {'ev_min':>6} {'top_n':>5} {'races':>6} {'bets':>6} {'hits':>5} {'hr%':>6} {'roi%':>8}")
    for r in results[:20]:
        print(f"{r['tickets']:<20} {r['min_prob']:>8.3f} {r['min_odds']:>8} {r['ev_min']:>6.2f} {r['top_n']:>5} {r['races']:>6} {r['bets']:>6} {r['hits']:>5} {r['hit_rate']:>6.2f} {r['roi']:>+8.1f}")

    # 結果をファイル保存
    import json
    with open("grid_search_result.json", "w", encoding="utf-8") as f:
        json.dump(results[:500], f, ensure_ascii=False, indent=2)
    print(f"\nsaved grid_search_result.json ({len(results)} combos)", flush=True)
    print(f"done in {time.time()-t0:.0f}s", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
