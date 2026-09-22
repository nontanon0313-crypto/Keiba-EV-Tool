"""検証: 過去レース・実オッズ・実結果から独立して集計。
予想ページ・収益ページの保存データは参照しない。
race_store (過去レース) + odds_store (実オッズ) + predict_race + 実結果 で完結。
"""
from fastapi import APIRouter
from datetime import datetime
from backend.app.services import race_store, odds_store
from backend.app.services.prediction import predict_race
from backend.app.services.ev_calc import calc_ev, _candidates, TICKET_TYPES, _TICKET_LABEL
from backend.app.models.schemas import Race, Runner

router = APIRouter(prefix="/analytics")


def _race_obj(rid, payload):
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
    return Race(race_id=rid, venue="中山", date="20240101", race_number=1,
                start_at=datetime.now(), deadline_at=datetime.now(),
                surface=surf, distance=payload.get("distance") or 1600, runners=runners)


def _real_odds(payload, ticket, combo):
    t = payload.get(ticket) or {}
    e = t.get(combo)
    if not e:
        return None
    if ticket == "wide":
        return e.get("max") or e.get("min")
    return e.get("odds")


def _hit(ticket, combo, finish):
    if len(finish) < 3:
        return 0
    try:
        nums = [int(x) for x in combo.split("-")]
    except ValueError:
        return 0
    w = list(finish[:3])
    if ticket == "trifecta":
        return 1 if nums == w else 0
    if ticket == "trio":
        return 1 if sorted(nums) == sorted(w) else 0
    if ticket == "exacta":
        return 1 if len(nums) == 2 and nums == w[:2] else 0
    if ticket == "quinella":
        return 1 if len(nums) == 2 and sorted(nums) == sorted(w[:2]) else 0
    if ticket == "wide":
        if len(nums) != 2:
            return 0
        s = sorted(nums)
        pairs = [sorted([w[0], w[1]]), sorted([w[0], w[2]]), sorted([w[1], w[2]])]
        return 1 if s in pairs else 0
    if ticket == "win":
        return 1 if len(nums) == 1 and nums[0] == w[0] else 0
    if ticket == "place":
        return 1 if len(nums) == 1 and nums[0] in w[:3] else 0
    return 0


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


def _ev_bins():
    return [(-1.0, 0.0), (0.0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20),
            (0.20, 0.30), (0.30, 0.50), (0.50, 1.0), (1.0, 5.0), (5.0, 99999.0)]


def _features_conf():
    return {
        "popularity": {"label": "1着予想馬の人気", "ranges": [("1", 1, 1), ("2", 2, 2), ("3", 3, 3), ("4-6", 4, 6), ("7-9", 7, 9), ("10+", 10, 99)]},
        "weight": {"label": "1着予想馬の斤量", "ranges": [("-53", 0, 53), ("53-55", 53, 55), ("55-57", 55, 57), ("57+", 57, 99)]},
        "frame": {"label": "1着予想馬の枠番", "ranges": [("1-2", 1, 2), ("3-4", 3, 4), ("5-6", 5, 6), ("7-8", 7, 8)]},
        "odds_win": {"label": "1着予想馬の単勝", "ranges": [("-5", 0, 5), ("5-10", 5, 10), ("10-20", 10, 20), ("20-50", 20, 50), ("50+", 50, 99999)]},
    }


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
        if kind == "prob":
            label = "{:.3f}-{:.3f}".format(lo, hi)
        elif kind == "odds":
            label = "{}-{}".format(lo, hi) if hi < 999999 else "{}+".format(lo)
        else:
            label = "{:.2f}-{:.2f}".format(lo, hi) if hi < 99999 else "{:.2f}+".format(lo)
        rows.append({
            "range": label, "count": n,
            "avg_prob": avg_prob, "avg_odds": avg_odds, "avg_ev": avg_ev,
            "expected_profit_pct": avg_ev * 100,
            "actual_hits": hits, "actual_attempts": n,
            "actual_rate": (hits / n) if n else None,
            "actual_profit_pct": (hits * avg_odds / n - 1) * 100 if n else None,
        })
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
            rows.append({
                "range": label, "count": n,
                "avg_prob": avg_prob, "avg_odds": avg_odds,
                "expected_profit_pct": (avg_prob * avg_odds - 1.0) * 100,
                "actual_hits": hits, "actual_attempts": n,
                "actual_rate": (hits / n) if n else None,
                "actual_profit_pct": (hits * avg_odds / n - 1) * 100 if n else None,
            })
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


