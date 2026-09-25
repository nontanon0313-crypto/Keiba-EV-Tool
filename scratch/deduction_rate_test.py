"""控除率テスト：全通り購入ROIが控除率と一致するか検証。
20レースで券種別ROIを計算。読み取り専用。
"""
import os
import json
import math
import time
from collections import defaultdict

import httpx
import libsql_client

import backend.scraper.oddspark_keiba as ok

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}


def combo(n, k):
    return math.comb(n, k) if n >= k else 0


def perm(n, k):
    return math.perm(n, k) if n >= k else 0


def parse_money(s):
    if not isinstance(s, str):
        return 0
    if "発売なし" in s:
        return 0
    s = s.replace(",", "").replace("円", "").strip()
    try:
        return int(s)
    except ValueError:
        return 0


def calc_all_ticket_roi(parsed):
    runners = parsed.get("runners", [])
    payouts = parsed.get("payouts", {})
    if not runners or not payouts:
        return None
    N = len(runners)
    result = {}
    specs = {
        "単勝":   (N,             ["単勝"]),
        "複勝":   (N,             ["複勝"]),
        "馬連":   (combo(N, 2),   ["馬連"]),
        "馬単":   (perm(N, 2),    ["馬単"]),
        "ワイド": (combo(N, 2),   ["ワイド"]),
        "3連複":  (combo(N, 3),   ["3連複"]),
        "3連単":  (perm(N, 3),    ["3連単"]),
    }
    for ticket, (num_combo, keys) in specs.items():
        if num_combo <= 0 or ticket not in payouts:
            continue
        rows = payouts[ticket]
        total_payout = 0
        for row in rows:
            amt = 0
            for cell in row:
                if isinstance(cell, str) and cell.endswith("円"):
                    amt = parse_money(cell)
                    break
            total_payout += amt
        stake = num_combo * 100
        result[ticket] = {
            "N": N,
            "combos": num_combo,
            "stake": stake,
            "payout": total_payout,
            "roi": total_payout / stake * 100.0,
        }
    return result


def fetch_result(client, date, track, race_nb):
    sp_candidates = {"43": ["33"], "55": ["29"]}
    sp_list = sp_candidates.get(track, ["03"])
    for sp in sp_list:
        url = f"https://www.oddspark.com/keiba/RaceResult.do?sponsorCd={sp}&raceDy={date}&opTrackCd={track}&raceNb={race_nb}"
        try:
            r = client.get(url)
            if r.status_code == 200 and len(r.text) > 15000:
                return r.text
        except Exception:
            pass
    return None


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    client = libsql_client.create_client_sync(url=http_url, auth_token=token)

    r = client.execute(
        "SELECT race_id, payload FROM scraped_races "
        "WHERE race_id LIKE 'nar-2023%' ORDER BY race_id LIMIT 400"
    )
    rows = list(r.rows)

    targets = []
    for row in rows:
        try:
            p = json.loads(row[1])
        except Exception:
            continue
        if p.get("result_runners") and p.get("payouts"):
            targets.append((row[0], p))
        if len(targets) >= 20:
            break

    print(f"対象レース: {len(targets)}\n")

    agg = defaultdict(lambda: {"stake": 0, "payout": 0, "races": 0})

    with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
        c.get("https://www.oddspark.com/keiba/")
        time.sleep(1)
        for rid, p in targets:
            parts = rid.split("-")
            date, track, rn = parts[1], parts[2], parts[3]
            html = fetch_result(c, date, track, rn)
            if html is None:
                print(f"[{rid}] 取得失敗")
                continue
            parsed = ok.parse_result(html, rid)
            if not parsed:
                print(f"[{rid}] parse None")
                continue

            roi = calc_all_ticket_roi(parsed)
            if not roi:
                print(f"[{rid}] ROI計算不可")
                continue

            print(f"[{rid}] N={roi['馬連']['N']} "
                  f"馬連ROI={roi['馬連']['roi']:.1f}% "
                  f"3連単ROI={roi['3連単']['roi']:.1f}%")
            for t, d in roi.items():
                agg[t]["stake"] += d["stake"]
                agg[t]["payout"] += d["payout"]
                agg[t]["races"] += 1
            time.sleep(1.2)

    print("\n=== 券種別 全通り購入ROI（合算） ===")
    print(f"{'券種':<8} {'レース':>6} {'購入':>14} {'払戻':>14} {'ROI%':>8} {'想定控除後%':>12}")
    expected = {"単勝": 20, "複勝": 20, "馬連": 22.5, "馬単": 22.5,
                "ワイド": 22.5, "3連複": 25, "3連単": 25}
    for t in ["単勝", "複勝", "馬連", "馬単", "ワイド", "3連複", "3連単"]:
        a = agg[t]
        if a["races"] == 0:
            continue
        roi_pct = a["payout"] / a["stake"] * 100.0
        exp_roi = 100 - expected[t]
        print(f"{t:<8} {a['races']:>6} {a['stake']:>14} {a['payout']:>14} "
              f"{roi_pct:>8.2f} {exp_roi:>12.1f}")

    try:
        client.close()
    except Exception:
        pass


main()
import os
os._exit(0)
