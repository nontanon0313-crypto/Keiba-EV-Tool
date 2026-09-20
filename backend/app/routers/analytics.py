from fastapi import APIRouter
from backend.app.services.race_fetcher import get_races
from backend.app.services.prediction import predict_race
from backend.app.services.ev_calc import calc_ev, mock_trifecta_odds

router = APIRouter(prefix="/analytics")


def _prob_bins():
    bins = []
    for i in range(50):
        bins.append((i * 0.001, (i + 1) * 0.001))
    for i in range(10):
        bins.append((0.050 + i * 0.005, 0.050 + (i + 1) * 0.005))
    for i in range(10):
        bins.append((0.100 + i * 0.010, 0.100 + (i + 1) * 0.010))
    for i in range(6):
        bins.append((0.200 + i * 0.050, 0.200 + (i + 1) * 0.050))
    return bins


def _odds_bins():
    bins = []
    for i in range(200):
        bins.append((1 + i, 2 + i))
    for i in range(16):
        bins.append((200 + i * 50, 200 + (i + 1) * 50))
    bins.append((1000, 999999))
    return bins


def _format(bins, samples, kind):
    rows = []
    for i, (lo, hi) in enumerate(bins):
        s = samples[i]
        if not s:
            continue
        n = len(s)
        avg_prob = sum(x[0] for x in s) / n
        avg_odds = sum(x[1] for x in s) / n
        avg_ev = sum(x[2] for x in s) / n
        if kind == "prob":
            label = f"{lo:.3f}-{hi:.3f}"
        else:
            label = f"{lo}-{hi}" if hi < 999999 else f"{lo}+"
        rows.append({
            "range": label,
            "count": n,
            "avg_prob": avg_prob,
            "avg_odds": avg_odds,
            "expected_profit_pct": avg_ev * 100,
            "actual_hits": 0,
            "actual_attempts": 0,
            "actual_rate": None,
        })
    return rows


@router.get("")
def get_analytics():
    pb = _prob_bins()
    ob = _odds_bins()
    prob_samples = {i: [] for i in range(len(pb))}
    odds_samples = {i: [] for i in range(len(ob))}
    races = get_races()
    for race in races:
        try:
            pred = predict_race(race)
        except Exception:
            continue
        for tri in pred.trifecta_probs:
            odds = mock_trifecta_odds(tri.prob)
            ev = calc_ev(tri.prob, odds)
            for i, (lo, hi) in enumerate(pb):
                if lo <= tri.prob < hi:
                    prob_samples[i].append((tri.prob, odds, ev))
                    break
            for i, (lo, hi) in enumerate(ob):
                if lo <= odds < hi:
                    odds_samples[i].append((tri.prob, odds, ev))
                    break
    return {
        "prob_bins": _format(pb, prob_samples, "prob"),
        "odds_bins": _format(ob, odds_samples, "odds"),
    }
