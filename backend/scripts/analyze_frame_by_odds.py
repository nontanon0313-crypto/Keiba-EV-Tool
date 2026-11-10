"""オッズ帯別の枠番効果を分析する。

単勝オッズを帯に区切り、帯ごとに枠番別の実1着率と市場期待を比較。
人気帯別の分析と同傾向が出るかで、発見の頑健性を確認する。

保存先: frame_by_odds_cache
"""
import os
import json
from datetime import datetime
from collections import defaultdict

import libsql_client

LOG_PATH = "frame_by_odds.log"
EXCLUDED_TRACK_CODES = ("03",)

ODDS_BANDS = [(1.0,1.5),(1.5,2.0),(2.0,2.5),(2.5,3.0),(3.0,4.0),(4.0,5.0),(5.0,7.0),(7.0,10.0),(10.0,20.0),(20.0,50.0),(50.0,100.0),(100.0,10000.0)]


def _log(msg):
    line = "[" + datetime.now().strftime("%H:%M:%S") + "] " + msg
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _odds_band(ow):
    for lo, hi in ODDS_BANDS:
        if lo <= ow < hi:
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
        "n": 0, "wins": 0, "market_sum": 0.0, "market_n": 0,
    }))
    v_buckets = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {
        "n": 0, "wins": 0, "market_sum": 0.0, "market_n": 0,
    })))

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
                    frame = run.get("frame_number")
                    if not num or not frame:
                        continue
                    ow = _to_num(run.get("odds_win"))
                    if not ow or ow <= 1.0:
                        continue
                    fin = fin_map.get(int(num))
                    if fin is None:
                        continue
                    ob = _odds_band(ow)
                    if not ob:
                        continue
                    try:
                        frame = int(frame)
                    except (ValueError, TypeError):
                        continue
                    mp = (1.0 / ow) / inv_sum
                    b = buckets[ob][frame]
                    b["n"] += 1
                    if fin == 1:
                        b["wins"] += 1
                    b["market_sum"] += mp
                    b["market_n"] += 1
                    if venue:
                        vb = v_buckets[venue][ob][frame]
                        vb["n"] += 1
                        if fin == 1:
                            vb["wins"] += 1
                        vb["market_sum"] += mp
                        vb["market_n"] += 1
                n_races += 1
            last_rid = rows[-1][0]
            if len(rows) < PAGE:
                break
            if n_races % 3000 == 0:
                _log("  races: " + str(n_races))
    finally:
        pass
    _log("races: " + str(n_races))

    def to_rows(b):
        rows = []
        for f in range(1, 9):
            x = b.get(f)
            if not x or x["n"] == 0:
                rows.append({"frame": f, "n": 0})
                continue
            n = x["n"]
            mp_avg = x["market_sum"] / x["market_n"] if x["market_n"] else None
            rows.append({
                "frame": f,
                "n": n,
                "win_rate_pct": round(x["wins"] / n * 100, 3),
                "market_pct": round(mp_avg * 100, 3) if mp_avg is not None else None,
                "diff_pct": round((x["wins"] / n - mp_avg) * 100, 3) if mp_avg is not None else None,
            })
        return rows

    overall = []
    for ob, b in buckets.items():
        overall.append({"odds_band": ob, "frames": to_rows(b)})
    def band_key(x):
        try:
            return float(x["odds_band"].split("-")[0])
        except Exception:
            return 999
    overall.sort(key=band_key)

    venues_out = {}
    for venue, by_ob in v_buckets.items():
        rows = []
        for ob, b in by_ob.items():
            rows.append({"odds_band": ob, "frames": to_rows(b)})
        rows.sort(key=band_key)
        venues_out[venue] = rows

    try:
        c.execute(
            "CREATE TABLE IF NOT EXISTS frame_by_odds_cache ("
            "id INTEGER PRIMARY KEY, payload TEXT NOT NULL, generated_at TEXT NOT NULL)"
        )
        payload = {
            "overall": overall,
            "by_venue": venues_out,
            "n_races": n_races,
            "generated_at": datetime.now().isoformat(),
        }
        pj = json.dumps(payload, ensure_ascii=False)
        c.execute(
            "INSERT INTO frame_by_odds_cache (id, payload, generated_at) VALUES (1, ?, ?) "
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
