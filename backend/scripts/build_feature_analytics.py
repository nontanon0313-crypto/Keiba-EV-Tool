"""単一特徴量の市場比較検証。

features テーブルを読み込み、result_runners と突合して
各特徴量の分位ごとに「実1着率 vs 市場期待1着率」を集計する。
結果は feature_analytics_cache テーブルに保存。

使い方:
    python3 -m backend.scripts.build_feature_analytics
"""
import os
import json
import time
from datetime import datetime

import libsql_client

LOG_PATH = "feature_analytics.log"
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
    "n_starts", "n_wins",
    "recent5_avg_pop",
]
CATEGORICAL_FEATURES = ["age_sex", "style", "frame", "current_class", "jockey", "sire"]

NBINS = 10


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
        x = float(v)
        return x
    except (ValueError, TypeError):
        return None


def _quantile_bounds(values):
    vs = sorted([v for v in values if v is not None])
    if not vs:
        return []
    return [vs[max(0, min(len(vs) - 1, int(len(vs) * (i + 1) / NBINS) - 1))] for i in range(NBINS - 1)]


def _bin_index(x, bounds):
    if x is None:
        return None
    i = 0
    while i < len(bounds) and x > bounds[i]:
        i += 1
    return i


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not url or not token:
        _log("TURSO_URL/TURSO_TOKEN not set")
        return
    h = url.replace("libsql://", "https://").replace("wss://", "https://")
    c = libsql_client.create_client_sync(url=h, auth_token=token)

    # result_runners を race_id -> {horse_number: finish} に
    _log("loading races")
    result_map = {}
    # race_id を昇順でページングして分割読み込み
    last_rid = ""
    PAGE = 500
    while True:
        r = c.execute(
            "SELECT race_id, payload FROM scraped_races WHERE race_id > ? ORDER BY race_id LIMIT ?",
            [last_rid, PAGE],
        )
        rows = list(r.rows)
        if not rows:
            break
        for row in rows:
            try:
                d = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except Exception:
                continue
            rr = d.get("result_runners") or []
            per_race = {}
            for x in rr:
                num = x.get("horse_number")
                fin = x.get("finish")
                if num:
                    per_race[int(num)] = fin
            result_map[row[0]] = per_race
        last_rid = rows[-1][0]
        if len(rows) < PAGE:
            break
    _log("races loaded: " + str(len(result_map)))

    # features 読み込み（race_id を IN 句でチャンク化、複合キー漏れなし）
    _log("loading features")
    samples = []
    rids_all = list(result_map.keys())
    CHUNK = 200
    for i in range(0, len(rids_all), CHUNK):
        chunk = rids_all[i:i+CHUNK]
        placeholders = ",".join(["?"] * len(chunk))
        r2 = c.execute(
            "SELECT race_id, horse_number, lineage_nb, features_json FROM features "
            "WHERE race_id IN (" + placeholders + ")",
            chunk,
        )
        for row in r2.rows:
            try:
                f = json.loads(row[3])
            except Exception:
                continue
            rid = row[0]
            num = int(row[1])
            finish = (result_map.get(rid) or {}).get(num)
            if finish is None:
                continue
            odds = _to_num(f.get("odds_win"))
            samples.append({
                "race_id": rid,
                "num": num,
                "finish": finish,
                "odds": odds,
                "features": f,
            })
        if i % 2000 == 0:
            _log("  features loaded: " + str(i + CHUNK) + "/" + str(len(rids_all)))
    _log("samples: " + str(len(samples)))

    # 市場確率をレースごとに正規化
    per_race_odds_sum = {}
    for s in samples:
        if s["odds"] and s["odds"] > 0:
            per_race_odds_sum[s["race_id"]] = per_race_odds_sum.get(s["race_id"], 0) + (1.0 / s["odds"])
    for s in samples:
        if s["odds"] and s["odds"] > 0:
            tot = per_race_odds_sum.get(s["race_id"], 0)
            s["market_p"] = (1.0 / s["odds"]) / tot if tot > 0 else None
        else:
            s["market_p"] = None

    # 特徴量別の集計
    result = {}

    def _accumulate(name, key_to_samples):
        out = []
        for k, arr in key_to_samples.items():
            n = len(arr)
            if n == 0:
                continue
            wins = sum(1 for s in arr if s["finish"] == 1)
            top3 = sum(1 for s in arr if s["finish"] and s["finish"] <= 3)
            with_odds = [s for s in arr if s["odds"] and s["odds"] > 0 and s["market_p"] is not None]
            market_p_avg = sum(s["market_p"] for s in with_odds) / len(with_odds) if with_odds else None
            # ROI: 単勝を各馬に100円ずつ購入した場合
            payout = sum((s["odds"] * 100 for s in with_odds if s["finish"] == 1))
            cost = len(with_odds) * 100
            roi = (payout / cost * 100 - 100) if cost > 0 else None
            out.append({
                "label": str(k),
                "n": n,
                "hit_pct": wins / n * 100,
                "top3_pct": top3 / n * 100,
                "market_pct": (market_p_avg * 100) if market_p_avg is not None else None,
                "diff_pct": ((wins / n) - market_p_avg) * 100 if market_p_avg is not None else None,
                "roi_pct": roi,
            })
        return out

    # 数値特徴
    for name in NUMERIC_FEATURES:
        vals = [_to_num(s["features"].get(name)) for s in samples]
        valid_vals = [v for v in vals if v is not None]
        if len(valid_vals) < 100:
            continue
        bounds = _quantile_bounds(valid_vals)
        buckets = {}
        for s in samples:
            v = _to_num(s["features"].get(name))
            if v is None:
                continue
            bi = _bin_index(v, bounds)
            if bi is None:
                continue
            buckets.setdefault(bi, []).append(s)
        rows = _accumulate(name, buckets)
        rows.sort(key=lambda x: int(x["label"]))
        # ラベルを分位の値域に置換
        for row in rows:
            bi = int(row["label"])
            lo = bounds[bi-1] if bi > 0 else None
            hi = bounds[bi] if bi < len(bounds) else None
            def _f(x):
                return None if x is None else round(x, 4)
            row["label"] = "Q{}".format(bi + 1) + " [" + str(_f(lo)) + "," + str(_f(hi)) + "]"
        result[name] = rows

    # カテゴリ特徴（上位値のみ）
    for name in CATEGORICAL_FEATURES:
        buckets = {}
        for s in samples:
            v = s["features"].get(name)
            if v is None or v == "":
                continue
            buckets.setdefault(str(v), []).append(s)
        # n>=200 のみ
        buckets = {k: v for k, v in buckets.items() if len(v) >= 200}
        rows = _accumulate(name, buckets)
        rows.sort(key=lambda x: -x["n"])
        result[name] = rows[:30]

    # 保存
    _log("saving results")
    c.execute(
        "CREATE TABLE IF NOT EXISTS feature_analytics_cache ("
        "id INTEGER PRIMARY KEY,"
        "payload TEXT NOT NULL,"
        "generated_at TEXT NOT NULL)"
    )
    payload = {
        "features": result,
        "samples": len(samples),
        "generated_at": datetime.now().isoformat(),
    }
    pj = json.dumps(payload, ensure_ascii=False)
    c.execute(
        "INSERT INTO feature_analytics_cache (id, payload, generated_at) VALUES (1, ?, ?) "
        "ON CONFLICT (id) DO UPDATE SET payload=EXCLUDED.payload, generated_at=EXCLUDED.generated_at",
        [pj, datetime.now().isoformat()],
    )
    _log("DONE samples=" + str(len(samples)))
    try:
        c.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
import os as _o
_o._exit(0)