def _scan(tickets):
    """過去レースを走査して券種別サンプルを収集。"""
    pb = _prob_bins()
    ob = _odds_bins()
    eb = _ev_bins()
    fc = _features_conf()
    prob_samples = {i: [] for i in range(len(pb))}
    odds_samples = {i: [] for i in range(len(ob))}
    ev_samples = {i: [] for i in range(len(eb))}
    feat_agg = {k: {r[0]: [] for r in c["ranges"]} for k, c in fc.items()}
    ticket_agg = {}
    for t in tickets:
        ticket_agg[t] = {"count": 0, "hits": 0, "stake": 0, "ret": 0, "prob_sum": 0.0, "ev_sum": 0.0, "races": 0}

    races = race_store.list_races()
    odds_all = {o["race_id"]: o.get("payload") for o in odds_store.list_odds()}
    for it in races:
        rid = it["race_id"]
        payload = it.get("payload") or {}
        finish = payload.get("finish_order") or []
        if len(finish) < 3:
            continue
        odds_p = odds_all.get(rid) or {}
        race = _race_obj(rid, payload)
        try:
            pred = predict_race(race)
        except Exception:
            continue
        runner_map = {r.horse_number: r for r in race.runners}
        w = list(finish[:3])
        for t in tickets:
            for combo, prob in _candidates(pred, t):
                if prob <= 0:
                    continue
                ro = _real_odds(odds_p, t, combo)
                if not ro or ro <= 1:
                    continue
                ev = calc_ev(prob, ro)
                hit = _hit(t, combo, finish)
                sample = (prob, ro, ev, hit)
                ta = ticket_agg[t]
                ta["count"] += 1
                ta["hits"] += hit
                ta["stake"] += 100
                ta["ret"] += int(100 * ro) if hit else 0
                ta["prob_sum"] += prob
                ta["ev_sum"] += ev
                if hit:
                    ta["races"] = ta["races"]
                for i, (lo, hi) in enumerate(pb):
                    if lo <= prob < hi:
                        prob_samples[i].append(sample)
                        break
                for i, (lo, hi) in enumerate(ob):
                    if lo <= ro < hi:
                        odds_samples[i].append(sample)
                        break
                for i, (lo, hi) in enumerate(eb):
                    if lo <= ev < hi:
                        ev_samples[i].append(sample)
                        break
                # 出走表項目
                parts = combo.split("-")
                try:
                    first_num = int(parts[0])
                except (ValueError, IndexError):
                    first_num = None
                if first_num is not None:
                    r = runner_map.get(first_num)
                    if r is not None:
                        pop = _get(r, "popularity")
                        wt = _get(r, "weight")
                        fr = _get(r, "frame_number")
                        ow = _get(r, "odds_win")
                        if pop is not None:
                            for (label, lo, hi) in fc["popularity"]["ranges"]:
                                if lo <= pop <= hi:
                                    feat_agg["popularity"][label].append((prob, ro, hit))
                        if wt is not None:
                            for (label, lo, hi) in fc["weight"]["ranges"]:
                                if lo <= wt < hi:
                                    feat_agg["weight"][label].append((prob, ro, hit))
                        if fr is not None:
                            for (label, lo, hi) in fc["frame"]["ranges"]:
                                if lo <= fr <= hi:
                                    feat_agg["frame"][label].append((prob, ro, hit))
                        if ow is not None:
                            for (label, lo, hi) in fc["odds_win"]["ranges"]:
                                if lo <= ow < hi:
                                    feat_agg["odds_win"][label].append((prob, ro, hit))
    # 各レース数を正しく再計算
    return prob_samples, odds_samples, ev_samples, feat_agg, ticket_agg


@router.get("")
def get_analytics():
    tickets = list(TICKET_TYPES)
    pb = _prob_bins()
    ob = _odds_bins()
    eb = _ev_bins()
    fc = _features_conf()
    prob_samples, odds_samples, ev_samples, feat_agg, ticket_agg = _scan(tickets)

    ticket_stats = []
    for t in tickets:
        ta = ticket_agg[t]
        n = ta["count"]
        stake = ta["stake"]
        ret = ta["ret"]
        ticket_stats.append({
            "ticket": t, "label": _TICKET_LABEL.get(t, t),
            "count": n, "hits": ta["hits"],
            "hit_rate": (ta["hits"] / n) if n else 0.0,
            "expected_hit_rate": (ta["prob_sum"] / n) if n else 0.0,
            "stake": stake, "ret": ret, "profit": ret - stake,
            "roi": ((ret - stake) / stake) if stake else 0.0,
            "expected_roi": (ta["ev_sum"] / n) if n else 0.0,
        })

    total_count = sum(ta["count"] for ta in ticket_agg.values())
    total_hits = sum(ta["hits"] for ta in ticket_agg.values())
    return {
        "prob_bins": _format(pb, prob_samples, "prob"),
        "odds_bins": _format(ob, odds_samples, "odds"),
        "ev_bins": _format(eb, ev_samples, "ev"),
        "features": _format_features(fc, feat_agg),
        "ticket_stats": ticket_stats,
        "summary": {
            "total_count": total_count,
            "total_hits": total_hits,
            "hit_rate": (total_hits / total_count) if total_count else 0.0,
            "races": len(race_store.list_races()),
        },
    }
