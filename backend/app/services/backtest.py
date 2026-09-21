"""保存済みレースから予想→EV→実結果を突き合わせて統計を返す。"""
from datetime import datetime
from typing import Dict, List

from backend.app.models.schemas import Race, Runner
from backend.app.services.prediction import predict_race
from backend.app.services.ev_calc import calc_ev, mock_odds, _candidates, TICKET_TYPES, _TICKET_LABEL
from backend.app.services import race_store
from backend.app.services import odds_store
from backend.config import settings

THRESHOLDS = {
    "trifecta": settings.EV_THRESHOLD_TRIFECTA,
    "trio": settings.EV_THRESHOLD_TRIO,
    "exacta": settings.EV_THRESHOLD_EXACTA,
    "quinella": settings.EV_THRESHOLD_EXACTA,
    "wide": settings.EV_THRESHOLD_WIDE,
    "win": 0.05,
    "place": 0.03,
}


def _hit(ticket_type, combo, finish):
    if not finish or len(finish) < 3:
        return 0
    parts = combo.split("-")
    try:
        nums = [int(x) for x in parts]
    except ValueError:
        return 0
    w = list(finish[:3])
    if ticket_type == "trifecta":
        return 1 if nums == w else 0
    if ticket_type == "trio":
        return 1 if sorted(nums) == sorted(w) else 0
    if ticket_type == "exacta":
        return 1 if len(nums) == 2 and nums == w[:2] else 0
    if ticket_type == "quinella":
        return 1 if len(nums) == 2 and sorted(nums) == sorted(w[:2]) else 0
    if ticket_type == "wide":
        if len(nums) != 2:
            return 0
        s = sorted(nums)
        pairs = [sorted([w[0], w[1]]), sorted([w[0], w[2]]), sorted([w[1], w[2]])]
        return 1 if s in pairs else 0
    if ticket_type == "win":
        return 1 if len(nums) == 1 and nums[0] == w[0] else 0
    if ticket_type == "place":
        return 1 if len(nums) == 1 and nums[0] in w[:3] else 0
    return 0




def _real_odds(odds_payload, ticket, combo):
    if not odds_payload:
        return None
    t = odds_payload.get(ticket) or {}
    entry = t.get(combo)
    if not entry:
        return None
    if ticket == "wide":
        v = entry.get("max") or entry.get("min")
        return v
    return entry.get("odds")


def _race_from_payload(race_id, payload):
    runners = []
    for r in payload.get("runners", []):
        runners.append(Runner(
            horse_number=r.get("horse_number", 0),
            frame_number=r.get("frame_number", 0),
            horse_id="",
            horse_name=r.get("horse_name", ""),
            jockey=r.get("jockey", ""),
            trainer="",
            weight=r.get("weight", 55.0) or 55.0,
            odds_win=r.get("odds_win") or 50.0,
            popularity=r.get("popularity"),
        ))
    return Race(
        race_id=race_id,
        venue="",
        date=race_id[:8],
        race_number=int(race_id[10:12]),
        start_at=datetime.now(),
        deadline_at=datetime.now(),
        surface=payload.get("surface") or "ダート",
        distance=payload.get("distance") or 1600,
        runners=runners,
    )


def run_backtest(tickets=None, ev_threshold_override=None, amount=100, min_prob=0.0):
    """全保存レースを走査し、券種別の的中率・ROIを集計。"""
    if tickets is None:
        tickets = list(TICKET_TYPES)
    items = race_store.list_races()
    stats = {}
    for t in tickets:
        stats[t] = {"ticket": t, "label": _TICKET_LABEL.get(t, t), "count": 0, "hits": 0,
                    "stake": 0, "ret": 0, "prob_sum": 0.0, "ev_sum": 0.0, "races": 0}
    per_race = []
    total = len(items)
    for idx, it in enumerate(items):
        if (idx + 1) % 20 == 0 or idx == 0:
            print("[backtest] {}/{}".format(idx + 1, total), flush=True)
        race_id = it.get("race_id")
        payload = it.get("payload") or {}
        finish = payload.get("finish_order") or []
        if len(finish) < 3:
            continue
        race = _race_from_payload(race_id, payload)
        odds_payload = odds_store.get_odds(race_id)
        try:
            pred = predict_race(race)
        except Exception:
            continue
        race_row = {"race_id": race_id, "finish": finish, "tickets": {}}
        for t in tickets:
            threshold = THRESHOLDS.get(t, 0.12)
            if ev_threshold_override is not None:
                threshold = ev_threshold_override
            ticket_count = 0
            ticket_hits = 0
            ticket_stake = 0
            ticket_ret = 0
            for combo, prob in _candidates(pred, t):
                if prob < min_prob:
                    continue
                odds = _real_odds(odds_payload, t, combo)
                if odds is None or odds <= 0:
                    continue
                ev = calc_ev(prob, odds)
                if ev < threshold:
                    continue
                hit = _hit(t, combo, finish)
                ret = int(amount * odds) if hit else 0
                ticket_count += 1
                ticket_hits += hit
                ticket_stake += amount
                ticket_ret += ret
                s = stats[t]
                s["count"] += 1
                s["hits"] += hit
                s["stake"] += amount
                s["ret"] += ret
                s["prob_sum"] += prob
                s["ev_sum"] += ev
            if ticket_count:
                stats[t]["races"] += 1
            race_row["tickets"][t] = {"count": ticket_count, "hits": ticket_hits,
                                       "stake": ticket_stake, "ret": ticket_ret}
        per_race.append(race_row)
    out = []
    for t in tickets:
        s = stats[t]
        n = s["count"]
        stake = s["stake"]
        ret = s["ret"]
        out.append({
            "ticket": s["ticket"],
            "label": s["label"],
            "races": s["races"],
            "count": n,
            "hits": s["hits"],
            "hit_rate": (s["hits"] / n) if n else 0.0,
            "expected_hit_rate": (s["prob_sum"] / n) if n else 0.0,
            "stake": stake,
            "ret": ret,
            "profit": ret - stake,
            "roi": ((ret - stake) / stake) if stake else 0.0,
            "expected_roi": (s["ev_sum"] / n) if n else 0.0,
        })
    return {"total_races": len(items), "tickets": out, "per_race": per_race}
