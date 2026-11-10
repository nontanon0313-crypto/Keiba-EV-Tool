"""人気帯別の枠番効果を分析する。

人気帯ごとに枠番別の実1着率と市場期待を比較。
これで「枠そのものの効果」と「強い馬の枠偏り」を切り分ける。

保存先: frame_by_popularity_cache
"""
import os
import json
from datetime import datetime
from collections import defaultdict

import libsql_client

LOG_PATH = "frame_by_popularity.log"
EXCLUDED_TRACK_CODES = ("03",)

POP_BANDS = [(1,1),(2,2),(3,3),(4,5),(6,9),(10,99)]


def _log(msg):
    line = "[" + datetime.now().strftime("%H:%M:%S") + "] " + msg
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _pop_band(pop):
    for lo, hi in POP_BANDS:
        if lo <= pop <= hi:
            return f"{lo}-{hi}人気" if lo != hi else f"{lo}人気"
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

    # buckets[pop_band][frame] = stats
    buckets = defaultdict(lambda: defaultdict(lambda: {
        "n": 0, "wins": 0, "market_sum": 0.0, "market_n": 0,
    }))
    # 会場別
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
                    pop = run.get("popularity")
                    if not num or not frame or not pop:
                        continue
                    try:
                        frame = int(frame)
                        pop = int(pop)
                    except (ValueError, TypeError):
                        continue
                    fin = fin_map.get(int(num))
                    if fin is None:
                        continue
                    pb = _pop_band(pop)
                    if not pb:
                        continue
                    ow = _to_num(run.get("odds_win"))
                    if not ow or ow <= 1.0:
                        continue
                    mp = (1.0 / ow) / inv_sum
                    b = buckets[pb][frame]
                    b["n"] += 1
                    if fin == 1:
                        b["wins"] += 1
                    b["market_sum"] += mp
                    b["market_n"] += 1
                    if venue:
                        vb = v_buckets[venue][pb][frame]
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

    # 出力: 全体 + 会場別
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
    for pb in [b[0] if b[0] == b[1] else f"{b[0]}-{b[1]}人気" for b in POP_BANDS]:
        if pb not in buckets:
            # 名前の変換ミスに対応
            for k in buckets.keys():
                if k == pb:
                    break
        if pb in buckets:
            overall.append({"pop_band": pb, "frames": to_rows(buckets[pb])})

    # ラベル再構築（安全のため）
    overall = []
    for pb, b in buckets.items():
        overall.append({"pop_band": pb, "frames": to_rows(b)})
    # 表示順
    order = {"1人気":0,"2人気":1,"3人気":2,"4-5人気":3,"6-9人気":4,"10-99人気":5}
    overall.sort(key=lambda x: order.get(x["pop_band"], 9))

    venues_out = {}
    for venue, by_pop in v_buckets.items():
        rows = []
        for pb, b in by_pop.items():
            rows.append({"pop_band": pb, "frames": to_rows(b)})
        rows.sort(key=lambda x: order.get(x["pop_band"], 9))
        venues_out[venue] = rows

    try:
        c.execute(
            "CREATE TABLE IF NOT EXISTS frame_by_popularity_cache ("
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
            "INSERT INTO frame_by_popularity_cache (id, payload, generated_at) VALUES (1, ?, ?) "
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
