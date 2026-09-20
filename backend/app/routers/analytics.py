from fastapi import APIRouter
from backend.app.services.race_fetcher import get_races
from backend.app.services.prediction import predict_race
from backend.app.services.ev_calc import calc_ev, mock_trifecta_odds
from backend.app.services.result_fetcher import fetch_result

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


def _features():
    return {
        "popularity": {"label": "1着予想馬の人気", "ranges": [("1",1,1),("2",2,2),("3",3,3),("4-6",4,6),("7-9",7,9),("10+",10,99)]},
        "weight": {"label": "1着予想馬の斤量", "ranges": [("-53",0,53),("53-55",53,55),("55-57",55,57),("57+",57,99)]},
        "frame": {"label": "1着予想馬の枠番", "ranges": [("1-2",1,2),("3-4",3,4),("5-6",5,6),("7-8",7,8)]},
        "odds_win": {"label": "1着予想馬の単勝", "ranges": [("-5",0,5),("5-10",5,10),("10-20",10,20),("20-50",20,50),("50+",50,99999)]},
    }


def _get(runner, key):
    if runner is None:
        return None
    v = getattr(runner, key, None)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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
        attempts = n
        hits = sum(x[3] for x in s)
        label = "{:.3f}-{:.3f}".format(lo, hi) if kind == "prob" else ("{}-{}".format(lo, hi) if hi < 999999 else "{}+".format(lo))
        rows.append({"range": label, "count": n, "avg_prob": avg_prob, "avg_odds": avg_odds, "expected_profit_pct": avg_ev * 100, "actual_hits": hits, "actual_attempts": attempts, "actual_rate": (hits / attempts) if attempts > 0 else None})
    return rows


def _format_features(features, agg):
    out = []
    for key, conf in features.items():
        rows = []
        for (label, lo, hi) in conf["ranges"]:
            s = agg.get(key, {}).get(label, [])
            if not s:
                continue
            n = len(s)
            avg_prob = sum(x[0] for x in s) / n
            avg_odds = sum(x[1] for x in s) / n
            hits = sum(x[2] for x in s)
            rows.append({"range": label, "count": n, "avg_prob": avg_prob, "avg_odds": avg_odds, "expected_profit_pct": (avg_prob * avg_odds - 1.0) * 100, "actual_hits": hits, "actual_attempts": n, "actual_rate": (hits / n) if n else None})
        out.append({"feature": key, "label": conf["label"], "rows": rows})
    return out


@router.get("")
def get_analytics():
    pb = _prob_bins()
    ob = _odds_bins()
    prob_samples = {i: [] for i in range(len(pb))}
    odds_samples = {i: [] for i in range(len(ob))}
    feat_conf = _features()
    feat_agg = {k: {r[0]: [] for r in c["ranges"]} for k, c in feat_conf.items()}
    races = get_races()
    for race in races:
        try:
            pred = predict_race(race)
        except Exception:
            continue
        runner_map = {r.horse_number: r for r in race.runners}
        try:
            winner = fetch_result(race.race_id, len(race.runners))
        except Exception:
            winner = None
        for tri in pred.trifecta_probs:
            odds = mock_trifecta_odds(tri.prob, race.race_id, tri.combo)
            ev = calc_ev(tri.prob, odds)
            hit = 0
            parts = tri.combo.split("-")
            if winner is not None and len(parts) == 3:
                try:
                    nums = [int(parts[0]), int(parts[1]), int(parts[2])]
                    if nums == list(winner[:3]):
                        hit = 1
                except ValueError:
                    pass
            for i, (lo, hi) in enumerate(pb):
                if lo <= tri.prob < hi:
                    prob_samples[i].append((tri.prob, odds, ev, hit))
                    break
            for i, (lo, hi) in enumerate(ob):
                if lo <= odds < hi:
                    odds_samples[i].append((tri.prob, odds, ev, hit))
                    break
            if parts:
                try:
                    first_num = int(parts[0])
                except ValueError:
                    first_num = None
                if first_num is not None:
                    r = runner_map.get(first_num)
                    if r is not None:
                        pop = _get(r, "popularity")
                        w = _get(r, "weight")
                        fr = _get(r, "frame_number")
                        ow = _get(r, "odds_win")
                        for (label, lo, hi) in feat_conf["popularity"]["ranges"]:
                            if pop is not None and lo <= pop <= hi:
                                feat_agg["popularity"][label].append((tri.prob, odds, hit))
                        for (label, lo, hi) in feat_conf["weight"]["ranges"]:
                            if w is not None and lo <= w < hi:
                                feat_agg["weight"][label].append((tri.prob, odds, hit))
                        for (label, lo, hi) in feat_conf["frame"]["ranges"]:
                            if fr is not None and lo <= fr <= hi:
                                feat_agg["frame"][label].append((tri.prob, odds, hit))
                        for (label, lo, hi) in feat_conf["odds_win"]["ranges"]:
                            if ow is not None and lo <= ow < hi:
                                feat_agg["odds_win"][label].append((tri.prob, odds, hit))
    return {"prob_bins": _format(pb, prob_samples, "prob"), "odds_bins": _format(ob, odds_samples, "odds"), "features": _format_features(feat_conf, feat_agg)}
