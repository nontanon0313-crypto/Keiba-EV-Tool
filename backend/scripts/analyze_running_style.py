"""脚質別の効果を分析する。

features テーブルの style / avg_corner_ratio を使い、
脚質別の実1着率と市場期待を比較する。

分析項目:
- 脚質別（逃げ/先行/差し/追込）
- 脚質×枠番
- 脚質×会場
- 脚質×距離帯
- 脚質×頭数

保存先: running_style_analysis_cache
"""
import os
import json
from datetime import datetime
from collections import defaultdict

import libsql_client

LOG_PATH = "running_style.log"
EXCLUDED_TRACK_CODES = ("03",)


def _log(msg):
    line = "[" + datetime.now().strftime("%H:%M:%S") + "] " + msg
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _distance_band(d):
    try:
        d = int(d)
    except (ValueError, TypeError):
        return None
    bands = [(0,1000),(1000,1200),(1200,1400),(1400,1600),(1600,1800),(1800,2000),(2000,3000)]
    for lo, hi in bands:
        if lo <= d < hi:
            return f"{lo}-{hi}"
    return None


def _to_num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _style_from_ratio(r):
    if r is None:
        return None
    if r < 0.2: return "逃げ"
    if r < 0.4: return "先行"
    if r < 0.7: return "差し"
    return "追込"


def load_features_map(c):
    """features から (race_id, horse_number) -> {style, ratio} を構築。"""
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
            style = f.get("style")
            ratio = _to_num(f.get("avg_corner_ratio"))
            if style:
                fmap[(row[0], int(row[1]))] = {"style": style, "ratio": ratio}
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

    by_style = defaultdict(new_bucket)
    by_style_frame = defaultdict(new_bucket)
    by_style_venue = defaultdict(new_bucket)
    by_style_dist = defaultdict(new_bucket)
    by_style_nrun = defaultdict(new_bucket)

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
                venue = (d.get("venue") or "").strip()
                dist_b = _distance_band(d.get("distance"))
                runners = d.get("runners") or []
                n_run = len(runners)
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
                    if not feat or not feat.get("style"):
                        n_unknown += 1
                        continue
                    n_matched += 1
                    mp = (1.0 / ow) / inv_sum
                    hit = 1 if fin == 1 else 0
                    style = feat["style"]
                    frame = run.get("frame_number")

                    def add(b, key):
                        x = b[key]
                        x["n"] += 1
                        x["wins"] += hit
                        x["market_sum"] += mp
                        x["market_n"] += 1

                    add(by_style, style)
                    if frame:
                        add(by_style_frame, f"{style}|{int(frame)}")
                    if venue:
                        add(by_style_venue, f"{style}|{venue}")
                    if dist_b:
                        add(by_style_dist, f"{style}|{dist_b}")
                    # 頭数帯
                    if n_run <= 7: nb = "≤7頭"
                    elif n_run <= 9: nb = "8-9頭"
                    elif n_run <= 11: nb = "10-11頭"
                    else: nb = "12頭以上"
                    add(by_style_nrun, f"{style}|{nb}")
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
        "by_style": to_rows(by_style),
        "by_style_frame": to_rows(by_style_frame, 100),
        "by_style_venue": to_rows(by_style_venue),
        "by_style_dist": to_rows(by_style_dist, 100),
        "by_style_nrun": to_rows(by_style_nrun, 100),
        "n_races": n_races,
        "n_matched": n_matched,
        "generated_at": datetime.now().isoformat(),
    }

    try:
        c.execute(
            "CREATE TABLE IF NOT EXISTS running_style_analysis_cache ("
            "id INTEGER PRIMARY KEY, payload TEXT NOT NULL, generated_at TEXT NOT NULL)"
        )
        pj = json.dumps(result, ensure_ascii=False)
        c.execute(
            "INSERT INTO running_style_analysis_cache (id, payload, generated_at) VALUES (1, ?, ?) "
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
