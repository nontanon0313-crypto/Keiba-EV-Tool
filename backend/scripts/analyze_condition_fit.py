"""条件適性の効果を分析する。

features テーブルの条件適性関連特徴量を使い、
各条件での実1着率と市場期待を比較する。

対象:
- same_dist_place_rate（同距離帯連対率）
- same_dist_avg_finish（同距離帯平均着順）
- same_dist_n（同距離帯出走数）
- same_cond_place_rate（同馬場連対率）
- same_cond_n
- same_venue_place_rate（同会場連対率）
- same_venue_n
- same_surface_place_rate（同芝ダート連対率）
- same_surface_n
- days_since_last（前走間隔）
- is_renntou（連闘）
- is_long_break（休み明け）

保存先: condition_fit_analysis_cache
"""
import os
import json
import math
from datetime import datetime
from collections import defaultdict

import libsql_client

LOG_PATH = "condition_fit.log"
EXCLUDED_TRACK_CODES = ("03",)


def _log(msg):
    line = "[" + datetime.now().strftime("%H:%M:%S") + "] " + msg
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _to_num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _bin_place_rate(v):
    if v is None: return "欠損"
    if v == 0: return "0"
    if v < 0.1: return "0-0.1"
    if v < 0.2: return "0.1-0.2"
    if v < 0.3: return "0.2-0.3"
    if v < 0.5: return "0.3-0.5"
    return "0.5+"


def _bin_avg_finish(v):
    if v is None: return "欠損"
    if v < 3: return "≤3"
    if v < 5: return "3-5"
    if v < 7: return "5-7"
    if v < 9: return "7-9"
    return "9+"


def _bin_n(v):
    if v is None: return "欠損"
    if v == 0: return "0"
    if v <= 2: return "1-2"
    if v <= 5: return "3-5"
    if v <= 10: return "6-10"
    return "11+"


def _bin_days(v):
    if v is None: return "欠損"
    if v <= 7: return "≤7日"
    if v <= 30: return "8-30日"
    if v <= 90: return "31-90日"
    if v <= 180: return "91-180日"
    return "181日+"


