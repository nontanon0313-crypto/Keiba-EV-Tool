"""馬×騎手の組み合わせ効果を分析する。

手順:
1. horse_details をページングして、馬×騎手の通算成績マップを構築
2. scraped_races をページングして、各レースの各馬について:
   - 現在の騎手と馬の組み合わせ成績
   - 乗り替わり / 継続騎乗
   - 馬×騎手 出走回数、連対率
   で集計し、実1着率と市場期待を比較

保存先: horse_jockey_analysis_cache
"""
import os
import json
import re
from datetime import datetime
from collections import defaultdict

import libsql_client

LOG_PATH = "horse_jockey.log"
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
    # 記号と所属（括弧内）を除去
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


def build_horse_jockey_map(c):
    """horse_details をページングして馬×騎手の通算成績を構築する。

    Returns:
        hj_map: {(lineage_nb, jockey) -> {n, wins, place, show, finish_sum}}
        last_jockey_map: {lineage_nb -> last_jockey}
    """
    hj_map = {}
    last_jockey_map = {}
    last_ln = ""
    PAGE = 200
    n_processed = 0
    while True:
        r = c.execute(
            "SELECT lineage_nb, payload FROM horse_details WHERE lineage_nb > ? ORDER BY lineage_nb LIMIT ?",
            [last_ln, PAGE],
        )
        rows = list(r.rows)
        if not rows:
            break
        for row in rows:
            n_processed += 1
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
            # 列インデックス
            try:
                i_jockey = header.index("騎手")
            except ValueError:
                i_jockey = None
            try:
                i_finish = header.index("着順")
            except ValueError:
                i_finish = None
            if i_jockey is None or i_finish is None:
                continue
            # 最新走の騎手
            first_row = data[0]
            if len(first_row) > i_jockey:
                last_jockey_map[ln] = _clean_jockey(first_row[i_jockey])
            # 各走を集計
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
                    hj_map[key] = {"n": 0, "wins": 0, "place": 0, "show": 0, "finish_sum": 0}
                b = hj_map[key]
                b["n"] += 1
                if fin == 1: b["wins"] += 1
                if fin <= 2: b["place"] += 1
                if fin <= 3: b["show"] += 1
                b["finish_sum"] += fin
        last_ln = rows[-1][0]
        if len(rows) < PAGE:
            break
        if n_processed % 3000 == 0:
            _log(f"  horse_details: {n_processed} (hj_map size: {len(hj_map)})")
    _log(f"horse_details done: {n_processed} hj_map: {len(hj_map)}")
    return hj_map, last_jockey_map


def _n_bin(v):
    if v is None: return "履歴なし"
    if v == 0: return "履歴なし"
    if v <= 1: return "1走"
    if v <= 3: return "2-3走"
    return "4走+"


def _place_rate_bin(wins, place, n):
    if n == 0: return None
    r = place / n
    if r == 0: return "連対0"
    if r < 0.2: return "連対0-0.2"
    if r < 0.5: return "連対0.2-0.5"
    return "連対0.5+"


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    h = url.replace("libsql://", "https://").replace("wss://", "https://")
    c = libsql_client.create_client_sync(url=h, auth_token=token)

    _log("building horse-jockey map")
    hj_map, last_jockey_map = build_horse_jockey_map(c)

    def new_bucket():
        return {"n": 0, "wins": 0, "market_sum": 0.0, "market_n": 0}

    by_change = defaultdict(new_bucket)
    by_hj_n = defaultdict(new_bucket)
    by_hj_pr = defaultdict(new_bucket)
    by_change_hj_n = defaultdict(new_bucket)

    n_races = 0
    n_matched = 0
    n_jockey_known = 0
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
                            if f:
                                fin_map[int(num)] = int(f)
                            if jk:
                                jockey_rr[int(num)] = _clean_jockey(jk)
                        except (ValueError, TypeError):
                            pass
                for run in runners:
                    num = run.get("horse_number")
                    ln = run.get("lineage_nb") or run.get("horse_id") or ""
                    if num and ln:
                        try:
                            ln_map[int(num)] = str(ln)
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
                    # 現在の騎手（result 優先、なければ runners）
                    cur_jk = jockey_rr.get(int(num)) or _clean_jockey(run.get("jockey"))
                    if not cur_jk:
                        continue
                    n_matched += 1
                    # 過去の乗り履歴
                    last_jk = last_jockey_map.get(ln)
                    if last_jk is not None:
                        is_change = (cur_jk != last_jk)
                        n_jockey_known += 1
                    else:
                        is_change = None
                    hj = hj_map.get((ln, cur_jk))
                    hj_n = hj["n"] if hj else 0
                    hj_place = hj["place"] if hj else 0
                    hj_wins = hj["wins"] if hj else 0

                    mp = (1.0 / ow) / inv_sum
                    hit = 1 if fin == 1 else 0

                    def add(b, key):
                        x = b[key]
                        x["n"] += 1
                        x["wins"] += hit
                        x["market_sum"] += mp
                        x["market_n"] += 1

                    # 乗り替わり区分
                    if is_change is None:
                        add(by_change, "前走不明")
                    elif is_change:
                        add(by_change, "乗り替わり")
                    else:
                        add(by_change, "継続騎乗")
                    # 馬×騎手の出走回数
                    add(by_hj_n, _n_bin(hj_n))
                    # 馬×騎手の連対率
                    prb = _place_rate_bin(hj_wins, hj_place, hj_n)
                    if prb:
                        add(by_hj_pr, prb)
                    # 乗り替わり×出走回数
                    if is_change is not None:
                        chg = "乗り替わり" if is_change else "継続騎乗"
                        add(by_change_hj_n, f"{chg}|{_n_bin(hj_n)}")
                n_races += 1
            last_rid = rows[-1][0]
            if len(rows) < PAGE:
                break
            if n_races % 3000 == 0:
                _log("  races: " + str(n_races))
    finally:
        pass
    _log(f"races: {n_races} matched: {n_matched} jockey_known: {n_jockey_known}")

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
        "by_change": to_rows(by_change),
        "by_hj_n": to_rows(by_hj_n),
        "by_hj_pr": to_rows(by_hj_pr),
        "by_change_hj_n": to_rows(by_change_hj_n, 100),
        "n_races": n_races,
        "n_matched": n_matched,
        "generated_at": datetime.now().isoformat(),
    }

    try:
        c.execute(
            "CREATE TABLE IF NOT EXISTS horse_jockey_analysis_cache ("
            "id INTEGER PRIMARY KEY, payload TEXT NOT NULL, generated_at TEXT NOT NULL)"
        )
        pj = json.dumps(result, ensure_ascii=False)
        c.execute(
            "INSERT INTO horse_jockey_analysis_cache (id, payload, generated_at) VALUES (1, ?, ?) "
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
