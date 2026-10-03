"""全 scraped_races から騎手ごとの成績を集計する。

記号（◇=減量、☆=若手など）は名前から除去し、出現回数を別カウントする。

結果は jockey_stats_cache テーブルに保存（id=1）。

使い方:
    python3 -m backend.scripts.build_jockey_stats
"""
import os
import json
import re
import time
from datetime import datetime
from collections import defaultdict

import libsql_client

LOG_PATH = "jockey_stats.log"

MARKER_CHARS = "◇☆△▲★◆○●◎"
MARKER_LABELS = {
    "◇": "女性騎手",
    "☆": "若手騎手",
    "△": "2kg減",
    "▲": "3kg減",
    "★": "女性＋減量",
    "◆": "その他印",
    "○": "その他印",
    "●": "その他印",
    "◎": "その他印",
}


def _log(msg):
    line = "[" + datetime.now().strftime("%H:%M:%S") + "] " + msg
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def strip_marker(name):
    if not name:
        return "", False
    has_marker = name[0] in MARKER_CHARS
    base = name.lstrip(MARKER_CHARS).strip()
    return base, has_marker


def _distance_band(d):
    try:
        d = int(d)
    except (ValueError, TypeError):
        return None
    bands = [(0, 1000), (1000, 1200), (1200, 1400), (1400, 1600),
             (1600, 1800), (1800, 2000), (2000, 3000)]
    for lo, hi in bands:
        if lo <= d < hi:
            return f"{lo}-{hi}"
    return None


def main():
    t0 = time.time()
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not url or not token:
        _log("TURSO_URL/TURSO_TOKEN not set")
        return
    h = url.replace("libsql://", "https://").replace("wss://", "https://")
    c = libsql_client.create_client_sync(url=h, auth_token=token)

    # 騎手ごとの集計
    stats = defaultdict(lambda: {
        "n": 0, "wins": 0, "place": 0, "show": 0,
        "n_marker": 0,
        "markers": defaultdict(int),
        "payout": 0.0, "cost": 0.0,
        "by_venue": defaultdict(lambda: {"n": 0, "wins": 0, "place": 0, "show": 0}),
        "by_dist": defaultdict(lambda: {"n": 0, "wins": 0, "place": 0, "show": 0}),
        "by_cond": defaultdict(lambda: {"n": 0, "wins": 0, "place": 0, "show": 0}),
    })

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
                cond = d.get("track_condition")
                dist_b = _distance_band(d.get("distance"))
                # 結果から騎手ごとの着順と払戻を集める
                for rr in (d.get("result_runners") or []):
                    j_raw = (rr.get("jockey") or "").strip()
                    if not j_raw:
                        continue
                    jname, has_marker = strip_marker(j_raw)
                    if not jname:
                        continue
                    fin = rr.get("finish")
                    try:
                        fin = int(fin) if fin else None
                    except (ValueError, TypeError):
                        fin = None
                    if fin is None:
                        continue
                    # 単勝オッズを取得（runners から馬番一致で）
                    st = stats[jname]
                    st["n"] += 1
                    if has_marker:
                        st["n_marker"] += 1
                        st["markers"][j_raw[0]] += 1
                    if fin == 1:
                        st["wins"] += 1
                    if fin <= 2:
                        st["place"] += 1
                    if fin <= 3:
                        st["show"] += 1
                    # 会場別
                    if venue:
                        v = st["by_venue"][venue]
                        v["n"] += 1
                        if fin == 1: v["wins"] += 1
                        if fin <= 2: v["place"] += 1
                        if fin <= 3: v["show"] += 1
                    # 距離帯別
                    if dist_b:
                        dd = st["by_dist"][dist_b]
                        dd["n"] += 1
                        if fin == 1: dd["wins"] += 1
                        if fin <= 2: dd["place"] += 1
                        if fin <= 3: dd["show"] += 1
                    # 馬場別
                    if cond:
                        cc = st["by_cond"][cond]
                        cc["n"] += 1
                        if fin == 1: cc["wins"] += 1
                        if fin <= 2: cc["place"] += 1
                        if fin <= 3: cc["show"] += 1
                n_races += 1
            last_rid = rows[-1][0]
            if len(rows) < PAGE:
                break
            if n_races % 3000 == 0:
                _log("  races: " + str(n_races))
        _log("races: " + str(n_races) + " jockeys: " + str(len(stats)))

        # ROI 計算のため、もう一巡して騎手ごとの単勝購入ROIを集計
        roi_stats = defaultdict(lambda: {"payout": 0.0, "cost": 0.0})
        last_rid = ""
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
                # 馬番 -> オッズ
                odds_map = {}
                for run in (d.get("runners") or []):
                    num = run.get("horse_number")
                    ow = run.get("odds_win")
                    if num and ow:
                        try:
                            odds_map[int(num)] = float(ow)
                        except (ValueError, TypeError):
                            pass
                for rr in (d.get("result_runners") or []):
                    j_raw = (rr.get("jockey") or "").strip()
                    if not j_raw:
                        continue
                    jname, _ = strip_marker(j_raw)
                    if not jname:
                        continue
                    num = rr.get("horse_number")
                    fin = rr.get("finish")
                    try:
                        num = int(num) if num else None
                        fin = int(fin) if fin else None
                    except (ValueError, TypeError):
                        continue
                    if num is None or fin is None:
                        continue
                    ow = odds_map.get(num)
                    if not ow or ow <= 0:
                        continue
                    roi_stats[jname]["cost"] += 100
                    if fin == 1:
                        roi_stats[jname]["payout"] += ow * 100
            last_rid = rows[-1][0]
            if len(rows) < PAGE:
                break
        _log("ROI computed")

        # 出力
        out = []
        for jname, st in stats.items():
            n = st["n"]
            if n < 10:
                continue
            rj = roi_stats.get(jname, {})
            cost = rj.get("cost", 0)
            roi = (rj.get("payout", 0) / cost * 100 - 100) if cost > 0 else None
            out.append({
                "name": jname,
                "n": n,
                "n_marker": st["n_marker"],
                "markers": dict(st["markers"]),
                "wins": st["wins"],
                "place": st["place"],
                "show": st["show"],
                "win_rate": round(st["wins"] / n * 100, 2),
                "place_rate": round(st["place"] / n * 100, 2),
                "show_rate": round(st["show"] / n * 100, 2),
                "roi_pct": round(roi, 1) if roi is not None else None,
                "by_venue": {k: dict(v) for k, v in st["by_venue"].items()},
                "by_dist": {k: dict(v) for k, v in st["by_dist"].items()},
                "by_cond": {k: dict(v) for k, v in st["by_cond"].items()},
            })
        out.sort(key=lambda x: -x["n"])
        _log("output jockeys: " + str(len(out)))

        c.execute(
            "CREATE TABLE IF NOT EXISTS jockey_stats_cache ("
            "id INTEGER PRIMARY KEY, payload TEXT NOT NULL, generated_at TEXT NOT NULL)"
        )
        payload = {
            "jockeys": out,
            "n_jockeys": len(out),
            "n_races": n_races,
            "generated_at": datetime.now().isoformat(),
        }
        pj = json.dumps(payload, ensure_ascii=False)
        c.execute(
            "INSERT INTO jockey_stats_cache (id, payload, generated_at) VALUES (1, ?, ?) "
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
