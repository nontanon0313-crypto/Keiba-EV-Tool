"""騎手ランクの効果を分析する。

騎手の通算勝率から分位（ランク）を計算し、
ランク別に実1着率と市場期待を比較する。

交絡対策として、オッズ帯別にも集計する。
（良い騎手は良い馬に乗る傾向があるため）

保存先: jockey_rank_analysis_cache
"""
import os
import json
import re
from datetime import datetime
from collections import defaultdict

import libsql_client

LOG_PATH = "jockey_rank.log"
EXCLUDED_TRACK_CODES = ("03",)
MARKER_CHARS = "◇☆△▲★◆○●◎"

ODDS_BANDS = [(1.0,2.0),(2.0,3.0),(3.0,5.0),(5.0,10.0),(10.0,20.0),(20.0,50.0),(50.0,10000.0)]


def _log(msg):
    line = "[" + datetime.now().strftime("%H:%M:%S") + "] " + msg
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _strip_marker(name):
    if not name:
        return ""
    return name.lstrip(MARKER_CHARS).strip()


def _has_marker(name):
    return bool(name) and name[0] in MARKER_CHARS


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

    # 騎手名 -> 勝率 のマップを構築（n>=100 のみ）
    _log("loading jockey stats")
    try:
        r = c.execute("SELECT payload FROM jockey_stats_cache WHERE id=1")
        if not r.rows:
            _log("no jockey stats")
            return
        d = json.loads(r.rows[0][0])
    except Exception as e:
        _log("load fail: " + repr(e))
        return
    jockey_wr = {}
    for j in (d.get("jockeys") or []):
        if not j.get("name"):
            continue
        if (j.get("n") or 0) < 100:
            continue
        jockey_wr[j["name"]] = j.get("win_rate") or 0.0
    _log("jockeys with n>=100: " + str(len(jockey_wr)))

    # 分位境界を計算
    wrs = sorted(jockey_wr.values())
    if not wrs:
        _log("no valid jockeys")
        return
    def q(p):
        return wrs[int(len(wrs) * p)]
    bounds = [q(0.2), q(0.4), q(0.6), q(0.8)]
    _log("rank bounds (20/40/60/80%): " + str([round(x, 2) for x in bounds]))

    def rank_of(wr):
        if wr <= bounds[0]: return "下位20%"
        if wr <= bounds[1]: return "20-40%"
        if wr <= bounds[2]: return "40-60%"
        if wr <= bounds[3]: return "60-80%"
        return "上位20%"

    def new_bucket():
        return {"n": 0, "wins": 0, "market_sum": 0.0, "market_n": 0}

    # 全体ランク別
    by_rank = defaultdict(new_bucket)
    # オッズ帯×ランク
    by_odds_rank = defaultdict(new_bucket)
    # 減量フラグ別
    by_marker = defaultdict(new_bucket)
    # 減量フラグ×ランク
    by_marker_rank = defaultdict(new_bucket)

    n_races = 0
    n_matched = 0
    n_jockey_unknown = 0
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
                marker_map = {}
                for rr in result_runners:
                    num = rr.get("horse_number")
                    f = rr.get("finish")
                    if num and f:
                        try:
                            fin_map[int(num)] = int(f)
                        except (ValueError, TypeError):
                            pass
                    jk_rr = rr.get("jockey") or ""
                    if num and jk_rr and jk_rr[0] in MARKER_CHARS:
                        try:
                            marker_map[int(num)] = True
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
                    mp = (1.0 / ow) / inv_sum
                    hit = 1 if fin == 1 else 0
                    jk_raw = run.get("jockey") or ""
                    jk_base = _strip_marker(jk_raw)
                    wr = jockey_wr.get(jk_base)
                    if wr is None:
                        n_jockey_unknown += 1
                        continue
                    n_matched += 1
                    rank = rank_of(wr)

                    def add(b, key):
                        x = b[key]
                        x["n"] += 1
                        x["wins"] += hit
                        x["market_sum"] += mp
                        x["market_n"] += 1

                    add(by_rank, rank)
                    ob = _odds_band(ow)
                    if ob:
                        add(by_odds_rank, f"{ob}|{rank}")
                    has_m = (int(num) in marker_map) or _has_marker(jk_raw)
                    add(by_marker, "減量印あり" if has_m else "減量印なし")
                    add(by_marker_rank, ("減量印あり" if has_m else "減量印なし") + "|" + rank)
                n_races += 1
            last_rid = rows[-1][0]
            if len(rows) < PAGE:
                break
            if n_races % 3000 == 0:
                _log("  races: " + str(n_races))
    finally:
        pass
    _log(f"races: {n_races} matched: {n_matched} jockey_unknown: {n_jockey_unknown}")

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
        "by_rank": to_rows(by_rank),
        "by_odds_rank": to_rows(by_odds_rank),
        "by_marker": to_rows(by_marker),
        "by_marker_rank": to_rows(by_marker_rank),
        "n_races": n_races,
        "n_matched": n_matched,
        "bounds": bounds,
        "generated_at": datetime.now().isoformat(),
    }

    try:
        c.execute(
            "CREATE TABLE IF NOT EXISTS jockey_rank_analysis_cache ("
            "id INTEGER PRIMARY KEY, payload TEXT NOT NULL, generated_at TEXT NOT NULL)"
        )
        pj = json.dumps(result, ensure_ascii=False)
        c.execute(
            "INSERT INTO jockey_rank_analysis_cache (id, payload, generated_at) VALUES (1, ?, ?) "
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
