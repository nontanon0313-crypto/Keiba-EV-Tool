from fastapi import APIRouter
from backend.app.services.race_fetcher import get_races
from backend.app.services.prediction import predict_race
from backend.app.services.ev_calc import calc_ev, mock_trifecta_odds
from backend.app.services.result_store import all_results

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
        attempts = sum(1 for x in s if x[3])
        hits = sum(x[4] for x in s)
        if kind == "prob":
            label = "{:.3f}-{:.3f}".format(lo, hi)
        else:
            label = "{}-{}".format(lo, hi) if hi < 999999 else "{}+".format(lo)
        rows.append({
            "range": label,
            "count": n,
            "avg_prob": avg_prob,
            "avg_odds": avg_odds,
            "expected_profit_pct": avg_ev * 100,
            "actual_hits": hits,
            "actual_attempts": attempts,
            "actual_rate": (hits / attempts) if attempts > 0 else None,
        })
    return rows


@router.get("")
def get_analytics():
    pb = _prob_bins()
    ob = _odds_bins()
    prob_samples = {i: [] for i in range(len(pb))}
    odds_samples = {i: [] for i in range(len(ob))}
    results = all_results()
    races = get_races()
    for race in races:
        try:
            pred = predict_race(race)
        except Exception:
            continue
        winner = results.get(race.race_id)
        for tri in pred.trifecta_probs:
            odds = mock_trifecta_odds(tri.prob, race.race_id, tri.combo)
            ev = calc_ev(tri.prob, odds)
            has_result = winner is not None
            hit = 0
            if has_result:
                parts = tri.combo.split("-")
                if len(parts) == 3:
                    try:
                        nums = [int(parts[0]), int(parts[1]), int(parts[2])]
                        if nums == list(winner[:3]):
                            hit = 1
                    except ValueError:
                        pass
            sample = (tri.prob, odds, ev, has_result, hit)
            for i, (lo, hi) in enumerate(pb):
                if lo <= tri.prob < hi:
                    prob_samples[i].append(sample)
                    break
            for i, (lo, hi) in enumerate(ob):
                if lo <= odds < hi:
                    odds_samples[i].append(sample)
                    break
    return {"prob_bins": _format(pb, prob_samples, "prob"), "odds_bins": _format(ob, odds_samples, "odds")}
