"""枠番優位性のメカニズム分析。

会場×距離帯×馬場ごとに、枠番別の:
- 実1着率
- 市場期待1着率
- 平均人気
- 平均オッズ
- 平均斤量

を集計し、枠番優位性が「馬の質の偏り」か「コース形状」かを切り分ける。

保存先: frame_mechanism_cache
"""
import os
import json
from datetime import datetime
from collections import defaultdict

import libsql_client

LOG_PATH = "frame_mechanism.log"

DIST_BANDS = [(0,1000),(1000,1200),(1200,1400),(1400,1600),(1600,1800),(1800,2000),(2000,3000)]
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
    for lo, hi in DIST_BANDS:
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


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    h = url.replace("libsql://", "https://").replace("wss://", "https://")
    c = libsql_client.create_client_sync(url=h, auth_token=token)

    buckets = defaultdict(lambda: defaultdict(lambda: {
        "n": 0, "wins": 0,
        "market_sum": 0.0, "market_n": 0,
        "pop_sum": 0.0, "pop_n": 0,
        "odds_sum": 0.0, "odds_n": 0,
        "weight_sum": 0.0, "weight_n": 0,
        "hw_sum": 0.0, "hw_n": 0,
    }))

    n_races = 0
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
                if not venue:
                    continue
                dist_b = _distance_band(d.get("distance"))
                if not dist_b:
                    continue
                cond = d.get("track_condition") or ""
                if not cond:
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
                key = (venue, dist_b, cond)
                for run in runners:
                    num = run.get("horse_number")
                    frame = run.get("frame_number")
                    if not num or not frame:
                        continue
                    fin = fin_map.get(int(num))
                    if fin is None:
                        continue
                    b = buckets[key][int(frame)]
                    b["n"] += 1
                    if fin == 1:
                        b["wins"] += 1
                    ow = _to_num(run.get("odds_win"))
                    if ow and ow > 1.0:
                        b["market_sum"] += (1.0 / ow) / inv_sum
                        b["market_n"] += 1
                        b["odds_sum"] += ow
                        b["odds_n"] += 1
                    pop = run.get("popularity")
                    if pop is not None:
                        try:
                            b["pop_sum"] += float(pop)
                            b["pop_n"] += 1
                        except (ValueError, TypeError):
                            pass
                    wt = _to_num(run.get("weight"))
                    if wt is not None:
                        b["weight_sum"] += wt
                        b["weight_n"] += 1
                    hw = _to_num(run.get("horse_weight"))
                    if hw is not None:
                        b["hw_sum"] += hw
                        b["hw_n"] += 1
                n_races += 1
            last_rid = rows[-1][0]
            if len(rows) < PAGE:
                break
            if n_races % 3000 == 0:
                _log("  races: " + str(n_races))
    finally:
        pass

    _log("races processed: " + str(n_races))

    cells = []
    for key, frame_data in buckets.items():
        total_n = sum(f["n"] for f in frame_data.values())
        if total_n < 100:
            continue
        venue, dist_b, cond = key
        frames_out = []
        for f in range(1, 9):
            b = frame_data.get(f)
            if not b or b["n"] == 0:
                frames_out.append({"frame": f, "n": 0})
                continue
            n = b["n"]
            frames_out.append({
                "frame": f,
                "n": n,
                "win_rate_pct": round(b["wins"] / n * 100, 3),
                "market_pct": round(b["market_sum"] / b["market_n"] * 100, 3) if b["market_n"] else None,
                "diff_pct": round((b["wins"] / n - b["market_sum"] / b["market_n"]) * 100, 3) if b["market_n"] else None,
                "avg_pop": round(b["pop_sum"] / b["pop_n"], 2) if b["pop_n"] else None,
                "avg_odds": round(b["odds_sum"] / b["odds_n"], 2) if b["odds_n"] else None,
                "avg_weight": round(b["weight_sum"] / b["weight_n"], 2) if b["weight_n"] else None,
                "avg_hw": round(b["hw_sum"] / b["hw_n"], 1) if b["hw_n"] else None,
            })
        cells.append({
            "venue": venue,
            "distance_band": dist_b,
            "track_condition": cond,
            "total_n": total_n,
            "frames": frames_out,
        })

    cells.sort(key=lambda x: -x["total_n"])
    _log("cells: " + str(len(cells)))

    try:
        c.execute(
            "CREATE TABLE IF NOT EXISTS frame_mechanism_cache ("
            "id INTEGER PRIMARY KEY, payload TEXT NOT NULL, generated_at TEXT NOT NULL)"
        )
        payload = {
            "cells": cells,
            "n_races": n_races,
            "generated_at": datetime.now().isoformat(),
        }
        pj = json.dumps(payload, ensure_ascii=False)
        c.execute(
            "INSERT INTO frame_mechanism_cache (id, payload, generated_at) VALUES (1, ?, ?) "
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