def load_features_map(c):
    fmap = {}
    last_rid = ""
    PAGE = 500
    n = 0
    while True:
        r = c.execute(
            "SELECT race_id, horse_number, features_json FROM features WHERE race_id > ? ORDER BY race_id, horse_number LIMIT ?",
            [last_rid, PAGE],
        )
        rows = list(r.rows)
        if not rows:
            break
        for row in rows:
            n += 1
            try:
                f = json.loads(row[2]) if isinstance(row[2], str) else row[2]
            except Exception:
                continue
            fmap[(row[0], int(row[1]))] = f
        last_rid = rows[-1][0]
        if len(rows) < PAGE:
            break
    _log(f"features loaded: {n}")
    return fmap


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    h = url.replace("libsql://", "https://").replace("wss://", "https://")
    c = libsql_client.create_client_sync(url=h, auth_token=token)

    fmap = load_features_map(c)

    def new_bucket():
        return {"n": 0, "wins": 0, "market_sum": 0.0, "market_n": 0}

    # 各特徴量別
    by_dist_pr = defaultdict(new_bucket)
    by_dist_af = defaultdict(new_bucket)
    by_dist_n = defaultdict(new_bucket)
    by_cond_pr = defaultdict(new_bucket)
    by_cond_n = defaultdict(new_bucket)
    by_venue_pr = defaultdict(new_bucket)
    by_venue_n = defaultdict(new_bucket)
    by_surface_pr = defaultdict(new_bucket)
    by_surface_n = defaultdict(new_bucket)
    by_days = defaultdict(new_bucket)
    by_flags = defaultdict(new_bucket)

    n_races = 0
    n_matched = 0
    n_unknown = 0
    try:
        last_rid = ""
        PAGE = 300
        while True:
            r = c.execute(
                "SELECT race_id, payload FROM scraped_races WHERE race_id > ? ORDER BY race_id LIMIT ?",
                [last_rid, PAGE],
            )
            rows = list(r.rows)
            if not rows:
                break
            for row in rows:
                rid = row[0]
                parts = rid.split("-")
                if len(parts) >= 3 and parts[2] in EXCLUDED_TRACK_CODES:
                    continue
                try:
                    d = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                except Exception:
                    continue
                runners = d.get("runners") or []
                result_runners = d.get("result_runners") or []
                fin_map = {}
                for rr in result_runners:
                    num = rr.get("horse_number")
                    f = rr.get("finish")
                    if num and f:
                        try:
                            fin_map[int(num)] = int(f)
                        except (ValueError, TypeError):
                            pass
                inv_sum = 0.0
                for run in runners:
                    ow = _to_num(run.get("odds_win"))
                    if ow and ow > 1.0:
                        inv_sum += 1.0 / ow
                if inv_sum <= 0:
                    continue
                for run in runners:
                    num = run.get("horse_number")
                    if not num:
                        continue
                    fin = fin_map.get(int(num))
                    if fin is None:
                        continue
                    ow = _to_num(run.get("odds_win"))
                    if not ow or ow <= 1.0:
                        continue
                    feat = fmap.get((rid, int(num)))
                    if not feat:
                        n_unknown += 1
                        continue
                    n_matched += 1
                    mp = (1.0 / ow) / inv_sum
                    hit = 1 if fin == 1 else 0

                    def add(b, key):
                        x = b[key]
                        x["n"] += 1
                        x["wins"] += hit
                        x["market_sum"] += mp
                        x["market_n"] += 1

                    # 距離帯
                    add(by_dist_pr, _bin_place_rate(_to_num(feat.get("same_dist_place_rate"))))
                    add(by_dist_af, _bin_avg_finish(_to_num(feat.get("same_dist_avg_finish"))))
                    add(by_dist_n, _bin_n(_to_num(feat.get("same_dist_n"))))
                    # 馬場
                    add(by_cond_pr, _bin_place_rate(_to_num(feat.get("same_cond_place_rate"))))
                    add(by_cond_n, _bin_n(_to_num(feat.get("same_cond_n"))))
                    # 会場
                    add(by_venue_pr, _bin_place_rate(_to_num(feat.get("same_venue_place_rate"))))
                    add(by_venue_n, _bin_n(_to_num(feat.get("same_venue_n"))))
                    # 芝ダート
                    add(by_surface_pr, _bin_place_rate(_to_num(feat.get("same_surface_place_rate"))))
                    add(by_surface_n, _bin_n(_to_num(feat.get("same_surface_n"))))
                    # 前走間隔
                    add(by_days, _bin_days(_to_num(feat.get("days_since_last"))))
                    # フラグ
                    ren = feat.get("is_renntou")
                    lb = feat.get("is_long_break")
                    if ren == 1: add(by_flags, "連闘")
                    elif lb == 1: add(by_flags, "休み明け")
                    else: add(by_flags, "通常")
                n_races += 1
            last_rid = rows[-1][0]
            if len(rows) < PAGE:
                break
            if n_races % 3000 == 0:
                _log("  races: " + str(n_races))
    finally:
        pass
    _log(f"races: {n_races} matched: {n_matched} unknown: {n_unknown}")

    def to_rows(b, min_n=200):
        out = []
        for k, x in b.items():
            if x["n"] < min_n:
                continue
            n = x["n"]
            mp_avg = x["market_sum"] / x["market_n"] if x["market_n"] else 0
            out.append({
                "key": k,
                "n": n,
                "win_rate_pct": round(x["wins"] / n * 100, 3),
                "market_pct": round(mp_avg * 100, 3),
                "diff_pct": round((x["wins"] / n - mp_avg) * 100, 3),
            })
        return out

    result = {
        "by_dist_place_rate": to_rows(by_dist_pr),
        "by_dist_avg_finish": to_rows(by_dist_af),
        "by_dist_n": to_rows(by_dist_n),
        "by_cond_place_rate": to_rows(by_cond_pr),
        "by_cond_n": to_rows(by_cond_n),
        "by_venue_place_rate": to_rows(by_venue_pr),
        "by_venue_n": to_rows(by_venue_n),
        "by_surface_place_rate": to_rows(by_surface_pr),
        "by_surface_n": to_rows(by_surface_n),
        "by_days": to_rows(by_days),
        "by_flags": to_rows(by_flags),
        "n_races": n_races,
        "n_matched": n_matched,
        "generated_at": datetime.now().isoformat(),
    }

    try:
        c.execute(
            "CREATE TABLE IF NOT EXISTS condition_fit_analysis_cache ("
            "id INTEGER PRIMARY KEY, payload TEXT NOT NULL, generated_at TEXT NOT NULL)"
        )
        pj = json.dumps(result, ensure_ascii=False)
        c.execute(
            "INSERT INTO condition_fit_analysis_cache (id, payload, generated_at) VALUES (1, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET payload=EXCLUDED.payload, generated_at=EXCLUDED.generated_at",
            [pj, datetime.now().isoformat()],
        )
        _log("saved")
    finally:
        try:
            c.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
