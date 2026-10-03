"""条件別の市場乖離を網羅的に集計する。

軸:
- 会場 (venue)
- 距離帯 (distance_band)
- 馬場 (track_condition)
- クラス (class)

1条件 / 2条件 / 3条件の組み合わせで、
実1着率 − 市場期待1着率 と ROI を集計する。

結果は condition_deviation_cache テーブルに保存。

使い方:
    python3 -m backend.scripts.build_condition_deviation
"""
import os
import json
import re
import time
from datetime import datetime
from collections import defaultdict
from itertools import combinations

import libsql_client

LOG_PATH = "condition_deviation.log"
MIN_CELL_N = 300

# 軸の定義（後で使う）
DIMENSIONS = ["venue", "distance_band", "track_condition", "class"]

DIST_BANDS = [(0, 1000), (1000, 1200), (1200, 1400), (1400, 1600),
              (1600, 1800), (1800, 2000), (2000, 3000)]

_CLASS_MAP = str.maketrans("ＡＢＣ１２３４５６７８９０", "ABC1234567890")


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
    for lo, hi in DIST_BANDS:
        if lo <= d < hi:
            return f"{lo}-{hi}"
    return None


def _parse_class(name):
    if not name:
        return None
    t = name.translate(_CLASS_MAP)
    m = re.search(r"([ABC])([1-3])", t)
    if m:
        return m.group(1) + m.group(2)
    m2 = re.search(r"(\d)歳", t)
    if m2:
        return m2.group(1) + "歳"
    if "新馬" in name:
        return "新馬"
    return None


def _to_num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _tercile_bounds(vals):
    vs = sorted([v for v in vals if v is not None])
    if len(vs) < 30:
        return None
    return [vs[int(len(vs) / 3)], vs[int(len(vs) * 2 / 3)]]


def load_races():
    """scraped_races から条件と馬情報を読み込む。"""
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    h = url.replace("libsql://", "https://").replace("wss://", "https://")
    c = libsql_client.create_client_sync(url=h, auth_token=token)
    samples = []
    try:
        last_rid = ""
        PAGE = 300
        n_races = 0
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
                venue = (d.get("venue") or "").strip()
                if not venue:
                    continue
                dist_b = _distance_band(d.get("distance"))
                cond = d.get("track_condition")
                race_name = d.get("race_name") or ""
                cls = _parse_class(race_name)
                runners = d.get("runners") or []
                result_runners = d.get("result_runners") or []
                # finish_map
                fin_map = {}
                for rr in result_runners:
                    num = rr.get("horse_number")
                    fin = rr.get("finish")
                    if num and fin:
                        fin_map[int(num)] = int(fin)
                # 市場確率を計算
                inv_sum = 0.0
                for run in runners:
                    ow = _to_num(run.get("odds_win"))
                    if ow and ow > 0:
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
                    if not ow or ow <= 0:
                        continue
                    p_mkt = (1.0 / ow) / inv_sum
                    samples.append({
                        "venue": venue,
                        "distance_band": dist_b,
                        "track_condition": cond,
                        "class": cls,
                        "finish": fin,
                        "odds": ow,
                        "market_p": p_mkt,
                    })
                n_races += 1
            last_rid = rows[-1][0]
            if len(rows) < PAGE:
                break
            if n_races % 3000 == 0:
                _log("  races loaded: " + str(n_races))
        _log("races: " + str(n_races) + " samples: " + str(len(samples)))
        return samples
    finally:
        try:
            c.close()
        except Exception:
            pass


def _bin_boundaries(values):
    """10分位の境界を返す。"""
    vs = sorted([v for v in values if v is not None])
    if not vs:
        return []
    return [vs[max(0, min(len(vs) - 1, int(len(vs) * (i + 1) / 10) - 1))] for i in range(9)]


def _aggregate(groups):
    """groups: dict key_tuple -> list of samples。各セルの指標を計算。"""
    out = []
    for key, arr in groups.items():
        n = len(arr)
        if n < MIN_CELL_N:
            continue
        wins = sum(1 for s in arr if s["finish"] == 1)
        hit = wins / n
        market = sum(s["market_p"] for s in arr) / n
        diff = (hit - market) * 100
        se = (hit * (1 - hit) / n) ** 0.5
        diff_se = se * 100
        diff_lo = diff - 1.96 * diff_se
        diff_hi = diff + 1.96 * diff_se
        sig = "有意" if diff_lo > 0 else ("劣位" if diff_hi < 0 else "-")
        payout = sum((s["odds"] * 100) for s in arr if s["finish"] == 1)
        cost = n * 100
        roi = (payout / cost * 100 - 100) if cost > 0 else None
        out.append({
            "key": list(key),
            "n": n,
            "wins": wins,
            "hit_pct": round(hit * 100, 2),
            "market_pct": round(market * 100, 2),
            "diff_pct": round(diff, 2),
            "diff_ci_lo": round(diff_lo, 2),
            "diff_ci_hi": round(diff_hi, 2),
            "sig": sig,
            "roi_pct": round(roi, 1) if roi is not None else None,
        })
    return out


def main():
    t0 = time.time()
    samples = load_races()
    _log("samples: " + str(len(samples)))

    results_by_dims = {}

    # 1条件 / 2条件 / 3条件
    dim_sets = []
    for k in [1, 2, 3]:
        for combo in combinations(DIMENSIONS, k):
            dim_sets.append(combo)

    for dims in dim_sets:
        key_name = "+".join(dims)
        groups = defaultdict(list)
        for s in samples:
            key = tuple(s.get(d) for d in dims)
            if any(v is None or v == "" for v in key):
                continue
            groups[key].append(s)
        rows = _aggregate(groups)
        # 有意セルを上位に
        rows.sort(key=lambda x: -x["diff_pct"])
        results_by_dims[key_name] = rows
        _log(key_name + ": " + str(len(rows)) + " cells")

    # 保存
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    h = url.replace("libsql://", "https://").replace("wss://", "https://")
    c = libsql_client.create_client_sync(url=h, auth_token=token)
    try:
        c.execute(
            "CREATE TABLE IF NOT EXISTS condition_deviation_cache ("
            "id INTEGER PRIMARY KEY, payload TEXT NOT NULL, generated_at TEXT NOT NULL)"
        )
        payload = {
            "results": results_by_dims,
            "samples": len(samples),
            "generated_at": datetime.now().isoformat(),
        }
        pj = json.dumps(payload, ensure_ascii=False)
        c.execute(
            "INSERT INTO condition_deviation_cache (id, payload, generated_at) VALUES (1, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET payload=EXCLUDED.payload, generated_at=EXCLUDED.generated_at",
            [pj, datetime.now().isoformat()],
        )
        _log("DONE " + str(round(time.time() - t0, 1)) + "s")
    finally:
        try:
            c.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
import os as _o
_o._exit(0)
