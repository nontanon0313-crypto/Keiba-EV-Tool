"""analytics_cache 生成（メモリ節約型・ストリーミング集計）。
計算式（全て %数値で返す。フロントは表示のみ）:
  予想的中率% = Σ確率 / N × 100
  想定利益%   = (Σ(確率×オッズ) / N − 1) × 100
  実的中率%   = 的中数 / N × 100
  実利益%     = (Σ的中払戻円 / (N×100) − 1) × 100
"""
import os
import json
import math
import time
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from backend.constants import (
    STAKE_PER_BET, HITS_PER_RACE, THEORY_DEDUCTION_PCT, ODDS_DISPLAY_MAX,
    prob_bins as _prob_bins_const, odds_bins as _odds_bins_const,
    ev_bins as _ev_bins_const,
    PROB_THRESHOLDS, ODDS_THRESHOLDS, EV_THRESHOLDS,
    EXCLUDED_TRACK_CODES,
)
from backend.app.services import race_store, odds_store
from backend.app.services.prediction import predict_race
from backend.app.services.ev_calc import calc_ev, _candidates, TICKET_TYPES, _TICKET_LABEL
from backend.app.models.schemas import Race, Runner
from backend.config import settings
from backend.scraper.oddspark_keiba import extract_payouts

CACHE_FILE = Path("analytics_cache.json")
SCOPES = ("all_combos", "all", "plan", "non_plan")


def race_obj(rid, payload):
    runners = []
    for r in payload.get("runners", []):
        runners.append(Runner(
            horse_number=r.get("horse_number", 0),
            frame_number=r.get("frame_number", 0),
            horse_id="", horse_name="", jockey="", trainer="",
            weight=r.get("weight", 55.0) or 55.0,
            odds_win=r.get("odds_win"),
            popularity=r.get("popularity"),
        ))
    surf = payload.get("surface") or "ダート"
    if surf not in ("芝", "ダート", "障害"):
        surf = "ダート"
    return Race(
        race_id=rid, venue=payload.get("venue", ""), date=payload.get("date", ""),
        race_number=int(payload.get("race_number", 0) or 0),
        start_at=datetime.now(), deadline_at=datetime.now(),
        surface=surf, distance=payload.get("distance") or 1600, runners=runners,
    )


def real_odds(odds_payload, ticket, combo):
    from backend.app.services.ev_calc import is_bettable_odds
    t = odds_payload.get(ticket) or {}
    e = t.get(combo)
    if not e:
        return None
    if ticket == "wide":
        v = e.get("min")
    else:
        v = e.get("odds")
    if v is None:
        return None
    fv = float(v)
    if not is_bettable_odds(fv):
        return None
    return fv


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


def payout_yen(payouts_dict, ticket_jp, combo):
    m = payouts_dict.get(ticket_jp) or {}
    if ticket_jp in ("馬連", "ワイド", "3連複", "枠連"):
        parts = combo.split("-")
        try:
            combo = "-".join(sorted(parts, key=lambda x: int(x)))
        except ValueError:
            pass
    return m.get(combo)


class Agg:
    """ストリーミング集計。サンプルは保持しない。"""
    def __init__(self):
        self.n = 0
        self.hits = 0
        self.sum_prob = 0.0
        self.sum_odds = 0.0
        self.sum_prob_odds = 0.0
        self.sum_payout_yen = 0.0
        self.sum_profit = 0.0
        self.sum_profit_sq = 0.0

    def add(self, prob, odds, hit, payout_yen=0):
        self.n += 1
        self.hits += hit
        self.sum_prob += prob
        self.sum_odds += odds
        self.sum_prob_odds += prob * odds
        profit = payout_yen / STAKE_PER_BET - 1.0
        self.sum_profit += profit
        self.sum_profit_sq += profit * profit
        if hit:
            self.sum_payout_yen += payout_yen

    def row(self, label):
        n = self.n
        if n == 0:
            return None
        mean_profit = self.sum_profit / n
        var_profit = self.sum_profit_sq / n - mean_profit * mean_profit
        var_profit = max(var_profit, 0.0)
        se_profit = math.sqrt(var_profit / n) if n > 0 else 0.0
        roi_ci_lo_pct = (mean_profit - 1.96 * se_profit) * 100
        roi_ci_hi_pct = (mean_profit + 1.96 * se_profit) * 100
        p_hat = self.hits / n
        se_p = math.sqrt(p_hat * (1 - p_hat) / n) if n > 0 else 0.0
        hr_ci_lo_pct = (p_hat - 1.96 * se_p) * 100
        hr_ci_hi_pct = (p_hat + 1.96 * se_p) * 100
        return {
            "range": label,
            "count": n,
            "avg_prob": self.sum_prob / n,
            "avg_odds": self.sum_odds / n,
            "expected_hit_rate_pct": (self.sum_prob / n) * 100,
            "expected_profit_pct": (self.sum_prob_odds / n - 1) * 100,
            "actual_hits": self.hits,
            "actual_attempts": n,
            "actual_hit_rate_pct": p_hat * 100,
            "actual_hit_rate_ci_lo_pct": hr_ci_lo_pct,
            "actual_hit_rate_ci_hi_pct": hr_ci_hi_pct,
            "actual_profit_pct": mean_profit * 100,
            "actual_profit_ci_lo_pct": roi_ci_lo_pct,
            "actual_profit_ci_hi_pct": roi_ci_hi_pct,
        }


