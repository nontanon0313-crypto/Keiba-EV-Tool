"""analytics_cache 生成。3スコープ + 累積表対応。"""
import os
import json
import time
from pathlib import Path
from datetime import datetime

from backend.app.services import race_store, odds_store
from backend.app.services.prediction import predict_race
from backend.app.services.ev_calc import calc_ev, _candidates, TICKET_TYPES, _TICKET_LABEL
from backend.app.models.schemas import Race, Runner
from backend.config import settings

CACHE_FILE = Path("analytics_cache.json")


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
    return Race(race_id=rid, venue="中山", date="20240101", race_number=1,
                start_at=datetime.now(), deadline_at=datetime.now(),
                surface=surf, distance=payload.get("distance") or 1600, runners=runners)


def real_odds(payload, ticket, combo):
    t = payload.get(ticket) or {}
    e = t.get(combo)
    if not e:
        return None
    if ticket == "wide":
        return e.get("max") or e.get("min")
    return e.get("odds")


def hit_check(ticket, combo, finish):
    if len(finish) < 3:
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


def _prob_bins():
    bins = []
    for i in range(50): bins.append((i * 0.001, (i + 1) * 0.001))
    for i in range(10): bins.append((0.050 + i * 0.005, 0.050 + (i + 1) * 0.005))
    for i in range(10): bins.append((0.100 + i * 0.010, 0.100 + (i + 1) * 0.010))
    for i in range(6): bins.append((0.200 + i * 0.050, 0.200 + (i + 1) * 0.050))
    return bins


def _odds_bins():
    bins = []
    for i in range(200): bins.append((1 + i, 2 + i))
    for i in range(16): bins.append((200 + i * 50, 200 + (i + 1) * 50))
    bins.append((1000, 999999))
    return bins


def _ev_bins():
    return [(-1.0, 0.0), (0.0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20),
            (0.20, 0.30), (0.30, 0.50), (0.50, 1.0), (1.0, 5.0), (5.0, 99999.0)]


def _features_conf():
    return {
        "popularity": {"label": "1着予想馬の人気", "ranges": [("1",1,1),("2",2,2),("3",3,3),("4-6",4,6),("7-9",7,9),("10+",10,99)]},
        "weight": {"label": "1着予想馬の斤量", "ranges": [("-53",0,53),("53-55",53,55),("55-57",55,57),("57+",57,99)]},
        "frame": {"label": "1着予想馬の枠番", "ranges": [("1-2",1,2),("3-4",3,4),("5-6",5,6),("7-8",7,8)]},
        "odds_win": {"label": "1着予想馬の単勝", "ranges": [("-5",0,5),("5-10",5,10),("10-20",10,20),("20-50",20,50),("50+",50,99999)]},
    }


def compute_plan_set(race, pred, odds_payload):
    tickets = list(settings.MIXED_TICKETS)
    ev_min = settings.MIXED_EV_MIN
    odds_min = settings.MIXED_ODDS_MIN
    top_n = settings.MIXED_TOP_N
    cands = []
    for t in tickets:
        for combo, prob in _candidates(pred, t):
            ro = real_odds(odds_payload, t, combo)
            if not ro or ro <= 1:
                continue
            if ro < odds_min:
                continue
            ev = calc_ev(prob, ro)
            if ev < ev_min:
                continue
            cands.append((ev, t, combo))
    cands.sort(key=lambda x: x[0], reverse=True)
    return set((t, c) for _, t, c in cands[:top_n])


def fmt_band_rows(bins, samples, kind):
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


def fmt_cumulative(samples, thresholds, kind):
    rows = []
    for th in thresholds:
        if kind == "prob":
            s = [x for x in samples if x[0] >= th]
            label = "≥{:.3f}".format(th)
        elif kind == "odds":
            s = [x for x in samples if x[1] >= th]
            label = "≥{}".format(th)
        elif kind == "ev":
            s = [x for x in samples if x[2] >= th]
            label = "≥{:.2f}".format(th)
        else:
            continue
        if not s:
            continue
        n = len(s)
        avg_prob = sum(x[0] for x in s) / n
        avg_odds = sum(x[1] for x in s) / n
        avg_ev = sum(x[2] for x in s) / n
        hits = sum(x[3] for x in s)
        rows.append({
            "range": label, "count": n,
            "avg_prob": avg_prob, "avg_odds": avg_odds, "avg_ev": avg_ev,
            "expected_profit_pct": avg_ev * 100,
            "actual_hits": hits, "actual_attempts": n,
            "actual_rate": (hits / n) if n else None,
            "actual_profit_pct": (hits * avg_odds / n - 1) * 100 if n else None,
        })
    return rows


def fmt_features(features, agg):
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


def _save_to_turso(result):
    import libsql_client
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not url or not token:
        raise RuntimeError("TURSO_URL/TURSO_TOKEN not set")
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    client = libsql_client.create_client_sync(url=http_url, auth_token=token)
    client.execute(
        "CREATE TABLE IF NOT EXISTS analytics_cache ("
        "id INTEGER PRIMARY KEY,"
        "payload TEXT NOT NULL,"
        "updated_at TEXT NOT NULL)"
    )
    payload = json.dumps(result, ensure_ascii=False)
    client.execute(
        "INSERT INTO analytics_cache (id, payload, updated_at) VALUES (1, ?, ?) "
        "ON CONFLICT (id) DO UPDATE SET payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at",
        [payload, datetime.now().isoformat()],
    )
    try:
        client.close()
    except Exception:
        pass


