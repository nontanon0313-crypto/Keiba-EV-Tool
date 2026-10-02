"""2特徴の交互作用を網羅的に調査。

features を読み込み、全ペアの3×3分位セルで
「実的中率 − 市場期待的中率」「ROI」を集計する。
n>=300 かつ ROI>0 のセルを抽出し、結果を Turso に保存。

使い方:
    python3 -m backend.scripts.build_feature_interactions
"""
import os
import json
import time
from datetime import datetime
from itertools import combinations

import libsql_client

LOG_PATH = "feature_interactions.log"
MIN_CELL_N = 300

NUMERIC_FEATURES = [
    "win_rate", "place_rate", "show_rate", "avg_finish",
    "avg_agari_3f", "best_agari_3f", "recent5_avg_finish",
    "recent3_avg_finish", "recent1_finish", "recent1_pop",
    "recent5_avg_agari", "days_since_last",
    "same_dist_place_rate", "same_dist_avg_finish",
    "same_cond_place_rate", "same_venue_place_rate",
    "same_surface_place_rate", "class_change",
    "horse_weight_trend", "avg_corner_ratio",
    "weight", "popularity", "horse_weight",
    "avg_time_norm", "best_time_norm",
    "n_starts", "n_wins", "recent5_avg_pop",
]


def _log(msg):
    line = "[" + datetime.now().strftime("%H:%M:%S") + "] " + msg
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _to_num(v):
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _tercile_bounds(values):
    vs = sorted([v for v in values if v is not None])
    if len(vs) < 30:
        return None
    return [vs[int(len(vs) / 3)], vs[int(len(vs) * 2 / 3)]]


