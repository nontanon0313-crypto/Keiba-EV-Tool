"""年齢・性別の効果を分析する。

年齢別、性別、年齢×クラス、年齢×距離帯で
実1着率と市場期待を比較し、4歳有利の原因を確定させる。

保存先: age_analysis_cache
"""
import os
import json
import re
from datetime import datetime
from collections import defaultdict

import libsql_client

LOG_PATH = "age_analysis.log"
EXCLUDED_TRACK_CODES = ("03",)


def _log(msg):
    line = "[" + datetime.now().strftime("%H:%M:%S") + "] " + msg
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _parse_age_sex(s):
    if not s:
        return None, None
    # result_runners は「セン」表記、runners は「セ」表記
    m = re.match(r"(牡|牝|セン|セ)\s*(\d+)", str(s))
    if not m:
        return None, None
    sex = m.group(1)
    if sex == "セン":
        sex = "セ"
    return sex, int(m.group(2))


def _parse_class(name):
    if not name:
        return None
    t = name.translate(str.maketrans("ＡＢＣ１２３４５６７８９０", "ABC1234567890"))
    m = re.search(r"([ABC])([1-3])", t)
    if m:
        return m.group(1) + m.group(2)
    m2 = re.search(r"(\d)歳", t)
    if m2:
        return m2.group(1) + "歳"
    if "新馬" in name:
        return "新馬"
    return None


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


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    h = url.replace("libsql://", "https://").replace("wss://", "https://")
    c = libsql_client.create_client_sync(url=h, auth_token=token)

    def new_bucket():
        return {"n": 0, "wins": 0, "market_sum": 0.0, "market_n": 0}

    # 年齢別
    by_age = defaultdict(new_bucket)
    # 性別別
    by_sex = defaultdict(new_bucket)
    # 年齢×性別
    by_age_sex = defaultdict(new_bucket)
    # 年齢×クラス
    by_age_class = defaultdict(new_bucket)
    # 年齢×距離帯
    by_age_dist = defaultdict(new_bucket)
    # 年齢×斤量
    by_age_weight = defaultdict(new_bucket)

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
                cls = _parse_class(d.get("race_name"))
                dist_b = _distance_band(d.get("distance"))
                runners = d.get("runners") or []
                result_runners = d.get("result_runners") or []
                fin_map = {}
                # result_runners から正確な性別を取得（runners はセを牡と誤記）
                sex_map = {}
                for rr in result_runners:
                    num = rr.get("horse_number")
                    f = rr.get("finish")
                    if num and f:
                        try:
                            fin_map[int(num)] = int(f)
                        except (ValueError, TypeError):
                            pass
                    ag = rr.get("age_sex") or ""
                    sex, age = _parse_age_sex(ag)
                    if num and sex and age:
                        try:
                            sex_map[int(num)] = (sex, age)
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
                    # result_runners の性別を優先（runners はセが牡扱い）
                    num_int = int(num)
                    sex = None
                    age = None
                    if num_int in sex_map:
                        sex, age = sex_map[num_int]
                    else:
                        age_sex_str = run.get("age_sex") or ""
                        sex, age = _parse_age_sex(age_sex_str)
                    if not sex or not age:
                        continue
                    wt = _to_num(run.get("weight"))

                    hit = 1 if fin == 1 else 0
                    def add(b, key):
                        x = b[key]
                        x["n"] += 1
                        x["wins"] += hit
                        x["market_sum"] += mp
                        x["market_n"] += 1

                    add(by_age, age)
                    add(by_sex, sex)
                    add(by_age_sex, f"{age}歳{sex}")
                    if cls:
                        add(by_age_class, f"{age}歳_{cls}")
                    if dist_b:
                        add(by_age_dist, f"{age}歳_{dist_b}")
                    if wt is not None:
                        add(by_age_weight, f"{age}歳_{int(wt)}kg")
                n_races += 1
            last_rid = rows[-1][0]
            if len(rows) < PAGE:
                break
            if n_races % 3000 == 0:
                _log("  races: " + str(n_races))
    finally:
        pass
    _log("races: " + str(n_races))

    def to_rows(b, min_n=100):
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
        "by_age": to_rows(by_age),
        "by_sex": to_rows(by_sex),
        "by_age_sex": to_rows(by_age_sex),
        "by_age_class": to_rows(by_age_class, 200),
        "by_age_dist": to_rows(by_age_dist, 200),
        "by_age_weight": to_rows(by_age_weight, 100),
        "n_races": n_races,
        "generated_at": datetime.now().isoformat(),
    }

    try:
        c.execute(
            "CREATE TABLE IF NOT EXISTS age_analysis_cache ("
            "id INTEGER PRIMARY KEY, payload TEXT NOT NULL, generated_at TEXT NOT NULL)"
        )
        pj = json.dumps(result, ensure_ascii=False)
        c.execute(
            "INSERT INTO age_analysis_cache (id, payload, generated_at) VALUES (1, ?, ?) "
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