def _features_conf():
    return {
        "popularity": {"label": "人気", "ranges": [("1",1,1),("2",2,2),("3",3,3),("4-6",4,6),("7-9",7,9),("10+",10,99)]},
        "weight": {"label": "斤量", "ranges": [("-53",0,53),("53-55",53,55),("55-57",55,57),("57+",57,99)]},
        "frame": {"label": "枠番", "ranges": [("1-2",1,2),("3-4",3,4),("5-6",5,6),("7-8",7,8)]},
        "odds_win": {"label": "単勝オッズ", "ranges": [("-5",0,5),("5-10",5,10),("10-20",10,20),("20-50",20,50),("50+",50,99999)]},
        "age_sex": {"label": "性齢", "ranges": [("牡",0,0),("牝",1,1),("セ",2,2)]},
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
    pb = _prob_bins_const()
    ob = _odds_bins_const()
    eb = _ev_bins_const()
    fc = _features_conf()
    prob_th = PROB_THRESHOLDS
    odds_th = ODDS_THRESHOLDS
    ev_th = EV_THRESHOLDS

    # scope集計: scope -> {"total": Agg, "prob_bins": [Agg,...], "odds_bins": [...], "ev_bins": [...],
    #                      "prob_cum": [Agg,...], "odds_cum": [...], "ev_cum": [...],
    #                      "features": {key: {label: Agg}}}
    def new_scope():
        return {
            "total": Agg(),
            "prob_bins": [Agg() for _ in pb],
            "odds_bins": [Agg() for _ in ob],
            "ev_bins": [Agg() for _ in eb],
            "prob_cum": [Agg() for _ in prob_th],
            "odds_cum": [Agg() for _ in odds_th],
            "ev_cum": [Agg() for _ in ev_th],
            "features": {k: {r[0]: Agg() for r in c["ranges"]} for k, c in fc.items()},
        }

    scopes_data = {s: new_scope() for s in SCOPES}
    ticket_agg = defaultdict(lambda: {"count": 0, "hits": 0, "prob_sum": 0.0,
                                      "odds_sum": 0.0, "prob_odds_sum": 0.0,
                                      "sum_inv_odds": 0.0,
                                      "stake": 0, "payout": 0,
                                      "sum_profit": 0.0, "sum_profit_sq": 0.0})
    RACE_COUNT = 0

    races = race_store.list_races()
    print("[build] races:", len(races), flush=True)
    rids = [it["race_id"] for it in races]
    odds_map = odds_store.get_odds_batch(rids)
    print("[build] odds fetched:", len(odds_map), flush=True)

    def add_to_scope(scope, prob, odds, hit, payout_yen):
        scope["total"].add(prob, odds, hit, payout_yen)
        for j, (lo, hi) in enumerate(pb):
            if lo <= prob < hi:
                scope["prob_bins"][j].add(prob, odds, hit, payout_yen); break
        for j, (lo, hi) in enumerate(ob):
            if lo <= odds < hi:
                scope["odds_bins"][j].add(prob, odds, hit, payout_yen); break
        ev = prob * odds - 1.0
        for j, (lo, hi) in enumerate(eb):
            if lo <= ev < hi:
                scope["ev_bins"][j].add(prob, odds, hit, payout_yen); break
        for j, th in enumerate(prob_th):
            if prob >= th:
                scope["prob_cum"][j].add(prob, odds, hit, payout_yen)
        for j, th in enumerate(odds_th):
            if odds >= th:
                scope["odds_cum"][j].add(prob, odds, hit, payout_yen)
        for j, th in enumerate(ev_th):
            if ev >= th:
                scope["ev_cum"][j].add(prob, odds, hit, payout_yen)

    for i, it in enumerate(races):
        rid = it["race_id"]
        parts_rid = rid.split("-")
        if len(parts_rid) >= 3 and parts_rid[2] in EXCLUDED_TRACK_CODES:
            continue
        payload = it.get("payload") or {}
        finish = payload.get("finish_order") or []
        if len(finish) < 3:
            continue
        odds_p = odds_map.get(rid) or {}
        payouts_dict = extract_payouts(payload.get("payouts") or {})
        race = race_obj(rid, payload)
        try:
            pred = predict_race(race)
        except Exception:
            continue
        plan_set = compute_plan_set(race, pred, odds_p)
        runner_map = {r.horse_number: r for r in race.runners}
        raw_runner_map = {r0.get("horse_number"): r0 for r0 in payload.get("runners", [])}
        result_runner_map = {r0.get("horse_number"): r0 for r0 in payload.get("result_runners", [])}
        RACE_COUNT += 1

        for t in tickets:
            for combo, prob in _candidates(pred, t):
                if prob <= 0:
                    continue
                ro = real_odds(odds_p, t, combo)
                if not ro or ro <= 1:
                    continue
                hit = hit_check(t, combo, finish)
                ticket_jp = _TICKET_LABEL.get(t, t)
                payout = payout_yen(payouts_dict, ticket_jp, combo) or 0

                # 全組み合わせ
                add_to_scope(scopes_data["all_combos"], prob, ro, hit, payout)

                # 券種別
                ta = ticket_agg[t]
                ta["count"] += 1
                ta["hits"] += hit
                ta["prob_sum"] += prob
                ta["odds_sum"] += ro
                ta["prob_odds_sum"] += prob * ro
                ta["sum_inv_odds"] += 1.0 / ro
                ta["stake"] += 100
                profit = payout / STAKE_PER_BET - 1.0
                ta["sum_profit"] += profit
                ta["sum_profit_sq"] += profit * profit
                if hit:
                    ta["payout"] += payout

                # フィルタ判定
                ev = prob * ro - 1.0
                passes_filter = (ro >= settings.MIXED_ODDS_MIN) and (ev >= settings.MIXED_EV_MIN) and (t in settings.MIXED_TICKETS)
                if passes_filter:
                    add_to_scope(scopes_data["all"], prob, ro, hit, payout)
                    if (t, combo) in plan_set:
                        add_to_scope(scopes_data["plan"], prob, ro, hit, payout)
                    else:
                        add_to_scope(scopes_data["non_plan"], prob, ro, hit, payout)

                # features（all_combos のみ。メモリ節約のため）
                parts = combo.split("-")
                try:
                    first_num = int(parts[0])
                except (ValueError, IndexError):
                    first_num = None
                if first_num is not None:
                    r = runner_map.get(first_num)
                    raw_r = raw_runner_map.get(first_num) or {}
                    if r is not None:
                        pop = getattr(r, "popularity", None)
                        wt = getattr(r, "weight", None)
                        fr = getattr(r, "frame_number", None)
                        ow = getattr(r, "odds_win", None)
                        age_sex = (raw_r.get("age_sex")
                                   or (result_runner_map.get(first_num) or {}).get("age_sex")
                                   or "")
                        fagg = scopes_data["all_combos"]["features"]
                        if pop is not None:
                            for (label, lo, hi) in fc["popularity"]["ranges"]:
                                if lo <= pop <= hi:
                                    fagg["popularity"][label].add(prob, ro, hit, payout)
                        if wt is not None:
                            for (label, lo, hi) in fc["weight"]["ranges"]:
                                if lo <= wt < hi:
                                    fagg["weight"][label].add(prob, ro, hit, payout)
                        if fr is not None:
                            for (label, lo, hi) in fc["frame"]["ranges"]:
                                if lo <= fr <= hi:
                                    fagg["frame"][label].add(prob, ro, hit, payout)
                        if ow is not None:
                            for (label, lo, hi) in fc["odds_win"]["ranges"]:
                                if lo <= ow < hi:
                                    fagg["odds_win"][label].add(prob, ro, hit, payout)
                        if age_sex:
                            a = age_sex[0] if age_sex else ""
                            if a in ("牡", "牝", "セ"):
                                fagg["age_sex"][a].add(prob, ro, hit, payout)

        if (i + 1) % 200 == 0:
            print("[build] {}/{} {:.1f}s".format(i + 1, len(races), time.time() - t0), flush=True)

    def features_out(scope):
        out = []
        for key, conf in fc.items():
            rows = []
            for (label, lo, hi) in conf["ranges"]:
                agg = scope["features"].get(key, {}).get(label)
                if agg is None or agg.n == 0:
                    continue
                row = agg.row(label)
                if row:
                    rows.append(row)
            out.append({"feature": key, "label": conf["label"], "rows": rows})
        return out

    def band_out(scope, bins, key, kind):
        rows = []
        for j, (lo, hi) in enumerate(bins):
            agg = scope[key][j]
            if agg.n == 0:
                continue
            if kind == "prob":
                label = "{:.3f}-{:.3f}".format(lo, hi)
            elif kind == "odds":
                label = "{}-{}".format(lo, hi) if hi < 999999 else "{}+".format(lo)
            else:
                label = "{:.2f}-{:.2f}".format(lo, hi) if hi < 99999 else "{:.2f}+".format(lo)
            row = agg.row(label)
            if row:
                rows.append(row)
        return rows

    def cum_out(scope, thresholds, key, kind):
        rows = []
        for j, th in enumerate(thresholds):
            agg = scope[key][j]
            if agg.n == 0:
                continue
            if kind == "prob":
                label = "≥{:.3f}".format(th)
            elif kind == "odds":
                label = "≥{}".format(th)
            else:
                label = "≥{:.2f}".format(th)
            row = agg.row(label)
            if row:
                rows.append(row)
        return rows

    scopes_out = {}
    for s in SCOPES:
        scope = scopes_data[s]
        scopes_out[s] = {
            "summary": {
                "total_count": scope["total"].n,
                "total_hits": scope["total"].hits,
                "hit_rate_pct": (scope["total"].hits / scope["total"].n * 100) if scope["total"].n else 0.0,
            },
            "prob_bins": band_out(scope, pb, "prob_bins", "prob"),
            "prob_cum": cum_out(scope, prob_th, "prob_cum", "prob"),
            "odds_bins": band_out(scope, ob, "odds_bins", "odds"),
            "odds_cum": cum_out(scope, odds_th, "odds_cum", "odds"),
            "ev_bins": band_out(scope, eb, "ev_bins", "ev"),
            "ev_cum": cum_out(scope, ev_th, "ev_cum", "ev"),
            "features": features_out(scope),
        }

    ticket_stats = []
    for t in tickets:
        ta = ticket_agg[t]
        if ta["count"] == 0:
            continue
        avg_inv = ta["sum_inv_odds"] / RACE_COUNT if RACE_COUNT else 0
        hpr = HITS_PER_RACE.get(t, 1)
        measured_deduction = (1 - hpr / avg_inv) * 100 if avg_inv > 0 else None
        n = ta["count"]
        mean_profit = ta["sum_profit"] / n
        var_profit = ta["sum_profit_sq"] / n - mean_profit * mean_profit
        var_profit = max(var_profit, 0.0)
        se_profit = math.sqrt(var_profit / n) if n > 0 else 0.0
        roi_ci_lo = (mean_profit - 1.96 * se_profit) * 100
        roi_ci_hi = (mean_profit + 1.96 * se_profit) * 100
        p_hat = ta["hits"] / n
        se_p = math.sqrt(p_hat * (1 - p_hat) / n) if n > 0 else 0.0
        hr_ci_lo = (p_hat - 1.96 * se_p) * 100
        hr_ci_hi = (p_hat + 1.96 * se_p) * 100
        ticket_stats.append({
            "ticket": t,
            "label": _TICKET_LABEL.get(t, t),
            "count": n,
            "hits": ta["hits"],
            "expected_hit_rate_pct": (ta["prob_sum"] / n) * 100,
            "avg_odds": ta["odds_sum"] / n,
            "actual_hit_rate_pct": p_hat * 100,
            "actual_hit_rate_ci_lo_pct": hr_ci_lo,
            "actual_hit_rate_ci_hi_pct": hr_ci_hi,
            "expected_profit_pct": (ta["prob_odds_sum"] / n - 1) * 100,
            "actual_profit_pct": mean_profit * 100,
            "actual_profit_ci_lo_pct": roi_ci_lo,
            "actual_profit_ci_hi_pct": roi_ci_hi,
            "measured_deduction_pct": measured_deduction,
            "theory_deduction_pct": THEORY_DEDUCTION_PCT.get(t),
        })

    result = {
        "scopes": scopes_out,
        "ticket_stats": ticket_stats,
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
