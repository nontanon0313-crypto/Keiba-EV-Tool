from fastapi import APIRouter
from backend.app.services.race_fetcher import get_races
from backend.app.services.prediction import predict_race
from backend.app.services.ev_calc import calc_ev, mock_odds, _candidates, TICKET_TYPES, _TICKET_LABEL
from backend.app.services.result_fetcher import fetch_result
from backend.config import settings

router = APIRouter(prefix="/analytics/tickets")

THRESHOLDS = {
    "trifecta": settings.EV_THRESHOLD_TRIFECTA,
    "trio": settings.EV_THRESHOLD_TRIO,
    "exacta": settings.EV_THRESHOLD_EXACTA,
    "quinella": settings.EV_THRESHOLD_EXACTA,
    "wide": settings.EV_THRESHOLD_WIDE,
    "win": 0.05,
    "place": 0.03,
}


def _hit(ticket_type, combo, winner):
    if winner is None:
        return 0
    parts = combo.split("-")
    try:
        nums = [int(x) for x in parts]
    except ValueError:
        return 0
    w = list(winner[:3])
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


def _collect(scope="all", model_version=None):
    from backend.app.services import bet_store
    bets_data = bet_store.list_bets()
    if model_version:
        bets_data = [b for b in bets_data if b.get("model_version") == model_version]
    voted_keys = set((b["race_id"], b["combo"], b.get("ticket_type", "trifecta")) for b in bets_data)
    races = get_races()
    stats = {}
    for t in TICKET_TYPES:
        stats[t] = {"ticket": t, "label": _TICKET_LABEL.get(t, t), "count": 0, "hits": 0, "stake": 0, "ret": 0, "prob_sum": 0.0, "ev_sum": 0.0}
    for race in races:
        try:
            pred = predict_race(race)
        except Exception:
            continue
        try:
            winner = fetch_result(race.race_id, len(race.runners), pred)
        except Exception:
            winner = None
        for t in TICKET_TYPES:
            for combo, prob in _candidates(pred, t):
                if prob <= 0:
                    continue
                odds = mock_odds(prob, race.race_id, combo, t)
                ev = calc_ev(prob, odds)
                if ev < THRESHOLDS.get(t, 0.12):
                    continue
                is_voted = (race.race_id, combo, t) in voted_keys
                if scope == "voted" and not is_voted:
                    continue
                if scope == "excluded" and is_voted:
                    continue
                amount = 100
                hit = _hit(t, combo, winner)
                ret = int(amount * odds) if hit else 0
                s = stats[t]
                s["count"] += 1
                s["hits"] += hit
                s["stake"] += amount
                s["ret"] += ret
                s["prob_sum"] += prob
                s["ev_sum"] += ev
    out = []
    for t in TICKET_TYPES:
        s = stats[t]
        n = s["count"]
        stake = s["stake"]
        ret = s["ret"]
        out.append({
            "ticket": s["ticket"],
            "label": s["label"],
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
    return out


@router.get("")
def get_ticket_stats(scope: str = "all", model_version: str | None = None):
    if scope not in ("all", "voted", "excluded"):
        scope = "all"
    return {"scope": scope, "model_version": model_version, "tickets": _collect(scope, model_version)}
