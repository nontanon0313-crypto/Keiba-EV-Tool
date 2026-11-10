"""馬×騎手の相性残差を分析する。

馬効果と騎手効果を分離し、残差（相性）が市場に織り込まれているか確認。

相性残差 = ペア連対率 - 馬効果 - 騎手効果 + 全体平均

保存先: horse_jockey_residual_cache
"""
import os
import json
import re
from datetime import datetime
from collections import defaultdict

import libsql_client

LOG_PATH = "horse_jockey_residual.log"
EXCLUDED_TRACK_CODES = ("03",)
MARKER_CHARS = "◇☆△▲★◆○●◎"


def _log(msg):
    line = "[" + datetime.now().strftime("%H:%M:%S") + "] " + msg
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _clean_jockey(name):
    if not name:
        return ""
    s = name.lstrip(MARKER_CHARS).strip()
    s = re.sub(r"\s*[\(（][^\)）]*[\)）]\s*$", "", s).strip()
    return s


def _to_num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _parse_finish(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def build_hj_map(c):
    """horse_details から (lineage_nb, jockey) の成績と、馬別・騎手別の集計を作る。"""
    hj_map = {}  # (ln, jk) -> {n, place, wins}
    horse_stats = defaultdict(lambda: {"n":0, "place":0, "wins":0})
    jockey_stats = defaultdict(lambda: {"n":0, "place":0, "wins":0})
    last_jockey_map = {}

    last_ln = ""
    PAGE = 200
    n = 0
    while True:
        r = c.execute(
            "SELECT lineage_nb, payload FROM horse_details WHERE lineage_nb > ? ORDER BY lineage_nb LIMIT ?",
            [last_ln, PAGE],
        )
        rows = list(r.rows)
        if not rows:
            break
        for row in rows:
            n += 1
            ln = row[0]
            try:
                d = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except Exception:
                continue
            hist = d.get("history") or {}
            header = hist.get("header") or []
            data = hist.get("rows") or []
            if not header or not data:
                continue
            try:
                i_jockey = header.index("騎手")
                i_finish = header.index("着順")
            except ValueError:
                continue
            first_row = data[0]
            if len(first_row) > i_jockey:
                last_jockey_map[ln] = _clean_jockey(first_row[i_jockey])
            for run in data:
                if len(run) <= max(i_jockey, i_finish):
                    continue
                jk = _clean_jockey(run[i_jockey])
                if not jk:
                    continue
                fin = _parse_finish(run[i_finish])
                if fin is None:
                    continue
                key = (ln, jk)
                if key not in hj_map:
                    hj_map[key] = {"n":0, "place":0, "wins":0}
                b = hj_map[key]
                b["n"] += 1
                if fin <= 2: b["place"] += 1
                if fin == 1: b["wins"] += 1
                h_stat = horse_stats[ln]
                h_stat["n"] += 1
                if fin <= 2: h_stat["place"] += 1
                if fin == 1: h_stat["wins"] += 1
                j_stat = jockey_stats[jk]
                j_stat["n"] += 1
                if fin <= 2: j_stat["place"] += 1
                if fin == 1: j_stat["wins"] += 1
        last_ln = rows[-1][0]
        if len(rows) < PAGE:
            break
        if n % 3000 == 0:
            _log(f"  horse_details: {n}")
    _log(f"horse_details done: {n} hj_map: {len(hj_map)}")
    return hj_map, horse_stats, jockey_stats, last_jockey_map


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    h = url.replace("libsql://", "https://").replace("wss://", "https://")
    c = libsql_client.create_client_sync(url=h, auth_token=token)

    _log("building maps")
    hj_map, horse_stats, jockey_stats, last_jockey_map = build_hj_map(c)

    # 全体平均連対率
    total_n = sum(s["n"] for s in horse_stats.values())
    total_place = sum(s["place"] for s in horse_stats.values())
    overall_pr = total_place / total_n if total_n else 0
    _log(f"overall place_rate: {overall_pr:.4f}")

    # (ln, jk) -> residual (連対率の残差)
    MIN_HJ_N = 3
    residual_map = {}
    for key, b in hj_map.items():
        if b["n"] < MIN_HJ_N:
            continue
        ln, jk = key
        actual = b["place"] / b["n"]
        h_stat = horse_stats[ln]
        j_stat = jockey_stats[jk]
        h_pr = h_stat["place"] / h_stat["n"] if h_stat["n"] else overall_pr
        j_pr = j_stat["place"] / j_stat["n"] if j_stat["n"] else overall_pr
        residual = actual - h_pr - j_pr + overall_pr
        residual_map[key] = residual
    _log(f"residual_map: {len(residual_map)}")

    # 残差分位境界（n>=3 の中で）
    res_vals = sorted(residual_map.values())
    if not res_vals:
        _log("no residuals")
        return
    def q(p):
        return res_vals[int(len(res_vals) * p)]
    bounds = [q(0.2), q(0.4), q(0.6), q(0.8)]
    _log("residual bounds: " + str([round(x, 4) for x in bounds]))

    def res_bin(r):
        if r is None: return "履歴なし"
        if r <= bounds[0]: return "相性 下位20%"
        if r <= bounds[1]: return "相性 20-40%"
        if r <= bounds[2]: return "相性 40-60%"
        if r <= bounds[3]: return "相性 60-80%"
        return "相性 上位20%"

    def new_bucket():
        return {"n":0, "wins":0, "market_sum":0.0, "market_n":0}

    by_res = defaultdict(new_bucket)
    by_res_change = defaultdict(new_bucket)

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
                jockey_rr = {}
                ln_map = {}
                for rr in result_runners:
                    num = rr.get("horse_number")
                    f = rr.get("finish")
                    jk = rr.get("jockey") or ""
                    if num:
                        try:
                            if f: fin_map[int(num)] = int(f)
                            if jk: jockey_rr[int(num)] = _clean_jockey(jk)
                        except (ValueError, TypeError):
                            pass
                for run in runners:
                    num = run.get("horse_number")
                    ln = run.get("lineage_nb") or run.get("horse_id") or ""
                    if num and ln:
                        try: ln_map[int(num)] = str(ln)
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
                    ln = ln_map.get(int(num))
                    if not ln:
                        continue
                    cur_jk = jockey_rr.get(int(num)) or _clean_jockey(run.get("jockey"))
                    if not cur_jk:
                        continue
                    n_matched += 1
                    res = residual_map.get((ln, cur_jk))
                    if res is None:
                        n_unknown += 1
                    mp = (1.0 / ow) / inv_sum
                    hit = 1 if fin == 1 else 0

                    def add(b, key):
                        x = b[key]
                        x["n"] += 1
                        x["wins"] += hit
                        x["market_sum"] += mp
                        x["market_n"] += 1

                    add(by_res, res_bin(res))
                    # 乗り替わり交絡
                    last_jk = last_jockey_map.get(ln)
                    if last_jk is not None:
                        chg = "乗り替わり" if cur_jk != last_jk else "継続騎乗"
                        add(by_res_change, f"{res_bin(res)}|{chg}")
                n_races += 1
            last_rid = rows[-1][0]
            if len(rows) < PAGE:
                break
            if n_races % 3000 == 0:
                _log(f"  races: {n_races}")
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
        "by_residual": to_rows(by_res),
        "by_residual_change": to_rows(by_res_change, 100),
        "bounds": bounds,
        "overall_place_rate": overall_pr,
        "n_races": n_races,
        "n_matched": n_matched,
        "generated_at": datetime.now().isoformat(),
    }

    try:
        c.execute(
            "CREATE TABLE IF NOT EXISTS horse_jockey_residual_cache ("
            "id INTEGER PRIMARY KEY, payload TEXT NOT NULL, generated_at TEXT NOT NULL)"
        )
        pj = json.dumps(result, ensure_ascii=False)
        c.execute(
            "INSERT INTO horse_jockey_residual_cache (id, payload, generated_at) VALUES (1, ?, ?) "
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