def _tercile(x, bounds):
    if x is None or bounds is None:
        return None
    if x <= bounds[0]:
        return 0
    if x <= bounds[1]:
        return 1
    return 2


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not url or not token:
        _log("TURSO_URL/TURSO_TOKEN not set")
        return
    h = url.replace("libsql://", "https://").replace("wss://", "https://")
    c = libsql_client.create_client_sync(url=h, auth_token=token)

    # result_map 構築（分割読み込み）
    _log("loading races")
    result_map = {}
    last_rid = ""
    while True:
        r = c.execute(
            "SELECT race_id, payload FROM scraped_races WHERE race_id > ? ORDER BY race_id LIMIT 500",
            [last_rid],
        )
        rows = list(r.rows)
        if not rows:
            break
        for row in rows:
            try:
                d = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except Exception:
                continue
            per = {}
            for x in (d.get("result_runners") or []):
                num = x.get("horse_number")
                fin = x.get("finish")
                if num:
                    per[int(num)] = fin
            result_map[row[0]] = per
        last_rid = rows[-1][0]
        if len(rows) < 500:
            break
    _log("races loaded: " + str(len(result_map)))

    # features 読み込み
    _log("loading features")
    samples = []
    rids_all = list(result_map.keys())
    CHUNK = 200
    for i in range(0, len(rids_all), CHUNK):
        chunk = rids_all[i:i+CHUNK]
        ph = ",".join(["?"] * len(chunk))
        r2 = c.execute(
            "SELECT race_id, horse_number, features_json FROM features WHERE race_id IN (" + ph + ")",
            chunk,
        )
        for row in r2.rows:
            try:
                f = json.loads(row[2])
            except Exception:
                continue
            rid = row[0]
            num = int(row[1])
            finish = (result_map.get(rid) or {}).get(num)
            if finish is None:
                continue
            odds = _to_num(f.get("odds_win"))
            samples.append({
                "race_id": rid, "num": num, "finish": finish,
                "odds": odds, "features": f,
            })
    _log("samples: " + str(len(samples)))

    # 市場確率を正規化
    per_race_sum = {}
    for s in samples:
        if s["odds"] and s["odds"] > 0:
            per_race_sum[s["race_id"]] = per_race_sum.get(s["race_id"], 0) + (1.0 / s["odds"])
    for s in samples:
        if s["odds"] and s["odds"] > 0:
            tot = per_race_sum.get(s["race_id"], 0)
            s["market_p"] = (1.0 / s["odds"]) / tot if tot > 0 else None
        else:
            s["market_p"] = None

    # 各特徴の分位境界と分位値を事前計算
    t0 = time.time()
    feature_data = {}
    for name in NUMERIC_FEATURES:
        vals = [_to_num(s["features"].get(name)) for s in samples]
        bounds = _tercile_bounds(vals)
        if bounds is None:
            continue
        feature_data[name] = bounds
    _log("features to analyze: " + str(len(feature_data)))

    results = []
    pairs = list(combinations(feature_data.keys(), 2))
    _log("pairs: " + str(len(pairs)))

    for pi, (fa, fb) in enumerate(pairs):
        ba = feature_data[fa]
        bb = feature_data[fb]
        buckets = {}
        for s in samples:
            va = _tercile(_to_num(s["features"].get(fa)), ba)
            vb = _tercile(_to_num(s["features"].get(fb)), bb)
            if va is None or vb is None:
                continue
            key = (va, vb)
            if key not in buckets:
                buckets[key] = {"n": 0, "wins": 0, "top3": 0, "market_p_sum": 0.0, "market_p_n": 0, "payout": 0.0, "cost": 0}
            b = buckets[key]
            b["n"] += 1
            if s["finish"] == 1:
                b["wins"] += 1
            if s["finish"] and s["finish"] <= 3:
                b["top3"] += 1
            if s["market_p"] is not None and s["odds"] and s["odds"] > 0:
                b["market_p_sum"] += s["market_p"]
                b["market_p_n"] += 1
                b["cost"] += 100
                if s["finish"] == 1:
                    b["payout"] += s["odds"] * 100
        for (va, vb), b in buckets.items():
            if b["n"] < MIN_CELL_N or b["market_p_n"] == 0:
                continue
            hit = b["wins"] / b["n"]
            market = b["market_p_sum"] / b["market_p_n"]
            diff = (hit - market) * 100
            # 二項CI（実的中率）
            se = (hit * (1 - hit) / b["n"]) ** 0.5
            hit_ci_lo = (hit - 1.96 * se) * 100
            hit_ci_hi = (hit + 1.96 * se) * 100
            # 市場との差のCI（差の標準誤差 = sqrt(p(1-p)/n) を市場側も同じnで近似）
            diff_se = se * 100
            diff_ci_lo = diff - 1.96 * diff_se
            diff_ci_hi = diff + 1.96 * diff_se
            sig = "有意" if diff_ci_lo > 0 else ("劣位" if diff_ci_hi < 0 else "-")
            roi = (b["payout"] / b["cost"] * 100 - 100) if b["cost"] > 0 else None
            results.append({
                "fa": fa, "fb": fb,
                "a_q": va, "b_q": vb,
                "n": b["n"],
                "wins": b["wins"],
                "hit_pct": round(hit * 100, 2),
                "hit_ci_lo": round(hit_ci_lo, 2),
                "hit_ci_hi": round(hit_ci_hi, 2),
                "market_pct": round(market * 100, 2),
                "diff_pct": round(diff, 2),
                "diff_ci_lo": round(diff_ci_lo, 2),
                "diff_ci_hi": round(diff_ci_hi, 2),
                "sig": sig,
                "top3_pct": round(b["top3"] / b["n"] * 100, 2),
                "roi_pct": round(roi, 1) if roi is not None else None,
            })
        if pi % 50 == 0:
            elapsed = time.time() - t0
            _log(f"  pairs={pi}/{len(pairs)} cells={len(results)} elapsed={elapsed:.0f}s")

    _log("total cells: " + str(len(results)))
    # 有望セル抽出: diff_pct>2 or roi_pct>0
    promising_diff = sorted([x for x in results if x["diff_pct"] > 2], key=lambda x: -x["diff_pct"])[:200]
    promising_roi = sorted([x for x in results if x["roi_pct"] is not None and x["roi_pct"] > 0], key=lambda x: -(x["roi_pct"] or 0))[:200]

    # 保存: 2テーブルに分ける。light=API用（小さく）、full=参照用（全セル）
    c.execute(
        "CREATE TABLE IF NOT EXISTS feature_interactions_cache ("
        "id INTEGER PRIMARY KEY, payload TEXT NOT NULL, generated_at TEXT NOT NULL)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS feature_interactions_full ("
        "id INTEGER PRIMARY KEY, payload TEXT NOT NULL, generated_at TEXT NOT NULL)"
    )
    now = datetime.now().isoformat()
    # light: API が読む方。promising 系のみ。
    light = {
        "samples": len(samples),
        "total_cells": len(results),
        "promising_diff": promising_diff,
        "promising_roi": promising_roi,
        "generated_at": now,
    }
    # full: 後から参照する用。全セル込み。
    full = {
        "samples": len(samples),
        "total_cells": len(results),
        "all_cells": results,
        "generated_at": now,
    }
    pj_light = json.dumps(light, ensure_ascii=False)
    pj_full = json.dumps(full, ensure_ascii=False)
    c.execute(
        "INSERT INTO feature_interactions_cache (id, payload, generated_at) VALUES (1, ?, ?) "
        "ON CONFLICT (id) DO UPDATE SET payload=EXCLUDED.payload, generated_at=EXCLUDED.generated_at",
        [pj_light, now],
    )
    c.execute(
        "INSERT INTO feature_interactions_full (id, payload, generated_at) VALUES (1, ?, ?) "
        "ON CONFLICT (id) DO UPDATE SET payload=EXCLUDED.payload, generated_at=EXCLUDED.generated_at",
        [pj_full, now],
    )
    _log("DONE cells=" + str(len(results)) + " promising_diff=" + str(len(promising_diff)) + " promising_roi=" + str(len(promising_roi)))
    try:
        c.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
import os as _o
_o._exit(0)