def build():
    t0 = time.time()
    print("[build] start", flush=True)
    tickets = list(TICKET_TYPES)
    pb = _prob_bins()
    ob = _odds_bins()
    eb = _ev_bins()
    fc = _features_conf()

    prob_th = [0.0, 0.005, 0.01, 0.015, 0.02, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20]
    odds_th = [0, 10, 20, 30, 50, 80, 100, 150, 200, 300, 500]
    ev_th = [-1.0, 0.0, 0.2, 0.5, 1.0, 2.0, 5.0]

    scopes_samples = {"all": [], "plan": [], "non_plan": []}
    feat_agg = {k: {r[0]: [] for r in c["ranges"]} for k, c in fc.items()}

    races = race_store.list_races()
    print("[build] races:", len(races), flush=True)

    # バッチで全オッズを一括取得（100件ずつ）
    rids = [it["race_id"] for it in races]
    odds_map = odds_store.get_odds_batch(rids)
    print("[build] odds fetched:", len(odds_map), flush=True)

    def get_odds_for(rid):
        return odds_map.get(rid) or {}

    for i, it in enumerate(races):
        rid = it["race_id"]
        payload = it.get("payload") or {}
        finish = payload.get("finish_order") or []
        if len(finish) < 3:
            continue
        odds_p = get_odds_for(rid)
        race = race_obj(rid, payload)
        try:
            pred = predict_race(race)
        except Exception:
            continue
        plan_set = compute_plan_set(race, pred, odds_p)
        runner_map = {r.horse_number: r for r in race.runners}
        for t in tickets:
            for combo, prob in _candidates(pred, t):
                if prob <= 0:
                    continue
                ro = real_odds(odds_p, t, combo)
                if not ro or ro <= 1:
                    continue
                ev = calc_ev(prob, ro)
                hit = hit_check(t, combo, finish)
                sample = (prob, ro, ev, hit)
                scopes_samples["all"].append(sample)
                # フィルタ通過候補のみがplan/non_plan対象
                passes_filter = (ro >= settings.MIXED_ODDS_MIN) and (ev >= settings.MIXED_EV_MIN) and (t in settings.MIXED_TICKETS)
                if passes_filter:
                    if (t, combo) in plan_set:
                        scopes_samples["plan"].append(sample)
                    else:
                        scopes_samples["non_plan"].append(sample)
                # features は all のみ
                parts = combo.split("-")
                try:
                    first_num = int(parts[0])
                except (ValueError, IndexError):
                    first_num = None
                if first_num is not None:
                    r = runner_map.get(first_num)
                    if r is not None:
                        pop = getattr(r, "popularity", None)
                        wt = getattr(r, "weight", None)
                        fr = getattr(r, "frame_number", None)
                        ow = getattr(r, "odds_win", None)
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
        if (i + 1) % 200 == 0:
            print("[build] {}/{} {:.1f}s".format(i + 1, len(races), time.time() - t0), flush=True)

    scopes_out = {}
    for scope_name, samples in scopes_samples.items():
        # bins
        prob_s = {i: [] for i in range(len(pb))}
        odds_s = {i: [] for i in range(len(ob))}
        ev_s = {i: [] for i in range(len(eb))}
        for smp in samples:
            for i, (lo, hi) in enumerate(pb):
                if lo <= smp[0] < hi:
                    prob_s[i].append(smp)
                    break
            for i, (lo, hi) in enumerate(ob):
                if lo <= smp[1] < hi:
                    odds_s[i].append(smp)
                    break
            for i, (lo, hi) in enumerate(eb):
                if lo <= smp[2] < hi:
                    ev_s[i].append(smp)
                    break
        total = len(samples)
        hits = sum(smp[3] for smp in samples)
        features_out = fmt_features(fc, feat_agg) if scope_name == "all" else []
        scopes_out[scope_name] = {
            "summary": {
                "total_count": total,
                "total_hits": hits,
                "hit_rate": (hits / total) if total else 0.0,
            },
            "prob_bins": fmt_band_rows(pb, prob_s, "prob"),
            "prob_cum": fmt_cumulative(samples, prob_th, "prob"),
            "odds_bins": fmt_band_rows(ob, odds_s, "odds"),
            "odds_cum": fmt_cumulative(samples, odds_th, "odds"),
            "ev_bins": fmt_band_rows(eb, ev_s, "ev"),
            "ev_cum": fmt_cumulative(samples, ev_th, "ev"),
            "features": features_out,
        }

    result = {
        "scopes": scopes_out,
        "meta": {"races": len(races)},
        "generated_at": datetime.now().isoformat(),
    }
    CACHE_FILE.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    try:
        _save_to_turso(result)
        print("[build] saved turso", flush=True)
    except Exception as e:
        print("[build] turso fail:", e, flush=True)
    print("[build] done {:.1f}s".format(time.time() - t0), flush=True)
    os._exit(0)


if __name__ == "__main__":
    build()
