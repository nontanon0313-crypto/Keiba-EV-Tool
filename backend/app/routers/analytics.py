from fastapi import APIRouter
from backend.app.services.race_fetcher import get_races
from backend.app.services.prediction import predict_race
from backend.app.services.ev_calc import calc_ev, mock_trifecta_odds
from backend.app.services.result_fetcher import fetch_result
from backend.app.services import bet_store

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


def _features_conf():
    return {"popularity": {"label": "1着予想馬の人気", "ranges": [("1", 1, 1), ("2", 2, 2), ("3", 3, 3), ("4-6", 4, 6), ("7-9", 7, 9), ("10+", 10, 99)]}, "weight": {"label": "1着予想馬の斤量", "ranges": [("-53", 0, 53), ("53-55", 53, 55), ("55-57", 55, 57), ("57+", 57, 99)]}, "frame": {"label": "1着予想馬の枠番", "ranges": [("1-2", 1, 2), ("3-4", 3, 4), ("5-6", 5, 6), ("7-8", 7, 8)]}, "odds_win": {"label": "1着予想馬の単勝", "ranges": [("-5", 0, 5), ("5-10", 5, 10), ("10-20", 10, 20), ("20-50", 20, 50), ("50+", 50, 99999)]}}


def _empty_bucket():
    pb = _prob_bins()
    ob = _odds_bins()
    fc = _features_conf()
    return {"prob_samples": {i: [] for i in range(len(pb))}, "odds_samples": {i: [] for i in range(len(ob))}, "feat_agg": {k: {r[0]: [] for r in c["ranges"]} for k, c in fc.items()}}


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
        hits = sum(x[3] for x in s)
        label = "{:.3f}-{:.3f}".format(lo, hi) if kind == "prob" else ("{}-{}".format(lo, hi) if hi < 999999 else "{}+".format(lo))
        rows.append({"range": label, "count": n, "avg_prob": avg_prob, "avg_odds": avg_odds, "expected_profit_pct": avg_ev * 100, "actual_hits": hits, "actual_attempts": n, "actual_rate": (hits / n) if n else None})
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


def _scope_summary(bucket):
    prob_s = bucket["prob_samples"]
    odds_s = bucket["odds_samples"]
    total = 0
    hits = 0
    ev_sum = 0.0
    for i in range(len(prob_s)):
        for s in prob_s[i]:
            total += 1
            hits += s[3]
            ev_sum += s[2]
    avg_ev = (ev_sum / total) if total else 0.0
    return {"count": total, "hits": hits, "actual_rate": (hits / total) if total else None, "avg_expected_profit_pct": avg_ev * 100}


@router.get("")
def get_analytics():
    pb = _prob_bins()
    ob = _odds_bins()
    fc = _features_conf()
    scopes = {"all": _empty_bucket(), "voted": _empty_bucket(), "excluded": _empty_bucket()}
    bets_data = bet_store.list_bets()
    voted_keys = set((b["race_id"], b["combo"]) for b in bets_data)
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
            sample = (tri.prob, odds, ev, hit)
            key = (race.race_id, tri.combo)
            is_voted = key in voted_keys
            targets = ["all", "voted" if is_voted else "excluded"]
            for scope in targets:
                b = scopes[scope]
                for i, (lo, hi) in enumerate(pb):
                    if lo <= tri.prob < hi:
                        b["prob_samples"][i].append(sample)
                        break
                for i, (lo, hi) in enumerate(ob):
                    if lo <= odds < hi:
                        b["odds_samples"][i].append(sample)
                        break
                if len(parts) == 3:
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
                            for (label, lo, hi) in fc["popularity"]["ranges"]:
                                if pop is not None and lo <= pop <= hi:
                                    b["feat_agg"]["popularity"][label].append((tri.prob, odds, hit))
                            for (label, lo, hi) in fc["weight"]["ranges"]:
                                if w is not None and lo <= w < hi:
                                    b["feat_agg"]["weight"][label].append((tri.prob, odds, hit))
                            for (label, lo, hi) in fc["frame"]["ranges"]:
                                if fr is not None and lo <= fr <= hi:
                                    b["feat_agg"]["frame"][label].append((tri.prob, odds, hit))
                            for (label, lo, hi) in fc["odds_win"]["ranges"]:
                                if ow is not None and lo <= ow < hi:
                                    b["feat_agg"]["odds_win"][label].append((tri.prob, odds, hit))
    scopes_out = {}
    for name, b in scopes.items():
        scopes_out[name] = {"summary": _scope_summary(b), "prob_bins": _format(pb, b["prob_samples"], "prob"), "odds_bins": _format(ob, b["odds_samples"], "odds"), "features": _format_features(fc, b["feat_agg"])}
    return {"by_ticket": [{"ticket": "3連単", "scopes": scopes_out}], "prob_bins": scopes_out["all"]["prob_bins"], "odds_bins": scopes_out["all"]["odds_bins"], "features": scopes_out["all"]["features"]}
